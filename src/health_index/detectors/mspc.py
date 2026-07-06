"""L2 多變量統計製程管制（MSPC）：PCA → T² / SPE / GSI + 控制限 + RBC 肇因。

依 ``docs/avm_metrics_definitions.md`` 與 ``redteam_reconciliation.md``：
- **T²**（Hotelling）：保留 k 主成分子空間內變異 = Σ t_i²/λ_i。
- **SPE / Q**：殘差子空間 ‖x − x̂‖² —— **隱性多變量飄移的主訊號**（每變數在規格內、僅相關
  結構偏移時，偏移落在殘差空間 → SPE 升高，而單變數 SPC 抓不到）。這正是本 index 存在的理由。
- **GSI**（AVM）= D²/p = 全空間 Mahalanobis / p（avm_metrics §1，US8095484B2 版）。**注意**：全空間
  含近零特徵值方向 → 數值不穩（紅隊：T²+SPE 為其穩健替身）；此處對 λ 加 floor 規避除爆，並
  以 T²/SPE 為主、GSI 為 AVM 相容對照。
- **RBC**（Reconstruction-Based Contribution, Alcala & Qin 2009, Automatica 45(7):1593-1600）取代
  原始 contribution，消單故障 smearing：RBC_j^SPE = e_j² / C̃_jj（C̃=I−P_kP_kᵀ 殘差投影）。
  紅隊 H3：多方向漂移時 RBC 仍殘留 smearing，故 RBC 為「定位非因果」。
- **控制限**：以 golden-A 的 **經驗 (1−α) 分位**（非參數，規避 F/χ² 高斯假設，紅隊 N4 部分）；
  真實強自相關資料須改 block-bootstrap（synthetic 為 iid，MVP 採經驗分位，Rule 2）。
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field

import numpy as np

from ..config import DEFAULT, Config

_RBC_MIN_DIAG = 1e-8   # Ctilde_jj 低於此＝變數幾乎全在模型子空間、無殘差容量→RBC 無定義；設 0 不排 argsort 首位
_COND_WARN = 1e10      # golden 協方差條件數超此→病態警告（誠實 surface，非靜默）


@dataclass
class MSPCModel:
    """在 golden-A 上 fit（PCA + 控制限）並凍結，對新樣本算 T²/SPE/GSI 與 RBC 肇因。"""

    config: Config = field(default=DEFAULT)

    def fit(self, X_golden: np.ndarray) -> "MSPCModel":
        """以 golden-A 建立標準化、PCA、殘差投影與 T²/SPE 經驗控制限（凍結）。"""
        X = np.asarray(X_golden, dtype=float)
        self.mean_ = X.mean(axis=0)
        self.std_ = X.std(axis=0) + 1e-9
        Xs = (X - self.mean_) / self.std_
        p = Xs.shape[1]
        cov = np.cov(Xs, rowvar=False)
        eigvals, eigvecs = np.linalg.eigh(cov)
        order = np.argsort(eigvals)[::-1]
        self.eigvals_ = np.clip(eigvals[order], 1e-12, None)
        self.P_ = eigvecs[:, order]
        self.cond_ = float(self.eigvals_[0] / self.eigvals_[-1])  # 條件數（eigvals 已 floor 1e-12）
        if self.cond_ > _COND_WARN:
            warnings.warn(
                f"MSPC golden 病態（條件數={self.cond_:.2e}）：協方差近奇異/秩虧，T²/SPE 控制限與 RBC "
                f"可信度下降，建議增樣本或降維（Rule 12 誠實 surface）。",
                RuntimeWarning, stacklevel=2,
            )
        cum = np.cumsum(self.eigvals_) / self.eigvals_.sum()
        k = int(np.searchsorted(cum, self.config.pca_var_explained) + 1)
        self.k_ = max(1, min(k, p))
        self.P_k_ = self.P_[:, : self.k_]
        self.lam_k_ = self.eigvals_[: self.k_]
        self.Ctilde_ = np.eye(p) - self.P_k_ @ self.P_k_.T  # 殘差投影
        q = 1.0 - self.config.mspc_alpha
        self.t2_lim_ = float(np.quantile(self.t2(X), q))
        self.spe_lim_ = float(np.quantile(self.spe(X), q))
        return self

    def _std(self, X: np.ndarray) -> np.ndarray:
        X = np.asarray(X, dtype=float)
        if not np.isfinite(X).all():  # 非有限輸入→fail loud（不靜默把 nan 當健康；上游應先過 L1 sanity_check）
            raise ValueError("MSPC 輸入含非有限值（NaN/Inf）——上游應先過 L1 資料效度閘（Rule 12 fail loud）")
        return (X - self.mean_) / self.std_

    def t2(self, X: np.ndarray) -> np.ndarray:
        """Hotelling T²（保留子空間內 Mahalanobis）。"""
        t = self._std(X) @ self.P_k_
        return ((t**2) / self.lam_k_).sum(axis=1)

    def spe(self, X: np.ndarray) -> np.ndarray:
        """SPE/Q（殘差空間平方距離）。"""
        resid = self._std(X) @ self.Ctilde_
        return (resid**2).sum(axis=1)

    def gsi(self, X: np.ndarray) -> np.ndarray:
        """GSI = D²/p（全空間 Mahalanobis/p；對 λ 加 floor 規避不穩）。"""
        t = self._std(X) @ self.P_
        p = self.P_.shape[1]
        return ((t**2) / self.eigvals_).sum(axis=1) / p

    def rbc_spe(self, X: np.ndarray) -> np.ndarray:
        """逐變數 SPE 的 RBC（reconstruction-based contribution），消單故障 smearing。

        Returns: (n, p) 每樣本每變數的 RBC_j = e_j² / C̃_jj。
        """
        resid = self._std(X) @ self.Ctilde_
        diag = np.diag(self.Ctilde_)
        degenerate = diag < _RBC_MIN_DIAG  # 無殘差容量欄：Ctilde_jj→0 ⟺ 整列→0 ⟺ resid_j→0（本就≈0）
        safe = np.where(degenerate, 1.0, diag)
        with np.errstate(divide="raise", invalid="raise"):  # 數值退化→loud，不靜默傳 inf/nan
            rbc = (resid**2) / safe
        if degenerate.any():
            rbc[:, degenerate] = 0.0  # 顯式歸零：退化欄不歸因（避免 1e-12 分母把數值雜訊放大成 garbage-first）
        return rbc

    def is_anomaly(self, X: np.ndarray) -> np.ndarray:
        """T² 或 SPE 超出控制限即判異常。"""
        return (self.t2(X) > self.t2_lim_) | (self.spe(X) > self.spe_lim_)
