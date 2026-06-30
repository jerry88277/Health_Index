"""特徵建構層（混合疊加）：連續製程穩態段定義 + [參數×統計] 聚合 + block-bootstrap 偏離視圖。

定位（v2 設計，經 3 視角獨立紅隊）：**本層不是偵測器**，是「穩態段定義 + 可解釋/品質溝通視圖」。
隱性飄移主訊號仍是 L2 SPE——逐參數段統計**丟棄跨變數相關**，對本專案核心的「保邊際、破相關」型
covert drift 天生鈍（見 ``test_features`` 硬閘測試）。主路徑 ``HealthIndex`` 逐位元不動；本層為純
function，由獨立 demo endpoint 呼叫，**主路徑函式不得 import 本模組**（結構性不變式：本層出錯不可能
影響 HI/alarm）。

段定義（兩模式；wavelet 延後增量，dep 已備）：
- ``trim``：段內丟頭丟尾、中間為 1 段（零調參確定性，預設）。
- ``ssd``：復用 ``detect_change_points``(PELT) + ``seg_ramp``/``seg_std`` 已校準準則
  （紅隊 B5：不另造未校準門檻，沿用 golden 自動挑選同一準則）。

偏離視圖（紅隊 B1 修正）：每個 [param×stat] 以 golden **window-vs-window block-bootstrap** 建 null
（連續窗→吸收自相關；非「跨 golden 段 std」——golden 僅第一個 A campaign，trim 下只有 1 段、分母未
定義）→ 標準化 z + golden-null 雙尾 p-value → **Holm 校正**跨 [param×stat]×段 網格。退化守衛：凍結
感測器（null std≈0）/ golden 不足窗長 / query 段過短 → NaN+warn（Rule 12 不假評）。每筆標
``is_advisory=True``（結構護欄：非偵測告警）。
"""

from __future__ import annotations

import warnings
from typing import Sequence

import numpy as np
import pandas as pd

from ..config import DEFAULT, Config
from .segment import detect_change_points, seg_ramp, seg_std

# [param×stat] 網格用的逐參數統計量（6）。count/seg_len 為**段級** metadata（跨參數重複、無 per-param
# 訊號）→ 不入網格、不入偏離排序（紅隊）。mode（眾數）連續浮點退化，本切片不提供（啟用須 golden 釘死共用 bin）。
_STAT_FUNCS = {
    "mean": lambda a: float(np.mean(a)),
    "std": lambda a: float(np.std(a)),
    "min": lambda a: float(np.min(a)),
    "max": lambda a: float(np.max(a)),
    "range": lambda a: float(np.max(a) - np.min(a)),
    "median": lambda a: float(np.median(a)),
}

_META_COLS = ("seg_index", "seg_start", "seg_end", "seg_len")


def detect_steady_segments(
    X: np.ndarray, *, method: str = "trim", config: Config = DEFAULT
) -> list[tuple[int, int]]:
    """把單一模式/campaign 的連續 X 切成穩態 pseudo-run ``[start, end)``（局部索引）。

    呼叫端須先用 ``preprocess.segment`` 的 CAMPAIGN_ID/GRADE_LABEL 把資料切到**單一模式**再傳入
    （跨 grade pool 製造假飄移，CSTR 研究強制）。回傳段為相對 X 的局部索引，呼叫端自行映回全域。

    Args:
        X: (n, p) 單一模式的製程參數。
        method: ``"trim"``（丟頭尾取中間，零調參確定性）| ``"ssd"``（PELT 變點 + seg_ramp/seg_std 穩態準則）。
        config: 提供 seg_trim_head/tail、seg_min_len，及 ssd 復用的 cpd/ramp 門檻。

    Returns:
        穩態段 ``[(s, e), ...]``（已濾掉 < ``seg_min_len`` 者）；過短/無乾淨段回 ``[]``。

    Raises:
        ValueError: method 非 trim/ssd（wavelet 延後增量）。
    """
    X = np.asarray(X, dtype=float)
    n = len(X)
    if method == "trim":
        s = int(config.seg_trim_head)
        e = int(n - config.seg_trim_tail)
        return [(s, e)] if e - s >= config.seg_min_len else []
    if method == "ssd":
        if n < config.seg_min_len:
            return []
        Xs = (X - X.mean(axis=0)) / (X.std(axis=0) + 1e-9)  # 標準化空間（對齊 seg_ramp/seg_std 準則）
        bkps = detect_change_points(X, config=config)
        bounds = [0, *bkps, n]
        segs = [(a, b) for a, b in zip(bounds[:-1], bounds[1:]) if b - a >= config.seg_min_len]
        # 復用 golden 自動挑選同一已校準準則（紅隊 B5）：內部近平穩(ramp 低) 且 非退化(std 不近零)
        return [
            (a, b) for a, b in segs
            if seg_ramp(Xs, a, b) < config.golden_auto_ramp_max and seg_std(Xs, a, b) > 1e-3
        ]
    raise ValueError(f"未知 method={method!r}（支援 'trim'|'ssd'；wavelet 延後增量，需 PyWavelets）")


