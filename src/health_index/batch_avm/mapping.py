"""INC-3 batch-AVM 映射模型 + X* MSPC（精靈第 7/9 關計算核心，advisory）。

- **映射**：`make_soft_sensor` 依規模路由（X* 高維共線 → PLS 主力；小 p → GPR），零新模型
  （模型分析裁決）。可信帶＝ **CV+/jackknife+**（批次尺度 n << cp_min_calibration=200，split-CP
  必不可用）；覆蓋誠實 worst-case ≥1−2α（`coverage_floor`）。
- **X* MSPC**：**fresh** `MSPCModel`（不 route 過 live L2 物件）＋ **highdim PCA-score 預投影**
  （整合紅隊 must-fix #7：naive cov 在 n<p 奇異、λ floor 出垃圾限）。降維與否/維度/變異匱乏
  以 `reduced_/r_/degraded_` 誠實 surface（比照 `DQIxGate._fit_reduction`）。
- **RBC 歸因**：僅未降維時提供（降維 score 空間無法命名 [param×stat]；指錯參數比不指更糟
  ——風險稽核 G2/G3 歸因裁決），降維時誠實回 None。
- 隔離：本模組屬 batch_avm 套件——主告警路徑不得 import（TDD-3 結構測試鎖）。
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field

import numpy as np

from ..config import DEFAULT, Config
from ..detectors.conformal_cv import CVPlusConformal
from ..detectors.highdim import effective_rank, reduction_plan
from ..detectors.mspc import MSPCModel
from ..detectors.soft_sensor import make_soft_sensor
from .homogeneity import golden_homogeneity_gate


@dataclass
class BatchAvmModel:
    """batch-AVM 已 fit 模型組（映射 + CV+ 可信帶 + X* MSPC）。以 `fit_batch_model` 建構。"""

    config: Config = field(default=DEFAULT)
    columns_: tuple = ()          # fit 時的全部欄名
    kept_idx_: tuple = ()         # 保留欄 index（非有限欄剔除後）
    dropped_columns: list = field(default_factory=list)
    mapping_kind: str = "gpr"     # 'pls' | 'gpr'
    reduced_: bool = False        # X* MSPC 是否啟動 PCA-score 預投影
    r_: int = 0
    degraded_: bool = False
    n_golden_: int = 0
    # fitted objects（fit_batch_model 填入）
    ss_: object = None            # 點預測 soft sensor（全資料）
    cv_: object = None            # CVPlusConformal（可信帶）
    mspc_: object = None          # fresh MSPCModel（X* 域監控）
    red_mean_: object = None      # 預投影用標準化（僅 reduced_ 時）
    red_std_: object = None
    reduce_V_: object = None      # (p_kept, r) 投影矩陣；None＝未降維
    homogeneity_: object = None   # 池化 Golden 同質性閘結果（fit 給 cells 時；設計 §8，WARN-only）

    def _kept(self, Xstar: np.ndarray) -> np.ndarray:
        X = np.asarray(Xstar, dtype=float)
        return X[:, list(self.kept_idx_)]

    def _mspc_space(self, Xk: np.ndarray) -> np.ndarray:
        """映到 MSPC fit 時所用空間：未降維＝原 X* 保留欄；降維＝標準化後投影 score。"""
        if self.reduce_V_ is None:
            return Xk
        return ((Xk - self.red_mean_) / self.red_std_) @ self.reduce_V_


def fit_batch_model(Xstar, y, *, columns=None, cells=None, config: Config = DEFAULT) -> BatchAvmModel:
    """以 golden 批的 (X*, y) 建映射模型 + CV+ 可信帶 + fresh X* MSPC（全部凍結）。

    Args:
        Xstar: (n_batches, p) 每批 [param×stat] 特徵（`batch_indicator_matrix` 數值欄）。
        y: (n_batches,) 每批量測（未量測 NaN；映射/CV+ 只用有限列）。
        columns: 欄名（RBC 歸因命名用）；None → f0..f{p-1}。
        cells: (n_batches,) 每批的 cell 標籤（如 machine_id）——給了就於 **build 時**跑池化
            同質性閘（設計 §8，WARN-only，結果存 ``homogeneity_`` 並進 score summary）；
            None＝不評（誠實 None，不偽造）。
        config: 全域超參。

    Raises:
        ValueError: 有效 (X*, y) 觀測 < 2，或剔除非有限欄後無可用欄。
    """
    X = np.asarray(Xstar, dtype=float)
    y = np.asarray(y, dtype=float)
    n, p = X.shape
    cols = tuple(columns) if columns is not None else tuple(f"f{i}" for i in range(p))
    finite_col = np.isfinite(X).all(axis=0)
    kept_idx = tuple(int(i) for i in np.where(finite_col)[0])
    dropped = [cols[i] for i in range(p) if not finite_col[i]]
    if not kept_idx:
        raise ValueError("X* 剔除非有限欄後無可用欄")
    Xk = X[:, list(kept_idx)]
    pk = Xk.shape[1]

    # 映射（點預測）＋ CV+ 可信帶（批次尺度小 n 唯一路徑；工廠每折 fresh 實例）
    ss = make_soft_sensor(config, n_samples=n, n_features=pk).fit(Xk, y)
    cv = CVPlusConformal(config).fit(
        lambda: make_soft_sensor(config, n_samples=n, n_features=pk), Xk, y
    )

    # X* MSPC：highdim 預投影決策（比照 DQIxGate._fit_reduction；SVD 恆良定義）
    mean = Xk.mean(axis=0)
    std = Xk.std(axis=0) + 1e-9
    Xs = (Xk - mean) / std
    _, sv, vt = np.linalg.svd(Xs, full_matrices=False)
    ev = sv**2
    rank = effective_rank(ev, rtol=config.hd_rank_rtol)
    cum = np.cumsum(ev) / (ev.sum() + 1e-300)
    var_components = int(np.searchsorted(cum, config.pca_var_explained) + 1)
    need_reduce, r, degraded = reduction_plan(
        n, pk,
        rank=rank,
        var_components=var_components,
        min_n_over_p=config.hd_min_n_over_p,
        max_frac=config.hd_reduce_max_frac,
    )
    if degraded:
        warnings.warn(
            f"batch-AVM X* 高維變異匱乏（degraded）：golden 批數 n={n} 僅容降維至 r={r}，"
            f"達 pca_var_explained={config.pca_var_explained} 需 {var_components} 成分——"
            f"X* MSPC 可信度下降，請增加 golden 批數（Rule 12 誠實 surface）。",
            RuntimeWarning,
            stacklevel=2,
        )
    V = vt[:r].T if need_reduce else None
    Z = Xs @ V if need_reduce else Xk
    mspc = MSPCModel(config).fit(Z)

    m = BatchAvmModel(
        config=config,
        columns_=cols,
        kept_idx_=kept_idx,
        dropped_columns=dropped,
        mapping_kind=getattr(ss, "method", "gpr"),
        reduced_=bool(need_reduce),
        r_=int(r),
        degraded_=bool(degraded),
        n_golden_=n,
    )
    m.ss_ = ss
    m.cv_ = cv
    m.mspc_ = mspc
    m.red_mean_ = mean if need_reduce else None
    m.red_std_ = std if need_reduce else None
    m.reduce_V_ = V
    if cells is not None:
        kept_cols = [cols[i] for i in kept_idx]
        m.homogeneity_ = golden_homogeneity_gate(Xk, cells, columns=kept_cols, config=config)
    return m


def score_batches(model: BatchAvmModel, Xstar) -> dict:
    """對每批 X* 算 Ŷ + CV+ 可信帶 + T²/SPE/GSI + 域旗標 +（未降維時）RBC top 歸因。

    Returns:
        dict：batches（yhat/band_lo/band_hi/t2/spe/gsi/t2_over/spe_over/anomaly/yhat_reliable/
        rbc_top）、summary（t2_lim/spe_lim/band_kind/coverage_floor/cv_available/mapping_kind/
        reduced/r/degraded/dropped_columns/n_golden）、is_advisory=True。
        `yhat_reliable`＝X* 域內（T²/SPE 未超限）——G3 適用域的 T²/SPE 代理（正式 AD 為後續項）。
    """
    Xk = model._kept(Xstar)
    Z = model._mspc_space(Xk)
    t2 = model.mspc_.t2(Z)
    spe = model.mspc_.spe(Z)
    gsi = model.mspc_.gsi(Z)
    t2_over = t2 > model.mspc_.t2_lim_
    spe_over = spe > model.mspc_.spe_lim_
    anomaly = t2_over | spe_over
    yhat = np.asarray(model.ss_.predict(Xk), dtype=float).ravel()
    if model.cv_.available:
        lo, hi = model.cv_.predict_interval(Xk)
    else:
        lo = hi = None
    rbc_all = model.mspc_.rbc_spe(Xk) if model.reduce_V_ is None else None
    kept_cols = [model.columns_[i] for i in model.kept_idx_]

    batches = []
    for i in range(len(Xk)):
        rbc_top = None
        if rbc_all is not None and bool(anomaly[i]):
            rbc_top = kept_cols[int(np.argmax(rbc_all[i]))]
        batches.append({
            "yhat": float(yhat[i]),
            "band_lo": float(lo[i]) if lo is not None else None,
            "band_hi": float(hi[i]) if hi is not None else None,
            "t2": float(t2[i]),
            "spe": float(spe[i]),
            "gsi": float(gsi[i]),
            "t2_over": bool(t2_over[i]),
            "spe_over": bool(spe_over[i]),
            "anomaly": bool(anomaly[i]),
            "yhat_reliable": bool(not anomaly[i]),
            "rbc_top": rbc_top,
        })
    summary = {
        "t2_lim": float(model.mspc_.t2_lim_),
        "spe_lim": float(model.mspc_.spe_lim_),
        "band_kind": model.cv_.band_kind if model.cv_.available else None,
        "coverage_floor": float(model.cv_.coverage_floor) if model.cv_.available else None,
        "cv_available": bool(model.cv_.available),
        "mapping_kind": model.mapping_kind,
        "reduced": bool(model.reduced_),
        "r": int(model.r_),
        "degraded": bool(model.degraded_),
        "dropped_columns": list(model.dropped_columns),
        "n_golden": int(model.n_golden_),
        "homogeneity": model.homogeneity_,  # 池化同質性閘（None＝fit 未給 cells，不評不偽造）
    }
    return {"batches": batches, "summary": summary, "is_advisory": True}
