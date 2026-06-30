"""特徵建構層 WHY 測試（Rule 9：測 intent 非 behavior）。

核心 WHY：本層是「段定義 + 可解釋視圖」，**不是偵測器**。最關鍵的測試（``test_hard_gate_*``）鎖死
『純多變量飄移（每參數段統計在規格內、但跨變數相關斷）→ 段統計視圖盲、但 L2 SPE 仍升』——這正是
本層**不可**被升級成主偵測器的理由（紅隊 v2 結構鎖）。當這條測試開始通過於「段統計也抓到 covert
drift」時，代表有人偷改了語義，測試該紅。
"""

from __future__ import annotations

import inspect

import numpy as np
import pytest

from health_index.config import DEFAULT
from health_index.preprocess import features as F
from health_index.preprocess.features import (
    detect_steady_segments,
    segment_drift_view,
    segment_statistics,
)


# ---------------------------------------------------------------- 段定義 --
def test_trim_drops_head_tail_keeps_middle():
    """trim：丟頭 seg_trim_head、丟尾 seg_trim_tail，中間為單一穩態段。"""
    X = np.random.default_rng(0).normal(0, 1, (100, 2))
    segs = detect_steady_segments(X, method="trim")
    assert segs == [(DEFAULT.seg_trim_head, 100 - DEFAULT.seg_trim_tail)]


def test_trim_too_short_returns_empty():
    """trim 後不足 seg_min_len → 不成段（誠實回空，非硬湊）。"""
    X = np.zeros((DEFAULT.seg_trim_head + DEFAULT.seg_trim_tail + 5, 2))
    assert detect_steady_segments(X, method="trim") == []


def test_ssd_excludes_ramp_transient_keeps_steady():
    """ssd：PELT 切段 + seg_ramp/seg_std 準則——非平穩 ramp 暫態段被排除、穩態段保留（不另造門檻）。"""
    rng = np.random.default_rng(1)
    ramp = np.linspace(0, 10, 50)[:, None] * np.ones((1, 2)) + rng.normal(0, 0.05, (50, 2))
    steady = rng.normal(5, 0.5, (250, 2))
    X = np.vstack([ramp, steady])
    segs = detect_steady_segments(X, method="ssd")
    assert segs, "ssd 應在穩態區找到 pseudo-run"
    # ramp 暫態（前 ~50）非平穩 → seg_ramp 高 → 全部被排除：保留段起點皆在 ramp 之後
    assert all(s >= 30 for s, _ in segs), f"ramp 暫態未被排除：{segs}"


def test_ssd_unknown_method_raises():
    """wavelet 延後增量 → 未知 method 明確 raise（不靜默退化）。"""
    with pytest.raises(ValueError, match="wavelet"):
        detect_steady_segments(np.zeros((50, 2)), method="wavelet")


# ---------------------------------------------------------- 段統計聚合 --
def test_segment_statistics_columns_and_count_excluded():
    """[param×stat] 笛卡兒積欄 + 段級 metadata；count/seg_len 為段級、不入 [param×stat] 網格。"""
    X = np.random.default_rng(0).normal(0, 1, (100, 2))
    segs = detect_steady_segments(X, method="trim")
    df = segment_statistics(X, segs, ["a", "b"], stats=["mean", "std"])
    assert list(df.columns) == ["seg_index", "seg_start", "seg_end", "seg_len", "a__mean", "a__std", "b__mean", "b__std"]
    assert len(df) == 1 and df.loc[0, "seg_len"] == 80


def test_segment_statistics_rejects_count_and_mode():
    """count（段級重複）/ mode（連續退化）不可入 [param×stat]——明確 raise（紅隊）。"""
    X = np.zeros((50, 2))
    segs = [(0, 50)]
    with pytest.raises(ValueError, match="count"):
        segment_statistics(X, segs, ["a", "b"], stats=["mean", "count"])
    with pytest.raises(ValueError):
        segment_statistics(X, segs, ["a", "b"], stats=["mode"])