def segment_statistics(
    X: np.ndarray,
    segments: Sequence[tuple[int, int]],
    x_columns: Sequence[str],
    *,
    stats: Sequence[str] | None = None,
    config: Config = DEFAULT,
) -> pd.DataFrame:
    """每段算 [參數×統計] 特徵表。

    Args:
        X: (n, p) 製程參數。segments: ``detect_steady_segments`` 回傳的段。x_columns: 欄名（長度 p）。
        stats: 統計量子集（None→``config.seg_statistics``）；僅 ``_STAT_FUNCS`` 鍵。

    Returns:
        DataFrame：每列一段；段級 metadata 欄 ``seg_index/seg_start/seg_end/seg_len`` +
        ``{param}__{stat}`` 逐參數統計欄。空 segments → 空表（含欄名）。

    Raises:
        ValueError: stats 含未知統計量（如 count/mode——count 為段級 metadata、mode 本切片不提供）。
    """
    X = np.asarray(X, dtype=float)
    cols = list(x_columns)
    stat_list = list(config.seg_statistics if stats is None else stats)
    bad = [s for s in stat_list if s not in _STAT_FUNCS]
    if bad:
        raise ValueError(
            f"未知統計量 {bad}；支援 {list(_STAT_FUNCS)}。"
            "（count/seg_len 為段級 metadata、不入 [param×stat]；mode 連續退化本切片不提供）"
        )
    feat_cols = [f"{c}__{st}" for c in cols for st in stat_list]
    rows = []
    for i, (s, e) in enumerate(segments):
        block = X[s:e]
        row: dict = {"seg_index": i, "seg_start": int(s), "seg_end": int(e), "seg_len": int(e - s)}
        for j, c in enumerate(cols):
            col = block[:, j]
            for st in stat_list:
                row[f"{c}__{st}"] = _STAT_FUNCS[st](col)
        rows.append(row)
    return pd.DataFrame(rows, columns=list(_META_COLS) + feat_cols)


def _holm_flags(pvals: Sequence[float], alpha: float) -> list[bool]:
    """Holm–Bonferroni step-down 拒絕旗標（與 ``health._holm_reject`` 同語義；inline 避免耦合骨架）。"""
    p = list(pvals)
    m = len(p)
    order = list(np.argsort(p))
    flags = [False] * m
    still = True
    for rank, idx in enumerate(order):
        still = still and (p[idx] <= alpha / (m - rank))
        flags[idx] = still
    return flags


