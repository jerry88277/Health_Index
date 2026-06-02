"""L3 軟測量（soft sensor）：GPR 預測 Ŷ + split-Conformal 可信度。

取 AVM 初衷：以虛擬量測 Ŷ 取代破壞性/昂貴抽樣。可信度層採 **Conformal Prediction（CP）**
取代 AVM RI（紅隊 H1/C3）——CP 給 distribution-free、**有限樣本邊際覆蓋保證** P(y∈Ĉ)≥1−α，
而 RI 是 ad-hoc 雙模型重疊、無保證。base estimator 為 GPR（小資料友善、確定性）。

可信度雙路（紅隊 H1）：
- **有標籤且 calibration 足量**：split-CP 預測區間（本模組）。
- **無標籤/標籤稀少**：退回輸入域相似度（GSI，見 mspc.py）/ ICAD——由上層（M7 融合）orchestrate。
  本模組以 ``cp_available`` 旗標表達「calibration 是否足夠上線 CP」（紅隊：cp_min_calibration 門檻）。

時序 CP（EnbPI/ACI）**不宣稱覆蓋保證**（re-entry 非穩態、無線上 label 破其前提）——Phase 2。
偵測器確定性（Rule 5）：GPR ``n_restarts_optimizer=0`` + 固定 random_state。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import RBF, ConstantKernel, WhiteKernel

from ..config import DEFAULT, Config


@dataclass
class SoftSensor:
    """GPR 軟測量 + split-CP 可信度。fit→（calibrate_cp）→predict/predict_interval。"""

    config: Config = field(default=DEFAULT)

    def fit(self, X: np.ndarray, y: np.ndarray) -> "SoftSensor":
        """以 golden-A 的 (X, Y) 訓練 GPR（只用 y 有觀測的列）。"""
        X = np.asarray(X, dtype=float)
        y = np.asarray(y, dtype=float)
        obs = np.isfinite(y)
        if int(obs.sum()) < 2:
            raise ValueError("有效 (X, y) 觀測不足（< 2），無法訓練軟測量")
        Xo, yo = X[obs], y[obs]
        self.x_mean_ = Xo.mean(axis=0)
        self.x_std_ = Xo.std(axis=0) + 1e-9
        Xs = (Xo - self.x_mean_) / self.x_std_
        kernel = ConstantKernel(1.0) * RBF(length_scale=1.0) + WhiteKernel(0.1)
        self.gpr_ = GaussianProcessRegressor(
            kernel=kernel,
            normalize_y=True,
            random_state=self.config.random_state,
            n_restarts_optimizer=0,  # 確定性（無隨機重啟）
        ).fit(Xs, yo)
        self.cp_q_: float | None = None
        return self

    def predict(self, X: np.ndarray, return_std: bool = False):
        """GPR 預測 Ŷ（return_std=True 時另回 GPR 後驗標準差）。需先 fit()。"""
        if not hasattr(self, "gpr_"):
            raise RuntimeError("須先呼叫 fit()")
        Xs = (np.asarray(X, dtype=float) - self.x_mean_) / self.x_std_
        return self.gpr_.predict(Xs, return_std=return_std)

    def calibrate_cp(self, X_cal: np.ndarray, y_cal: np.ndarray) -> "SoftSensor":
        """以 calibration set 校準 split-CP（X_cal 須與 fit 的 X **不重疊**以維 exchangeability）。

        不啟用 CP（cp_available=False，退回 GSI）的兩種情形：
            - calibration 觀測點 < cp_min_calibration；
            - α 過小使 k=ceil((n+1)(1−α)) > n（conformal 分位為 +∞，無法以有限區間達標，紅隊 R-1）。
        """
        X_cal = np.asarray(X_cal, dtype=float)
        y_cal = np.asarray(y_cal, dtype=float)
        obs = np.isfinite(y_cal)
        Xc, yc = X_cal[obs], y_cal[obs]
        if yc.shape[0] < self.config.cp_min_calibration:
            self.cp_q_ = None
            return self
        scores = np.abs(yc - self.predict(Xc))  # nonconformity = 絕對殘差
        n = scores.shape[0]
        k = int(np.ceil((n + 1) * (1.0 - self.config.cp_alpha)))  # split-CP 有限樣本秩
        if k > n:
            self.cp_q_ = None  # +∞ 分位：無法以有限區間達標 → 退回 GSI（不靜默近似，紅隊 R-1）
            return self
        self.cp_q_ = float(np.sort(scores)[k - 1])  # 第 k 小殘差（精確序統計，非 numpy 分位的 +1 保守）
        return self

    @property
    def cp_available(self) -> bool:
        """CP 是否已校準且 calibration 足量。"""
        return self.cp_q_ is not None

    def predict_interval(self, X: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """回傳 split-CP 預測區間 (lo, hi)，覆蓋率有限樣本保證 ≥ 1−α。

        Raises:
            RuntimeError: 未校準或 calibration 不足（cp_available=False）；上層應改用 GSI 可信度。
        """
        if not self.cp_available:
            raise RuntimeError("CP 未校準或 calibration 不足；改用 GSI 無標籤可信度（紅隊 H1）")
        yhat = self.predict(X)
        return yhat - self.cp_q_, yhat + self.cp_q_
