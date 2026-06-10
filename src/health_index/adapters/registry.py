"""Adapter registry（桶1）：``name → builder``，統一 ``build(name, **kw) -> (ProcessDataset, GroundTruth)``。

把既有 adapter（各自 ``generate``/``load`` 入口 + bespoke ``*GroundTruth``）以**轉換器**包裝為統一
builder，向後相容（既有入口完全不動，方案 A）。新資料集可用 ``register(name, builder)`` 自助掛入，
或直接用 ``dataframe.from_frame``（已回傳共用 GroundTruth）。
"""

from __future__ import annotations

from ..interface import ProcessDataset
from . import synthetic, tep, uci_gas_drift
from .base import DatasetBuilder, GroundTruth, Segment


def _campaign_segments(bounds: tuple) -> tuple[Segment, ...]:
    """synthetic/tep 的 ``(start, end, grade)`` → Segment（id 依順序）。

    紅隊 A#3：由呼叫端**明示**形狀，不再以 ``isinstance(b[2], str)`` 嗅探型別（整數 grade 會誤判）。
    """
    return tuple(Segment(id=i, start=int(s), end=int(e), label=str(g)) for i, (s, e, g) in enumerate(bounds))


def _batch_segments(bounds: tuple) -> tuple[Segment, ...]:
    """uci_gas_drift 的 ``(batch_id, start, end)`` → Segment（label=batchN）。"""
    return tuple(Segment(id=int(bid), start=int(s), end=int(e), label=f"batch{int(bid)}") for bid, s, e in bounds)


def _wrap_campaign_like(ds: ProcessDataset, gt) -> tuple[ProcessDataset, GroundTruth]:
    """包裝 synthetic/tep 型真值（campaign_bounds + drift_mask）為共用 GroundTruth。"""
    return ds, GroundTruth(
        x_columns=gt.x_columns,
        golden_mask=gt.golden_mask,
        segments=_campaign_segments(gt.campaign_bounds),
        drift_mask=gt.drift_mask,
    )


def _build_synthetic(**kw) -> tuple[ProcessDataset, GroundTruth]:
    return _wrap_campaign_like(*synthetic.generate(**kw))


def _build_tep(**kw) -> tuple[ProcessDataset, GroundTruth]:
    return _wrap_campaign_like(*tep.generate(**kw))


def _build_tep_tp(**kw) -> tuple[ProcessDataset, GroundTruth]:
    # tep_tp 即保時序（②）：硬釘 time_preserving=True；明示傳 False＝語意矛盾，fail loud（紅隊 A#1）。
    if kw.get("time_preserving") is False:
        raise ValueError("'tep_tp' 即保時序模式，不可 time_preserving=False；要 iid 重抽請改用 'tep'")
    kw["time_preserving"] = True
    return _wrap_campaign_like(*tep.generate(**kw))


def _build_uci_gas_drift(**kw) -> tuple[ProcessDataset, GroundTruth]:
    ds, gt = uci_gas_drift.load(**kw)
    return ds, GroundTruth(
        x_columns=gt.x_columns,
        golden_mask=gt.golden_mask,
        segments=_batch_segments(gt.batch_bounds),
        drift_mask=None,  # 真實感測器老化集：漂移為時間性、無逐列 ground-truth（誠實標 None）
    )


_BUILDERS: dict[str, DatasetBuilder] = {
    "synthetic": _build_synthetic,
    "tep": _build_tep,
    "tep_tp": _build_tep_tp,
    "uci_gas_drift": _build_uci_gas_drift,
}


def register(name: str, builder: DatasetBuilder, *, overwrite: bool = False) -> None:
    """掛入新資料集 builder（``build(**kw) -> (ProcessDataset, GroundTruth)``）。

    Raises:
        ValueError: name 已存在且未指定 overwrite（避免靜默覆蓋既有資料集）。
    """
    if name in _BUILDERS and not overwrite:
        raise ValueError(f"資料集 '{name}' 已註冊；overwrite=True 才覆蓋")
    _BUILDERS[name] = builder


def available() -> list[str]:
    """已註冊資料集名稱（排序）。"""
    return sorted(_BUILDERS)


def build(name: str, **kwargs) -> tuple[ProcessDataset, GroundTruth]:
    """以統一入口建構任一已註冊資料集。

    Raises:
        KeyError: 未知資料集（附可用清單）。
    """
    if name not in _BUILDERS:
        raise KeyError(f"未知資料集 '{name}'；可用: {available()}")
    return _BUILDERS[name](**kwargs)