def segment_drift_view(
    golden_X: np.ndarray,
    query_X: np.ndarray,
    query_segments: Sequence[tuple[int, int]],
    x_columns: Sequence[str],
    *,
    stats: Sequence[str] | None = None,
    config: Config = DEFAULT,
    alpha: float | None = None,
) -> dict:
    """每個 [param×stat]×段 對 golden 的偏離 z + golden-null p-value（Holm 校正）。**非告警**。

    null（紅隊 B1，block-aware）：對每個 query 段（長度 s），抽 ``w_null_reps`` 個 golden **連續窗**（長 s）
    算同一統計 → ``z=(obs−mean(null))/(std(null)+1e-9)``、雙尾 ``p``。連續窗保自相關（吸收連續製程窗級
    變異），且 golden 僅 1 段時仍可定義（從 golden 原始樣本抽窗，非跨段 std）。

    退化守衛（Rule 12 不假評）：null std≈0（凍結/近常數感測器）/ golden 短於窗長 / query 段樣本 <
    ``max(seg_min_len, seg_min_obs_factor·p)`` → 該 cell z/p 回 NaN 並 warn。

    Args:
        golden_X: golden 穩態原始樣本 (ng, p)；query_X: query campaign 原始樣本 (nq, p)。
        query_segments: query 的穩態段（``detect_steady_segments``）。alpha: Holm 水準（None→config.fwer_alpha）。

    Returns:
        dict：``cells``（每筆 {seg_index,param,stat,obs,z,p_raw,significant_holm}）、``n_comparisons``、
        ``chance_band_z``（H0 下 max|z| 期望 √(2ln m)，供 UI 畫雜訊帶）、``is_advisory=True``。
    """
    golden_X = np.asarray(golden_X, dtype=float)
    query_X = np.asarray(query_X, dtype=float)
    cols = list(x_columns)
    p = len(cols)
    stat_list = list(config.seg_statistics if stats is None else stats)
    bad = [s for s in stat_list if s not in _STAT_FUNCS]
    if bad:
        raise ValueError(f"未知統計量 {bad}；支援 {list(_STAT_FUNCS)}（mode 本切片不提供）")
    a = config.fwer_alpha if alpha is None else float(alpha)
    reps = config.w_null_reps
    rng = np.random.default_rng(config.random_state)
    ng = len(golden_X)
    min_obs = max(config.seg_min_len, int(config.seg_min_obs_factor * p))
    cells: list[dict] = []
    degenerate = 0
    for si, (s, e) in enumerate(query_segments):
        s_len = e - s
        block = query_X[s:e]
        reliable = s_len >= min_obs and ng >= s_len
        for j, c in enumerate(cols):
            for st in stat_list:
                f = _STAT_FUNCS[st]
                obs = f(block[:, j])
                z = pval = float("nan")
                if reliable:
                    starts = rng.integers(0, ng - s_len + 1, size=reps)
                    null = np.array([f(golden_X[a0 : a0 + s_len, j]) for a0 in starts])
                    mu, sd = float(np.mean(null)), float(np.std(null))
                    if sd < 1e-9:  # 凍結/近常數感測器 → 不假評（health.py:172-175 同口徑）
                        degenerate += 1
                    else:
                        dev = abs(obs - mu)
                        z = (obs - mu) / (sd + 1e-9)
                        pval = (1 + int(np.sum(np.abs(null - mu) >= dev))) / (reps + 1)
                cells.append(
                    {"seg_index": si, "param": c, "stat": st, "obs": float(obs), "z": z, "p_raw": pval}
                )
    valid_idx = [k for k, cc in enumerate(cells) if not np.isnan(cc["p_raw"])]
    m = len(valid_idx)
    flags = _holm_flags([cells[k]["p_raw"] for k in valid_idx], a) if m else []
    for cc in cells:
        cc["significant_holm"] = False
    for k, fl in zip(valid_idx, flags):
        cells[k]["significant_holm"] = bool(fl)
    if degenerate:
        warnings.warn(
            f"segment_drift_view：{degenerate} 個 [param×stat] cell 因 golden null std≈0（凍結/近常數感測器）"
            "回 NaN，不假評（Rule 12）。",
            RuntimeWarning,
            stacklevel=2,
        )
    return {
        "cells": cells,
        "n_comparisons": m,
        "chance_band_z": float(np.sqrt(2.0 * np.log(max(m, 2)))),
        "is_advisory": True,
    }
