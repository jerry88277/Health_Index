"""INC-2 batch-AVM 資料品質/完整度視圖（精靈第 6 關「建模前」，advisory）。

- **X 側**：X*=[param×stat]（`batch_features.batch_indicator_matrix`）→ **fresh** `DQIxGate`
  對 golden 批 fit、對全批打 DQI_x（不 route 過 live L1 物件；DQIxGate 內建高維小 n PCA-score
  預降維）。批長 n 一致性閘（設計 §4：脫離常態批的極值統計不可比）。
- **Y 側（確定性准入閘，取代已砍除的 ART2 DQIy）**：存在性/有限性、robust 界限
  （median±k·MAD，抓單位錯/打錯小數點）、卡值 run（量測儀凍結）。
  「Y 未量測」與「Y 正常」明確分離（Rule 12：不得以未量測充健康）。
- 全輸出為純 Python 純量（可 `==` 比較、可 JSON 化）；`is_advisory=True`（非告警）。
"""

from __future__ import annotations

import numpy as np

from ..config import DEFAULT, Config
from ..detectors.dqi_x import DQIxGate
from ..preprocess.batch_features import batch_indicator_matrix

_META_COLS = ("batch", "start", "end", "len")


def _y_bound_flags(y: np.ndarray, present: np.ndarray, k: float) -> list:
    """robust 界限旗標：present 且 |y−median| > k·(1.4826·MAD) → True；absent → None。

    參考集 < 5 筆有效 Y 時回全 None（樣本不足不假評，Rule 12）。
    """
    ref = y[present]
    if ref.size < 5:
        return [None] * len(y)
    med = float(np.median(ref))
    mad_s = 1.4826 * float(np.median(np.abs(ref - med)))
    thr = max(k * mad_s, 1e-12)
    out: list = []
    for i in range(len(y)):
        out.append(bool(abs(y[i] - med) > thr) if present[i] else None)
    return out


def _y_stuck_flags(y: np.ndarray, present: np.ndarray, stuck_run: int) -> list[bool]:
    """卡值旗標：連續 ≥ stuck_run 批的有效 Y **完全相同** → 該 run 全標 True（NaN 斷 run）。"""
    n = len(y)
    flags = [False] * n
    if stuck_run < 2:
        return flags
    i = 0
    while i < n:
        if not present[i]:
            i += 1
            continue
        j = i
        while j + 1 < n and present[j + 1] and y[j + 1] == y[i]:
            j += 1
        if j - i + 1 >= stuck_run:
            for t in range(i, j + 1):
                flags[t] = True
        i = j + 1
    return flags


