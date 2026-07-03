"""batch-AVM 前處理（advisory，隔離於主 HealthIndex 路徑）：多批 temporal 疊圖 + [param×stat] 指標轉換。

定位（隔離裁決 2026-07-02）：本層為 batch-AVM 新路徑的**純函數**前處理，供新精靈的「疊圖」與「統計特徵
轉換（X*）」及映射模型輸入。主 HealthIndex/score_timeline/window_detail **不得 import 本模組**
（結構不變式，另由隔離測試鎖；本層出錯不可能影響 HI/alarm）。僅依賴 numpy/pandas，無專案骨架耦合。

- ``batches``：以 ``(start, end)`` row span 表示一批（end exclusive），與 ``features.segment_statistics``
  的 segments 契約一致。
- ``trim_frac``：每批**同法**丟頭丟尾比例（保留中間 1−2·frac；連續製程反應時間相近時各批點數近似，
  極值統計偏差可忽略——見 ``docs/batch_avm_design.md`` §4）。
- ``count`` 走**原生格**（真實批長，餵 DQIx，不進 resample）；``cv`` 有 ``|mean|`` floor 防除零；
  ``min/max/range`` 為極值統計（跨批長度不一時偏差，UI/模型層應配 n 一致性閘或改 fixed-p 分位）。
- resample 僅**畫圖層**用（疊圖中位/分位帶）；先算 count 再 resample（設計 §3）。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

_DEFAULT_STATS: tuple[str, ...] = ("mean", "std", "min", "max", "range", "median", "count", "cv")


def _trim_span(s: int, e: int, trim_frac: float) -> tuple[int, int]:
    """回傳批 (s, e) 丟頭丟尾 trim_frac 後的 span；trim_frac=0 時原樣。"""
    cut = int(np.floor((e - s) * trim_frac))
    return s + cut, e - cut


def _stat(values: np.ndarray, stat: str) -> float:
    """單一統計指標（只取 finite 值）。空段回 NaN（不假評，Rule 12）。"""
    v = values[np.isfinite(values)]
    if v.size == 0:
        return float("nan")
    if stat == "mean":
        return float(v.mean())
    if stat == "std":
        return float(v.std())
    if stat == "median":
        return float(np.median(v))
    if stat == "min":
        return float(v.min())
    if stat == "max":
        return float(v.max())
    if stat == "range":
        return float(v.max() - v.min())
    if stat == "count":
        return float(v.size)  # 原生格、長度敏感（餵 DQIx）；不進 resample
    if stat == "cv":
        m = float(v.mean())
        if abs(m) < 1e-9:  # |mean| floor：mean≈0 → NaN 非 inf（設計 §4）
            return float("nan")
        return float(v.std() / abs(m))
    raise ValueError(f"未知統計指標：{stat}")


def batch_indicator_matrix(X, batches, x_columns, *, stats=_DEFAULT_STATS, trim_frac=0.05):
    """每批 [param×stat] → DataFrame（列＝批，欄＝batch/start/end/len + ``{param}__{stat}``）。

    這是 batch-AVM 的 **X***（映射模型輸入）。純函數、確定性、無副作用。

    Args:
        X: (n, p) 製程參數矩陣。
        batches: [(start, end)] row span（end exclusive）。
        x_columns: 參數欄名（長度 = p）。
        stats: 要算的統計指標（預設 6+count+cv）。
        trim_frac: 每批同法丟頭丟尾比例。

    Raises:
        ValueError: 未知統計指標名。
    """
    import pandas as pd

    X = np.asarray(X, dtype=float)
    rows: list[dict] = []
    for bi, (s, e) in enumerate(batches):
        ts, te = _trim_span(int(s), int(e), trim_frac)
        seg = X[ts:te]
        row: dict = {"batch": bi, "start": ts, "end": te, "len": te - ts}
        for j, col in enumerate(x_columns):
            col_vals = seg[:, j] if seg.size else np.empty(0)
            for st in stats:
                row[f"{col}__{st}"] = _stat(col_vals, st)
        rows.append(row)
    return pd.DataFrame(rows)


@dataclass
class OverlayResult:
    """疊圖結果：各批原生 trace + （可選）共同格中位/分位帶。

    Attributes:
        traces: [{batch, t, values}]，t 為 0..1 正規化 index（僅供對齊畫圖）。
        grid: 共同進度格（resample 時）或 None。
        median/band_lo/band_hi: 共同格上的逐點中位與 [band_q, 1−band_q] 分位帶（resample 時）或 None。
    """

    traces: list
    grid: "np.ndarray | None"
    median: "np.ndarray | None"
    band_lo: "np.ndarray | None"
    band_hi: "np.ndarray | None"


def batch_temporal_overlay(X, batches, *, param, trim_frac=0.05, resample_n=None, band_q=0.1):
    """單一參數的多批疊圖：各批 trim 後 trace（原生），可選 resample 到共同進度格算中位/分位帶。

    Args:
        X: (n, p) 製程參數矩陣。
        batches: [(start, end)] row span。
        param: 參數欄 index。
        trim_frac: 每批同法丟頭丟尾比例。
        resample_n: None → 只回各批原生 trace；k → 另回共同格 median + 分位帶（display-only，設計 §3）。
        band_q: 分位帶下側分位（上側為 1−band_q）。

    確定性：無 RNG；同輸入同輸出。
    """
    X = np.asarray(X, dtype=float)
    grid = np.linspace(0.0, 1.0, resample_n) if resample_n else None
    traces: list[dict] = []
    resampled: list[np.ndarray] = []
    for bi, (s, e) in enumerate(batches):
        ts, te = _trim_span(int(s), int(e), trim_frac)
        vals = X[ts:te, param]
        vals = vals[np.isfinite(vals)]
        n = vals.size
        t = np.linspace(0.0, 1.0, n) if n > 1 else np.zeros(n)
        traces.append({"batch": bi, "t": t, "values": vals})
        if resample_n and n >= 2:
            resampled.append(np.interp(grid, t, vals))
    median = band_lo = band_hi = None
    if resample_n and resampled:
        R = np.vstack(resampled)
        median = np.median(R, axis=0)
        band_lo = np.quantile(R, band_q, axis=0)
        band_hi = np.quantile(R, 1.0 - band_q, axis=0)
    return OverlayResult(traces=traces, grid=grid, median=median, band_lo=band_lo, band_hi=band_hi)