# ----------------------------------------------- 偏離視圖（block-bootstrap）--
def test_drift_view_golden_self_no_false_alarm():
    """golden 自比：偏離 z≈0、Holm 後 0 顯著 cell（不誤報；is_advisory 標記）。"""
    rng = np.random.default_rng(2)
    golden = rng.normal(0, 1, (600, 3))
    query = rng.normal(0, 1, (200, 3))  # 同分佈
    qsegs = detect_steady_segments(query, method="trim")
    view = segment_drift_view(golden, query, qsegs, ["a", "b", "c"])
    assert view["is_advisory"] is True
    n_sig = sum(c["significant_holm"] for c in view["cells"])
    assert n_sig == 0, f"同分佈不該有顯著 cell，得 {n_sig}"
    assert view["chance_band_z"] > 0


def test_hard_gate_covert_drift_blind_to_segment_stats_but_l2_spe_rises():
    """**marquee（Rule 9 結構鎖）**：純多變量飄移（marginals 保留、跨變數相關斷）→ 段統計偏離視圖
    Holm 後 0 顯著（盲），但 L2 SPE 大幅升。證明段統計**不可**取代主偵測器；此測試若因『段統計也抓到
    covert drift』而通過，代表語義被偷改，應紅。"""
    from health_index.detectors.mspc import MSPCModel

    rng = np.random.default_rng(3)
    x1g = rng.normal(0, 1, 600)
    golden = np.column_stack([x1g, x1g + rng.normal(0, 0.05, 600)])  # x2≈x1（強相關）
    x1q = rng.normal(0, 1, 200)
    query = np.column_stack([x1q, rng.normal(0, 1, 200)])  # x2 獨立：marginals 同、相關斷（covert）

    # 段統計視圖：marginals 保留 → 偏離不顯著（盲）
    qsegs = detect_steady_segments(query, method="trim")
    view = segment_drift_view(golden, query, qsegs, ["x1", "x2"])
    n_sig = sum(c["significant_holm"] for c in view["cells"])
    assert n_sig == 0, f"段統計視圖對 covert drift 應盲（marginals 保留），卻有 {n_sig} 顯著 cell"

    # L2 SPE：相關結構斷 → 殘差升（主訊號）
    mspc = MSPCModel(DEFAULT).fit(golden)
    spe_g = float(mspc.spe(golden).mean())
    spe_q = float(mspc.spe(query).mean())
    assert spe_q > 5 * spe_g, f"L2 SPE 應對 covert drift 大幅升：golden {spe_g:.3g} vs query {spe_q:.3g}"


def test_drift_view_frozen_sensor_nan_and_warn():
    """凍結/近常數感測器（golden null std≈0）→ 該 cell z/p 回 NaN 並 warn（Rule 12 不假評）。"""
    rng = np.random.default_rng(4)
    golden = np.column_stack([rng.normal(0, 1, 400), np.full(400, 5.0)])  # 第二欄凍結
    query = np.column_stack([rng.normal(0, 1, 200), np.full(200, 5.0)])
    qsegs = detect_steady_segments(query, method="trim")
    with pytest.warns(RuntimeWarning, match="std≈0|凍結"):
        view = segment_drift_view(golden, query, qsegs, ["live", "frozen"])
    frozen_cells = [c for c in view["cells"] if c["param"] == "frozen"]
    assert frozen_cells and all(np.isnan(c["z"]) for c in frozen_cells)


def test_drift_view_short_segment_nan():
    """query 段樣本 < max(seg_min_len, factor·p) → 不假評（cell NaN）。"""
    rng = np.random.default_rng(5)
    golden = rng.normal(0, 1, (400, 2))
    query = rng.normal(0, 1, (200, 2))
    view = segment_drift_view(golden, query, [(0, 10)], ["a", "b"])  # 段長 10 < seg_min_len 20
    assert all(np.isnan(c["z"]) for c in view["cells"])


# ------------------------------------------- 結構不變式（附加層，不耦合骨架）--
def test_features_module_does_not_import_skeleton():
    """結構鎖：features 只依賴 config + preprocess.segment，**不 import** health/detectors/demo
    （主路徑出錯不影響 HI/alarm 的不變式靠『不耦合』成立，非靠運氣）。"""
    src = inspect.getsource(F)
    for forbidden in ("from ..health", "from ..detectors", "from ..deploy", "import health_index.health"):
        assert forbidden not in src, f"features 不應 import 骨架：{forbidden}"
