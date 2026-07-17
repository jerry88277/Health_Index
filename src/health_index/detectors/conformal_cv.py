"""L3 小 n 可信度：CV+/jackknife+ conformal（Barber, Candès, Ramdas & Tibshirani,
"Predictive inference with the jackknife+", Ann. Statist. 49(1):486–507, 2021；
VERIFIED DOI 10.1214/20-AOS1965，見 docs/literature_crossref.md §1「Conformal 補登」）。

為何存在：split-CP 需**不相交** calibration（``cp_min_calibration``=200）；本專案 golden 為
單一 campaign（n 常 <200）→ split-CP 退回 GSI、Ŷ 失去可信區間。CV+/jackknife+ 以 K-fold
leave-fold-out 讓**每一點 both fit both 校準**，故小 n 仍可上線——**自有門檻 ``cv_plus_min_obs``，
獨立於 ``cp_min_calibration``**（紅隊 must-fix #1：兩者為不同估計器，不得共用 200 門檻，否則對
「正是要救的 n<200」失效）。

覆蓋（誠實口徑，紅隊 A11 / must-fix #2）：CV+/jackknife+ 為 worst-case **≥1−2α**（α=0.1→0.80），
實務常近 1−α，但**不得**沿用 split-CP 的 ≥1−α 宣稱。亦非抗漂移：re-entry 破 exchangeability 對
split-CP 與 CV+ 一視同仁；CV+ 只買「小 n 可用性」，不買「漂移下有效」。

確定性（Rule 5）：折分配按 index 取模（無 RNG）。
分工（Rule 3）：本模組為 batch-AVM / 小 n 路徑的**獨立**估計器，**不動** ``SoftSensor`` /
``PLSSoftSensor`` 的 split-CP（``calibrate_cp`` / ``cp_available`` / ``predict_interval``）與
``cp_min_calibration`` 契約。base estimator 由 ``make_estimator()`` 工廠提供（需具
``fit(X, y) -> self`` 與 ``predict(X)``，如 ``SoftSensor`` / ``PLSSoftSensor``）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from ..config import DEFAULT, Config


@dataclass
class CVPlusConformal:
    """CV+/jackknife+ 可信區間（小 n 路徑）。fit(make_estimator, X, y) → predict/predict_interval。

    Args:
        config: 全域超參（用 ``cp_alpha`` / ``cv_plus_folds`` / ``cv_plus_min_obs``）。
        n_folds: 折數 K；``None`` → ``config.cv_plus_folds``；``≥n`` → jackknife+（逐一 LOO，capped 至 n）。

    不變式：``predict_interval`` 的覆蓋為 worst-case ≥ ``coverage_floor``（=1−2α）。
    """

    config: Config = field(default=DEFAULT)
    n_folds: int | None = None
    band_kind: str = "CV+"

    @property
    def coverage_floor(self) -> float:
        """誠實最壞覆蓋底線 = 1−2α（非 split-CP 的 1−α）。"""
        return 1.0 - 2.0 * self.config.cp_alpha

    def fit(self, make_estimator: Callable[[], object], X: np.ndarray, y: np.ndarray) -> "CVPlusConformal":
        """以 K-fold leave-fold-out 建立 CV+ 殘差與各折模型。

        Args:
            make_estimator: 無參工廠，回傳**未 fit** 的 base estimator（具 fit/predict）。
            X, y: golden (X, Y)；只用 y 有觀測（finite）的列。

        不可用（``available`` 為 False，上層改用 GSI）：有效觀測 < ``cv_plus_min_obs``、
        K<2、或上分位 k=⌈(1−α)(n+1)⌉ > n（有限區間無法達標）。
        """
        X = np.asarray(X, dtype=float)
        y = np.asarray(y, dtype=float)
        obs = np.isfinite(y)
        X, y = X[obs], y[obs]
        n = int(y.shape[0])
        K = int(self.n_folds) if self.n_folds is not None else int(self.config.cv_plus_folds)
        K = max(1, min(K, n))
        self.n_folds_effective_ = K
        alpha = float(self.config.cp_alpha)
        k_hi = int(np.ceil((1.0 - alpha) * (n + 1)))  # q^+_{1−α} 序位
        self._available = (n >= self.config.cv_plus_min_obs) and (K >= 2) and (k_hi <= n)
        if not self._available:
            self.cv_resid_ = None
            return self
        fold_of = np.arange(n) % K  # 確定性折分配（無 RNG，Rule 5）
        self.fold_of_ = fold_of
        self.models_: list = []
        resid = np.empty(n, dtype=float)
        resid_signed = np.empty(n, dtype=float)
        for k in range(K):
            te = np.where(fold_of == k)[0]
            trn = np.where(fold_of != k)[0]
            model = make_estimator().fit(X[trn], y[trn])
            self.models_.append(model)
            pred = np.asarray(model.predict(X[te]), dtype=float).ravel()
            resid_signed[te] = y[te] - pred
            resid[te] = np.abs(y[te] - pred)
        self.cv_resid_ = resid
        self.cv_resid_signed_ = resid_signed  # out-of-fold **有號**殘差（殘差漂移監控的誠實 null）
        self.full_model_ = make_estimator().fit(X, y)  # 點預測用全資料模型
        self._n = n
        return self

    @property
    def available(self) -> bool:
        """CV+ 是否已建立且觀測足量。"""
        return bool(getattr(self, "_available", False)) and getattr(self, "cv_resid_", None) is not None

    def predict(self, X: np.ndarray) -> np.ndarray:
        """點預測 Ŷ（全資料模型）。需先 fit()。"""
        if not hasattr(self, "full_model_"):
            raise RuntimeError("須先呼叫 fit()")
        return np.asarray(self.full_model_.predict(np.asarray(X, dtype=float)), dtype=float).ravel()

    def predict_interval(self, X: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """CV+ 預測區間 (lo, hi)：``[q^-_α{μ_{-k(i)}(x)−R_i}, q^+_{1−α}{μ_{-k(i)}(x)+R_i}]``。

        worst-case 覆蓋 ≥ 1−2α（``coverage_floor``；紅隊 A11 誠實口徑，非 ≥1−α）。

        Raises:
            RuntimeError: CV+ 不可用（n < ``cv_plus_min_obs`` 等）；上層改用 GSI 可信度。
        """
        if not self.available:
            raise RuntimeError("CV+ 不可用（n < cv_plus_min_obs 或折不足）；改用 GSI 可信度（紅隊 H1）")
        X = np.asarray(X, dtype=float)
        n = self._n
        alpha = float(self.config.cp_alpha)
        fold_pred = np.stack(  # (K, n_test)：各 leave-fold-out 模型在測試點的預測
            [np.asarray(m.predict(X), dtype=float).ravel() for m in self.models_], axis=0
        )
        mu_i = fold_pred[self.fold_of_, :]  # (n, n_test)：列 i 用其所屬 fold 的模型
        R = self.cv_resid_[:, None]         # (n, 1)
        lower_vals = mu_i - R                # {μ_{-k(i)}(x) − R_i}
        upper_vals = mu_i + R                # {μ_{-k(i)}(x) + R_i}
        k_hi = min(max(int(np.ceil((1.0 - alpha) * (n + 1))), 1), n)  # 第 k_hi 小
        k_lo = min(max(int(np.floor(alpha * (n + 1))), 1), n)         # 第 k_lo 小
        hi = np.sort(upper_vals, axis=0)[k_hi - 1, :]
        lo = np.sort(lower_vals, axis=0)[k_lo - 1, :]
        return lo, hi
