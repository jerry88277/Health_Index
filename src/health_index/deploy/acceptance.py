"""G3 生產驗收報告：部署前回答「這個模型能不能上線？」。

第一性原理（docs/deployment_plan.md §6 G3）：交付流程的「驗收」步驟——使用者選定 golden 建模後，須在
**hold-out golden**（與 fit 用的 golden disjoint、同分布）上確認 golden 誤報率 ≤ 目標，並（若有已知事故段）
確認抓得到、且單變數 SPC 對該事故盲。改造桶6 benchmark 的 DoD 結構為**單模型部署 gate**。

誠實邊界（紅隊 P1 揭露）：hold-out 必須是**時間連續**的代表性 golden 段（非平穩段切分會製造假 FPR，桶5 §3.3）；
自相關資料的窗級變異使 per-sample 標準化偏樂觀（health._severity_health docstring）→ 本報告用**實際窗級
告警率**量測（不靠 per-sample 假設），故能誠實反映 P1 融合在自相關下的真實 golden FPR 與 recall。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..health import HealthIndex
from .bundle import ModelBundle
from .runner import RunnerState, poll_once
from .sources import FrameSource


@dataclass
class AcceptanceReport:
    """單一模型的部署驗收結果（不適用判準回 None）。"""

    product: str
    window: int
    n_golden_holdout: int
    holdout_golden_fpr: float  # hold-out golden 窗告警率（目標 ≤ target_fpr）
    golden_floor: float  # hold-out golden 最低窗 HI（可移植性餘裕）
    drift_recall: float | None  # 已知事故段窗告警率（None=無事故標記）
    spc_exceedance_excess: float | None  # 事故段相對 golden 的單變數越界增量（低=SPC 盲）
    # gates
    fpr_ok: bool
    recall_ok: bool | None
    spc_blind: bool | None

    @property
    def passed(self) -> bool:
        """所有**適用**判準皆通過。"""
        checks = [self.fpr_ok]
        for c in (self.recall_ok, self.spc_blind):
            if c is not None:
                checks.append(c)
        return all(checks)


def _frame_source(X: np.ndarray, x_columns) -> FrameSource:
    import pandas as pd

    return FrameSource(pd.DataFrame(np.asarray(X, dtype=float), columns=list(x_columns)), x_columns)


def acceptance_report(
    bundle: ModelBundle,
    golden_holdout: np.ndarray,
    *,
    target_fpr: float = 0.05,
    window: int | None = None,
    drift: np.ndarray | None = None,
    spc_blind_max: float = 0.15,
    compute_fwer: bool = True,
    persistence_k: int = 1,
) -> AcceptanceReport:
    """對已建模型在 hold-out golden（+選配事故段）評估部署 gate。

    Args:
        bundle: 已建並驗證的模型 bundle。
        golden_holdout: 與 fit 用 golden disjoint 的同分布 golden（時間連續代表性段）。
        target_fpr: golden 窗告警率上限（部署 gate）。
        window: 窗長（None→bundle.config.drift_window）。
        drift: 選配已知事故段（有則評 recall 與 SPC 盲）。
        spc_blind_max: 事故段相對 golden 的單變數越界增量上限（低於＝SPC 盲，隱性）。
        compute_fwer: 是否含 AC-6 FWER（is_alarm∨fwer_alarm，與線上 runner 同口徑）。
        persistence_k: 驗收用單窗即計（=1）以量原始窗 FPR，不被 persistence 遮蔽。

    Returns:
        AcceptanceReport。
    """
    hi = bundle.health
    w = int(window or bundle.config.drift_window)
    cols = bundle.x_columns
    G = np.asarray(golden_holdout, dtype=float)

    gsrc = _frame_source(G, cols)
    gscores, _ = poll_once(bundle, gsrc, RunnerState(), window=w, persistence_k=persistence_k, compute_fwer=compute_fwer)
    if gscores:
        fpr = float(np.mean([s.raw_alarm for s in gscores]))
        floor = float(min(s.health_index for s in gscores))
    else:
        fpr, floor = float("nan"), float("nan")

    recall = spc_excess = None
    recall_ok = spc_blind = None
    if drift is not None:
        D = np.asarray(drift, dtype=float)
        dsrc = _frame_source(D, cols)
        dscores, _ = poll_once(bundle, dsrc, RunnerState(), window=w, persistence_k=persistence_k, compute_fwer=compute_fwer)
        if dscores:
            recall = float(np.mean([s.raw_alarm for s in dscores]))
            recall_ok = recall > 0.5
            # SPC 盲：事故段相對 golden in-sample 底噪的單變數越界增量（高維安全，比照 benchmark 桶3b）
            gmean, gstd = G.mean(axis=0), G.std(axis=0) + 1e-9
            exc = lambda A: float((np.abs(A - gmean) > 3 * gstd).any(axis=1).mean())  # noqa: E731
            spc_excess = exc(D) - exc(G)
            spc_blind = bool(spc_excess < spc_blind_max)

    return AcceptanceReport(
        product=bundle.product,
        window=w,
        n_golden_holdout=int(len(G)),
        holdout_golden_fpr=round(fpr, 4) if np.isfinite(fpr) else fpr,
        golden_floor=round(floor, 4) if np.isfinite(floor) else floor,
        drift_recall=None if recall is None else round(recall, 4),
        spc_exceedance_excess=None if spc_excess is None else round(spc_excess, 4),
        fpr_ok=bool(np.isfinite(fpr) and fpr <= target_fpr),
        recall_ok=recall_ok,
        spc_blind=spc_blind,
    )


def acceptance_from_dataset(
    name: str,
    *,
    holdout_frac: float = 0.5,
    target_fpr: float = 0.05,
    window: int | None = None,
    created_at: str = "acceptance",
    compute_fwer: bool = True,
    **build_kwargs,
) -> AcceptanceReport:
    """便利：用公開資料集做**時間連續 hold-out 驗收**——golden 前段 fit、後段驗 FPR；drift_mask 段評 recall。

    時間連續 split（非隨機）以保自相關結構（block-aware 的前提，紅隊；亦避免桶5 §3.3 非平穩假象）。
    """
    from ..adapters import registry
    from .bundle import build_bundle

    ds, gt = registry.build(name, **build_kwargs)
    cols = list(gt.x_columns)
    fr = ds.frame
    gm = np.asarray(gt.golden_mask)
    gidx = np.flatnonzero(gm)
    cut = gidx[0] + int(holdout_frac * len(gidx))
    fit_idx = gidx[gidx < cut]
    hold_idx = gidx[gidx >= cut]
    Xfit = fr.iloc[fit_idx][cols].to_numpy()
    Xhold = fr.iloc[hold_idx][cols].to_numpy()
    Xdrift = fr.loc[np.asarray(gt.drift_mask), cols].to_numpy() if gt.drift_mask is not None else None
    bundle = build_bundle(name, HealthIndex().fit(Xfit), cols, golden=Xfit, created_at=created_at)
    return acceptance_report(
        bundle, Xhold, target_fpr=target_fpr, window=window, drift=Xdrift, compute_fwer=compute_fwer
    )
