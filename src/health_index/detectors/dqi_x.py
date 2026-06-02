"""L1 資料效度閘：sanity check + FastMCD 抗污染協方差 + DQI_x（PCA Euclidean 距離）。

依 ``docs/avm_metrics_definitions.md`` §2：
- **DQI_x**：PCA 取 k 顯著主成分投影，DQI_x = 在 k 維特徵空間對模型集中心的 **Euclidean**
  距離（不加權，非 Mahalanobis；與 GSI 區別）。

**對 AVM 原文的刻意偏離（Rule 12 留痕）**：
1. 中心採 MCD **robust location** 取代 AVM 原文的特徵 sample mean——抗污染。
2. 協方差採 **FastMCD**（MinCovDet）取代 sample covariance——抗污染。
3. 門檻採 **MCD support（robust inlier 子集）內**的 90% trimmed mean × factor，取代 AVM 的
   LOO 90% trimmed mean。理由：(a) in-sample≈LOO（robust center 不隨單點 refit 收縮，實測比
   ≈1.002）；(b) **關鍵**——若用全部點的 in-sample trimmed mean，當污染率 > trim 比例時污染會
   洩入門檻把它吹大（紅隊實證 mag=6/5% 下漏 73% 離群）；改用 MCD support 內的點可排除污染。

- **sanity check**（NaN/凍結/超界）是 AVM DQI_x 所無的工程性補強（紅隊：DQI_x 不含原始效度檢查）。

層分離與落地風險（紅隊 surface）：L1 是域/效度閘，**只量 k-PC 子空間內的距離**；正交於 golden
主成分的域移（如某些換產品位移）會落在殘差空間，L1 抓不到——那是 L2 SPE 的職責。故 L1 對
「換產品資料」的攔截率**資料相依**；golden 純淨性的最終保障靠 L2 SPE + L4 campaign 漂移，不靠 L1。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.stats import trim_mean
from sklearn.covariance import MinCovDet

from ..config import DEFAULT, Config


def sanity_check(
    X: np.ndarray,
    *,
    bounds: tuple[np.ndarray, np.ndarray] | None = None,
    frozen_window: int = 5,
) -> np.ndarray:
    """回傳每列是否物理有效的 bool 遮罩（True=有效）。

    無效條件（任一成立即無效）：
        - 含 NaN/Inf。
        - 超出 bounds（low, high）逐欄界限。
        - 凍結：連續 ``frozen_window`` 個**完全相同**的樣本（DCS freeze / 通訊中斷），其第
          ``frozen_window`` 列起被標無效。

    Args:
        X: (n, p) 製程參數。
        bounds: (low, high) 各為 (p,) 物理界限；None 則跳過界限檢查。
        frozen_window: 判定凍結所需的連續相同樣本數（<2 則停用）。

    Returns:
        (n,) bool 遮罩。
    """
    X = np.asarray(X, dtype=float)
    n = len(X)
    valid = np.isfinite(X).all(axis=1)
    if bounds is not None:
        low, high = bounds
        valid &= ~((X < low) | (X > high)).any(axis=1)
    if frozen_window and frozen_window >= 2 and n >= frozen_window:
        same_as_prev = np.zeros(n, dtype=bool)
        same_as_prev[1:] = (X[1:] == X[:-1]).all(axis=1)
        run = np.zeros(n, dtype=int)
        for i in range(1, n):  # 連續「與前列相同」的長度；L 個相同樣本 → run 峰值 L-1
            run[i] = run[i - 1] + 1 if same_as_prev[i] else 0
        valid &= run < (frozen_window - 1)  # 連續 frozen_window 個相同樣本即觸發
    return valid


@dataclass
class DQIxGate:
    """DQI_x 域效度閘：golden-A 上 fit 並凍結，對新樣本算 DQI_x 與 inlier 判定。

    Attributes:
        config: 提供 mcd_support_fraction / random_state / pca_var_explained / dqi_x_threshold_factor。
        robust: True=FastMCD 抗污染中心/協方差 + support 內門檻；False=sample mean/cov + 全點門檻
            （非 robust，僅供 ablation/對照，會被污染毒化）。
    """

    config: Config = field(default=DEFAULT)
    robust: bool = True

    def fit(self, X_golden: np.ndarray) -> "DQIxGate":
        """以 golden-A 建立標準化、（robust）中心/協方差、PCA 載荷與 DQI_x 門檻（凍結）。"""
        X = np.asarray(X_golden, dtype=float)
        if self.robust:
            # robust 標準化（median/MAD）：否則污染會膨脹 sample std、壓縮離群距離，
            # 使 robust 協方差也救不回來（紅隊：標準化步驟本身也須 robust）。
            self.mean_ = np.median(X, axis=0)
            self.std_ = 1.4826 * np.median(np.abs(X - self.mean_), axis=0) + 1e-9
        else:
            self.mean_ = X.mean(axis=0)
            self.std_ = X.std(axis=0) + 1e-9
        Xs = (X - self.mean_) / self.std_
        if self.robust:
            mcd = MinCovDet(
                support_fraction=self.config.mcd_support_fraction,
                random_state=self.config.random_state,
            ).fit(Xs)
            self.center_ = mcd.location_
            cov = mcd.covariance_
            support = mcd.support_  # robust inlier 遮罩 → 門檻排除污染
        else:
            self.center_ = Xs.mean(axis=0)
            cov = np.cov(Xs, rowvar=False)
            support = np.ones(len(Xs), dtype=bool)
        eigvals, eigvecs = np.linalg.eigh(cov)
        order = np.argsort(eigvals)[::-1]
        eigvals = np.clip(eigvals[order], 0.0, None)
        eigvecs = eigvecs[:, order]
        cum = np.cumsum(eigvals) / eigvals.sum()
        k = int(np.searchsorted(cum, self.config.pca_var_explained) + 1)
        self.k_ = max(1, min(k, Xs.shape[1]))
        self.P_k_ = eigvecs[:, : self.k_]
        dq = self._dqi(Xs)
        self.threshold_ = self.config.dqi_x_threshold_factor * float(trim_mean(dq[support], 0.05))
        return self

    def _dqi(self, Xs: np.ndarray) -> np.ndarray:
        a = (Xs - self.center_) @ self.P_k_  # k 維 PCA 特徵（相對 robust 中心）
        return np.sqrt((a**2).sum(axis=1))

    def score(self, X: np.ndarray) -> np.ndarray:
        """回傳每列 DQI_x（越大越離 golden 域）。需先 fit。"""
        Xs = (np.asarray(X, dtype=float) - self.mean_) / self.std_
        return self._dqi(Xs)

    def is_inlier(self, X: np.ndarray) -> np.ndarray:
        """DQI_x ≤ 門檻 為域內（True）。"""
        return self.score(X) <= self.threshold_
