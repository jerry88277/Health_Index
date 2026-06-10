"""跨資料集 DoD benchmark harness（桶6，泛化的「證明」層）。

第一性原理：泛化只有在「**同一條判斷鏈經統一協定（桶1 GroundTruth）跑通結構不同的多個資料集，且
通過相同 DoD**」時才算被證明。本模組消費 ``adapters.registry`` 建出的任一資料集 + 共用 ``GroundTruth``，
對每個資料集評估 CLAUDE.md 三條 DoD：

1. **golden 健康**：golden 段 Health Index 高（基準不誤報）。
2. **隱性飄移被抓且早於單變數 SPC**：drift 段被融合 HI 或 AC-6 fwer 抓到，而**單變數 3σ 近乎盲**
   （越界率低）——這正是本 index 存在的理由。
3. **區分乾淨回歸 vs 殘留飄移**：clean re-entry 健康（不誤報）、drift re-entry 被旗標。

誠實標（Rule 12）：無 drift 真值的資料集（如真實老化集 uci，``drift_mask=None``）只評 golden 健康，
飄移/clean 判準回 ``None``（不適用，不假裝）。
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass

import numpy as np

from ..adapters import registry
from ..adapters.base import GroundTruth, Segment
from ..health import HealthIndex


@dataclass(frozen=True)
class DatasetDoD:
    """單一資料集的 DoD 評估（不適用判準回 None）。"""

    dataset: str
    golden_health: float
    clean_health: float | None
    drift_health: float | None
    drift_fwer_alarm: bool | None
    clean_fwer_alarm: bool | None
    spc_exceedance_drift: float | None
    # DoD 判準
    golden_healthy: bool
    drift_caught: bool | None
    spc_blind_on_drift: bool | None
    clean_not_flagged: bool | None

    @property
    def passed(self) -> bool:
        """所有**適用**判準皆通過（None 判準不計）。"""
        checks = [self.golden_healthy]
        for c in (self.drift_caught, self.spc_blind_on_drift, self.clean_not_flagged):
            if c is not None:
                checks.append(c)
        return all(checks)


def _segment_roles(gt: GroundTruth) -> tuple[Segment, Segment | None, Segment | None]:
    """從 GroundTruth 推出 (golden, clean, drift) 角色段。

    - golden：被 golden_mask **完整覆蓋** 的段。
    - drift：與 drift_mask 有交集的段（drift_mask=None → None）。
    - clean：與 golden **同標籤**、且非 golden/非 drift 的段（如換產品後乾淨回歸的同 grade）。

    Raises:
        ValueError: 找不到 golden 段（golden_mask 非單段覆蓋；fail loud）。
    """
    gm = np.asarray(gt.golden_mask)
    golden = next((s for s in gt.segments if gm[s.start : s.end].all()), None)
    if golden is None:
        raise ValueError(f"找不到被 golden_mask 完整覆蓋的段（{gt.x_columns[:1]}...）")
    drift = None
    if gt.drift_mask is not None:
        dm = np.asarray(gt.drift_mask)
        drift = next((s for s in gt.segments if dm[s.start : s.end].any()), None)
    if drift is not None and drift is golden:  # drift_mask 與 golden 段交集 → 角色衝突，fail loud（紅隊 A-D1）
        raise ValueError("drift_mask 與 golden 段重疊：角色不互斥，無法評 DoD（檢查真值標記）")
    clean = next(
        (s for s in gt.segments if s is not golden and s is not drift and s.label == golden.label),
        None,
    )
    return golden, clean, drift


def evaluate_dataset(
    name: str,
    *,
    golden_health_min: float = 0.8,
    spc_blind_max: float = 0.15,
    drift_margin: float = 0.15,
    **build_kwargs,
) -> DatasetDoD:
    """對單一已註冊資料集評估 DoD（經 registry + 統一 GroundTruth）。

    Args:
        name: registry 資料集名。
        golden_health_min: golden/clean 視為健康的 HI 下限。
        spc_blind_max: 單變數 3σ 越界率上限（低於＝SPC 盲，index 有價值）。
        drift_margin: drift HI 須低於 golden 此幅度（或 fwer 告警）才算被抓。
        **build_kwargs: 傳給 registry.build（如 seed/drift_strength）。

    Returns:
        DatasetDoD。
    """
    ds, gt = registry.build(name, **build_kwargs)
    cols = list(gt.x_columns)
    fr = ds.frame
    golden_seg, clean_seg, drift_seg = _segment_roles(gt)
    Xg = fr.loc[np.asarray(gt.golden_mask), cols].to_numpy()
    hi = HealthIndex().fit(Xg)

    def seg_x(s: Segment) -> np.ndarray:
        return fr.iloc[s.start : s.end][cols].to_numpy()

    gh = float(hi.health_index(Xg))  # 在 fit 同列上評 golden HI（與 fit set 一致；紅隊 B-D1，消潛在分歧）
    ch = float(hi.health_index(seg_x(clean_seg))) if clean_seg else None
    cfw = bool(hi.fwer_alarm(seg_x(clean_seg))) if clean_seg else None

    dh = dfw = spc = None
    drift_caught = spc_blind = None
    if drift_seg is not None:
        Xd = seg_x(drift_seg)
        dh = float(hi.health_index(Xd))
        dfw = bool(hi.fwer_alarm(Xd))
        gmean, gstd = Xg.mean(axis=0), Xg.std(axis=0) + 1e-9
        spc = float((np.abs(Xd - gmean) > 3 * gstd).any(axis=1).mean())
        # 融合 HI **或** AC-6 任一抓到（OR 雙軌）。誠實標（紅隊 A-D4）：tep_tp 保時序情境下，融合 HI
        # 受權重稀釋幾乎不動（drop≈0.13<margin），drift_caught **僅靠 fwer leg**——融合層對該情境惰性、
        # 由 AC-6/L2 偵測扛起，這是 OR 設計的用意（粗融合漏的由校準偵測器補）。
        drift_caught = bool(dfw or dh < gh - drift_margin)
        spc_blind = bool(spc < spc_blind_max)

    return DatasetDoD(
        dataset=name,
        golden_health=round(gh, 4),
        clean_health=None if ch is None else round(ch, 4),
        drift_health=None if dh is None else round(dh, 4),
        drift_fwer_alarm=dfw,
        clean_fwer_alarm=cfw,
        spc_exceedance_drift=None if spc is None else round(spc, 4),
        golden_healthy=bool(gh > golden_health_min),
        drift_caught=drift_caught,
        spc_blind_on_drift=spc_blind,
        clean_not_flagged=None if clean_seg is None else bool(ch > golden_health_min and not cfw),
    )


_DEFAULT_SPECS: tuple[tuple[str, dict], ...] = (
    ("synthetic", {"seed": 5, "drift_strength": 1.2}),
    ("tep", {"seed": 0, "drift_strength": 1.0}),
    ("tep_tp", {"seed": 0, "drift_strength": 0.7}),
)


def run_benchmark(specs: tuple = _DEFAULT_SPECS) -> list[DatasetDoD]:
    """對多個資料集跑 DoD benchmark；資料缺（FileNotFoundError）的資料集自動略過（誠實標 log 由呼叫端）。

    Args:
        specs: (name, build_kwargs) 序列。

    Returns:
        各資料集的 DatasetDoD（可建者）。
    """
    out: list[DatasetDoD] = []
    for name, kw in specs:
        try:
            out.append(evaluate_dataset(name, **kw))
        except FileNotFoundError:
            warnings.warn(  # 紅隊 A-D2：略過須出聲，否則「全過」會遮蔽涵蓋率縮水（資料缺非全過）
                f"benchmark: 略過資料集 '{name}'（資料未下載）；本次涵蓋率不含此集。",
                RuntimeWarning,
                stacklevel=2,
            )
    return out
