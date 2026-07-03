"""INC-4 批次/機台/時間選取（精靈第 1/2/4 關後端，advisory）。

- `machines_in_interval`：時間區間內有生產資料的機台清單（第 2 關「顯示機台」）。
- `cut_batches`：把（機台×時間區間）的連續資料切成**固定時長 pseudo-batch**（使用者批次生命
  週期：一批＝固定製程時長，如 4h CSTR）；每批 y＝批內實驗室量測**平均**、無則 NaN
  （未量測≠正常，接 `quality.batch_quality_view`）。輸出 (X, spans, y) 直接餵
  `batch_features`/`quality`/`mapping`。
- 無 `machine_id` 欄的舊資料集視為單機台 "M0"（向後相容）。
- 隔離：本模組屬 batch_avm 套件——主告警路徑不得 import（TDD-3 結構測試鎖）。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..interface import MACHINE_ID, TIMESTAMP, Y_VALUE


def _machine_series(frame: pd.DataFrame) -> pd.Series:
    if MACHINE_ID in frame.columns:
        return frame[MACHINE_ID].astype(str)
    return pd.Series("M0", index=frame.index)


def _time_mask(frame: pd.DataFrame, start, end) -> np.ndarray:
    ts = pd.to_datetime(frame[TIMESTAMP])
    mask = np.ones(len(frame), dtype=bool)
    if start is not None:
        mask &= (ts >= pd.Timestamp(start)).to_numpy()
    if end is not None:
        mask &= (ts < pd.Timestamp(end)).to_numpy()
    return mask


def machines_in_interval(frame: pd.DataFrame, *, start=None, end=None) -> list[dict]:
    """時間區間 [start, end) 內有資料的機台清單（依 id 排序）。

    Returns:
        每機台 dict：machine / n_rows / n_y（有限 Y 筆數）/ first / last（ISO 時間字串）。
    """
    mask = _time_mask(frame, start, end)
    sub = frame[mask]
    if sub.empty:
        return []
    mser = _machine_series(sub)
    out = []
    for mid in sorted(mser.unique()):
        rows = sub[(mser == mid).to_numpy()]
        ts = pd.to_datetime(rows[TIMESTAMP])
        out.append({
            "machine": str(mid),
            "n_rows": int(len(rows)),
            "n_y": int(np.isfinite(rows[Y_VALUE].to_numpy(dtype=float)).sum()),
            "first": ts.min().isoformat(),
            "last": ts.max().isoformat(),
        })
    return out


def cut_batches(
    frame: pd.DataFrame,
    x_columns,
    *,
    machine: str | None = None,
    start=None,
    end=None,
    batch_minutes: int = 240,
    min_frac: float = 0.5,
) -> dict:
    """把（機台×時間區間）切成固定時長 pseudo-batch，輸出可直接餵 batch-AVM 管線的 (X, spans, y)。

    Args:
        frame: 統一契約長表（含 TIMESTAMP；可含 MACHINE_ID）。
        x_columns: X 參數欄名。
        machine: 機台 id；frame 為多機台時**必須**指定（fail loud）；單機台可省略。
        start, end: 時間區間 [start, end)；None＝不限。
        batch_minutes: 每批固定時長（分鐘）；使用者情境一批＝4h → 240。
        min_frac: 尾批列數 < min_frac×中位批列數 → 丟棄（不完整批不進統計）。

    Returns:
        dict：machine / X（(n,p) 依時間排序）/ spans（[(s,e)] into X）/ y（(n_batches,) 批內
        有限 Y 平均、無則 NaN）/ batch_start_times（ISO）/ frame_positions（X 每列對應原 frame
        位置，供下鑽溯源）/ n_dropped_partial。

    Raises:
        ValueError: batch_minutes<=0、start>=end、多機台未指定 machine、machine 不存在、區間無資料。
    """
    if batch_minutes <= 0:
        raise ValueError("batch_minutes 須 > 0")
    if start is not None and end is not None and pd.Timestamp(start) >= pd.Timestamp(end):
        raise ValueError("start 須早於 end")
    mser = _machine_series(frame)
    avail = sorted(mser.unique())
    if machine is None:
        if len(avail) > 1:
            raise ValueError(f"多機台 frame 須指定 machine（可用：{avail}）")
        machine = avail[0]
    if machine not in avail:
        raise ValueError(f"machine '{machine}' 不存在（可用：{avail}）")
    mask = _time_mask(frame, start, end) & (mser == machine).to_numpy()
    if not mask.any():
        raise ValueError(f"machine '{machine}' 於選取區間無資料")

    pos = np.flatnonzero(mask)
    ts = pd.to_datetime(frame[TIMESTAMP]).iloc[pos]
    order = np.argsort(ts.to_numpy(), kind="stable")  # 依時間穩定排序（確定性）
    pos = pos[order]
    ts = ts.iloc[order]

    t0 = ts.iloc[0]
    bucket = ((ts - t0).dt.total_seconds() // (batch_minutes * 60)).astype(int).to_numpy()
    # 連續同 bucket → span（bucket 隨時間非遞減）
    cut_pts = np.flatnonzero(np.diff(bucket) != 0) + 1
    edges = np.concatenate(([0], cut_pts, [len(bucket)]))
    spans_all = [(int(edges[i]), int(edges[i + 1])) for i in range(len(edges) - 1)]
    sizes = np.array([e - s for s, e in spans_all], dtype=float)
    med = float(np.median(sizes))
    keep = [sp for sp, sz in zip(spans_all, sizes) if sz >= min_frac * med]
    n_dropped = len(spans_all) - len(keep)

    X = frame[list(x_columns)].to_numpy(dtype=float)[pos]
    y_rows = frame[Y_VALUE].to_numpy(dtype=float)[pos]
    y_batch = []
    for s, e in keep:
        vals = y_rows[s:e]
        vals = vals[np.isfinite(vals)]
        y_batch.append(float(vals.mean()) if vals.size else float("nan"))  # 多筆實驗室量測取平均
    return {
        "machine": str(machine),
        "X": X,
        "spans": keep,
        "y": np.asarray(y_batch, dtype=float),
        "batch_start_times": [ts.iloc[s].isoformat() for s, _ in keep],
        "frame_positions": pos,
        "n_dropped_partial": int(n_dropped),
    }
