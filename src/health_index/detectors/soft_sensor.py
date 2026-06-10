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
from sklearn.cross_decomposition import PLSRegression
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import RBF, ConstantKernel, WhiteKernel

from ..config import DEFAULT, Config


def _split_conformal_q(scores: np.ndarray, *, n_min: int, alpha: float) -> float | None:
    """split-CP 非一致性分位（model-agnostic，GPR/PLS 共用）：``scores``=校準絕對殘差。

    Returns:
        cp 半寬 q（第 k 小殘差），或 ``None``——兩情形：calibration < n_min；或
        k=ceil((n+1)(1−α))>n（+∞分位，無法以有限區間達標，紅隊 R-1）。
    """
    scores = np.asarray(scores, dtype=float)
    n = scores.shape[0]
    if n < n_min:
        return None
    k = int(np.ceil((n + 1) * (1.0 - alpha)))
    if k > n:
        return None
    return float(np.sort(scores)[k - 1])


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


@dataclass
class PLSSoftSensor:
    """PLS 軟測量 + split-CP——**可擴展**(O(n·p·k)) 且對**共線/高維 X 穩健**，補 GPR(O(n³)、RBF 高維退化)
    在「多製程參數 + 大資料集」的不足（桶2，泛化）。PLS 投影到潛在成分天然處理共線，多輸出 Y 友善
    （本版以純量 Y 對齊既有 ``Y_VALUE`` 契約）。

    與 ``SoftSensor`` **同介面**（fit/predict/calibrate_cp/cp_available/predict_interval），可由
    ``make_soft_sensor`` 依資料規模互換。可信度層同採 split-CP（model-agnostic，與 GPR 版共用
    ``_split_conformal_q``）。確定性（Rule 5）：PLS 為確定性解，無隨機。
    """

    config: Config = field(default=DEFAULT)
    method: str = "pls"  # 供上層（server band_kind）辨識基底；SoftSensor 無此屬性→預設 "gpr"

    def fit(self, X: np.ndarray, y: np.ndarray) -> "PLSSoftSensor":
        """以 golden-A 的 (X, Y) 訓練 PLS（只用 y 有觀測的列）。成分數 cap 至 min(p, n_obs−1)。"""
        X = np.asarray(X, dtype=float)
        y = np.asarray(y, dtype=float)
        obs = np.isfinite(y)
        if int(obs.sum()) < 2:
            raise ValueError("有效 (X, y) 觀測不足（< 2），無法訓練軟測量")
        Xo, yo = X[obs], y[obs]
        self.x_mean_ = Xo.mean(axis=0)
        self.x_std_ = Xo.std(axis=0) + 1e-9
        Xs = (Xo - self.x_mean_) / self.x_std_
        ncomp = max(1, min(self.config.pls_components, Xs.shape[1], len(yo) - 1))
        self.n_components_ = ncomp
        self.pls_ = PLSRegression(n_components=ncomp, scale=False).fit(Xs, yo)
        resid = yo - self.pls_.predict(Xs).ravel()
        self.resid_std_ = float(resid.std()) + 1e-9  # 同方差殘差 std（無 CP 時可信帶 fallback）
        self.cp_q_: float | None = None
        return self

    def predict(self, X: np.ndarray, return_std: bool = False):
        """PLS 預測 Ŷ（return_std=True 時另回**同方差**殘差 std，PLS 無後驗變異）。需先 fit()。"""
        if not hasattr(self, "pls_"):
            raise RuntimeError("須先呼叫 fit()")
        Xs = (np.asarray(X, dtype=float) - self.x_mean_) / self.x_std_
        yhat = self.pls_.predict(Xs).ravel()
        if return_std:
            return yhat, np.full(len(yhat), self.resid_std_)
        return yhat

    def calibrate_cp(self, X_cal: np.ndarray, y_cal: np.ndarray) -> "PLSSoftSensor":
        """split-CP 校準（X_cal 須與 fit 的 X 不重疊以維 exchangeability）；不足則 cp_available=False。"""
        X_cal = np.asarray(X_cal, dtype=float)
        y_cal = np.asarray(y_cal, dtype=float)
        obs = np.isfinite(y_cal)
        Xc, yc = X_cal[obs], y_cal[obs]
        scores = np.abs(yc - self.predict(Xc)) if yc.shape[0] else np.empty(0)
        self.cp_q_ = _split_conformal_q(scores, n_min=self.config.cp_min_calibration, alpha=self.config.cp_alpha)
        return self

    @property
    def cp_available(self) -> bool:
        return self.cp_q_ is not None

    def predict_interval(self, X: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """split-CP 預測區間 (lo, hi)，覆蓋率有限樣本保證 ≥ 1−α。"""
        if not self.cp_available:
            raise RuntimeError("CP 未校準或 calibration 不足；改用 GSI 無標籤可信度（紅隊 H1）")
        yhat = self.predict(X)
        return yhat - self.cp_q_, yhat + self.cp_q_


def make_soft_sensor(config: Config = DEFAULT, *, n_samples: int, n_features: int):
    """依資料規模選軟測量基底（泛化選擇器，桶2）：

    - **高維**（n_features > ``soft_sensor_pls_min_features``）或 **大 n**（n_samples >
      ``soft_sensor_pls_min_samples``）→ ``PLSSoftSensor``（可擴展、共線穩健）。
    - 否則 → ``SoftSensor``（GPR，小資料非線性 + 後驗不確定度友善）。

    回傳已建構**未 fit** 的實例（兩者同介面）。既有 synthetic(p=10)/tep(p=22) 小資料 → GPR，
    行為不變（向後相容）；高維集（如 uci p=128）→ PLS。
    """
    if n_features > config.soft_sensor_pls_min_features or n_samples > config.soft_sensor_pls_min_samples:
        return PLSSoftSensor(config)
    return SoftSensor(config)