def batch_quality_view(
    X,
    y,
    batches,
    x_columns,
    *,
    golden_batches=None,
    stats=None,
    trim_frac: float = 0.05,
    y_bound_k: float = 5.0,
    y_stuck_run: int = 3,
    config: Config = DEFAULT,
) -> dict:
    """建模前的每批資料品質/完整度視圖（advisory，供精靈第 6 關顯示）。

    Args:
        X: (n, p) 製程參數矩陣。
        y: (n_batches,) 每批一筆量測（未量測為 NaN）。
        batches: [(start, end)] 每批 row span（end exclusive）。
        x_columns: 參數欄名。
        golden_batches: 供 DQI_x 建基準的批 index 清單；None 或 <4 批 → DQI 誠實回 None。
        stats: X* 統計集（None → batch_features 預設 8 統計）。
        trim_frac: 每批同法丟頭尾比例。
        y_bound_k: Y robust 界限倍數（median±k·MAD）。
        y_stuck_run: 卡值判定的連續相同批數。
        config: 全域超參（DQIxGate 用；cv_plus_min_obs 供映射門檻提示）。

    Returns:
        dict：per_batch（batch/start/end/n/x_nan_frac/n_out_of_family/dqi_x/dqi_x_over/
        y_present/y_out_of_bounds/y_stuck）、summary（n_batches/n_y_present/y_coverage/
        y_enough_for_mapping/dqi_available/x_star_dropped_columns/warnings）、is_advisory=True。

    Raises:
        ValueError: len(y) != len(batches)。
    """
    X = np.asarray(X, dtype=float)
    y = np.asarray(y, dtype=float)
    if len(y) != len(batches):
        raise ValueError(f"y 長度 {len(y)} 須等於批數 {len(batches)}（每批一筆量測，未量測為 NaN）")
    warnings_out: list[str] = []

    kwargs = {"trim_frac": trim_frac}
    if stats is not None:
        kwargs["stats"] = stats
    xs = batch_indicator_matrix(X, batches, x_columns, **kwargs)

    # 批長 n 一致性閘（robust）：|len − median| > max(3·1.4826·MAD, 0.1·median) → 脫離常態
    lens = xs["len"].to_numpy(dtype=float)
    med_len = float(np.median(lens))
    mad_len = 1.4826 * float(np.median(np.abs(lens - med_len)))
    len_thr = max(3.0 * mad_len, 0.1 * med_len)
    n_flags = [bool(abs(l - med_len) > len_thr) for l in lens]

    # X 側 fresh DQIxGate on X*（丟非有限欄；golden <4 批誠實跳過）
    feat_cols = [c for c in xs.columns if c not in _META_COLS]
    Xstar = xs[feat_cols].to_numpy(dtype=float)
    finite_col = np.isfinite(Xstar).all(axis=0)
    dropped = [c for c, ok in zip(feat_cols, finite_col) if not ok]
    if dropped:
        warnings_out.append(f"X* 含非有限值欄位已排除於 DQI：{dropped}")
    Xd = Xstar[:, finite_col]
    dqi_vals: list = [None] * len(batches)
    dqi_over: list = [None] * len(batches)
    dqi_available = False
    if golden_batches is not None and len(golden_batches) >= 4 and Xd.shape[1] >= 1:
        gate = DQIxGate(config=config).fit(Xd[list(golden_batches)])
        scores = gate.score(Xd)
        inlier = gate.is_inlier(Xd)
        dqi_vals = [float(s) for s in scores]
        dqi_over = [bool(not ok) for ok in inlier]
        dqi_available = True
    elif golden_batches is not None:
        warnings_out.append("golden 批 <4 或 X* 無可用欄位，DQI_x 不評（樣本不足不假評）")

    # Y 側確定性准入閘
    present = np.isfinite(y)
    oob = _y_bound_flags(y, present, y_bound_k)
    stuck = _y_stuck_flags(y, present, y_stuck_run)
    if int(present.sum()) < 5:
        warnings_out.append("有效 Y <5 筆，界限旗標不評（None）")

    per_batch = []
    for i, row in xs.iterrows():
        s, e = int(row["start"]), int(row["end"])
        seg = X[s:e]
        nan_frac = float(np.mean(~np.isfinite(seg))) if seg.size else 1.0
        per_batch.append({
            "batch": int(row["batch"]),
            "start": s,
            "end": e,
            "n": int(row["len"]),
            "x_nan_frac": nan_frac,
            "n_out_of_family": n_flags[i],
            "dqi_x": dqi_vals[i],
            "dqi_x_over": dqi_over[i],
            "y_present": bool(present[i]),
            "y_out_of_bounds": oob[i],
            "y_stuck": stuck[i],
        })

    n_y = int(present.sum())
    summary = {
        "n_batches": len(batches),
        "n_y_present": n_y,
        "y_coverage": float(n_y / len(batches)) if batches else 0.0,
        "y_enough_for_mapping": bool(n_y >= config.cv_plus_min_obs),  # CV+ 小 n 門檻（提示用）
        "dqi_available": dqi_available,
        "x_star_dropped_columns": dropped,
        "warnings": warnings_out,
    }
    return {"per_batch": per_batch, "summary": summary, "is_advisory": True}
