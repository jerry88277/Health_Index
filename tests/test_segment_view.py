"""特徵建構層 demo endpoint WHY 測試（Rule 9）。

WHY：``segment_view`` 是特徵層接 UI 的**唯一**出口，且必須是**附加、不污染主路徑**——主路徑函式
（score_timeline/window_detail）不得呼叫 features，否則特徵層出錯會打掛健康指標主流程（v2 §1 結構不變式）。
本層回傳 is_advisory=True 的**可解釋視圖**、非告警。
"""

from __future__ import annotations

import inspect

import numpy as np
import pytest

from health_index.deploy import demo
from health_index.deploy.demo import segment_view


def test_segment_view_structure_and_advisory():
    """synthetic（有 drift 標記）→ 段定義 + [參數×統計] 偏離視圖；is_advisory；cells 數＝參數×統計×段。"""
    v = segment_view("synthetic", seed=5, drift_strength=1.2)
    assert set(v) >= {"dataset", "method", "params", "stats", "golden", "query", "feature_table", "drift", "traces", "note"}
    assert v["method"] == "trim"  # 預設
    n_seg = v["query"]["n_segments"]
    assert n_seg >= 1
    d = v["drift"]
    assert d["is_advisory"] is True
    assert len(d["cells"]) == len(v["params"]) * len(v["stats"]) * n_seg
    assert d["n_comparisons"] <= len(d["cells"]) and d["chance_band_z"] > 0
    # 每個選定參數都有 trace
    assert all(p in v["traces"] for p in v["params"])
    # 段全域邊界落在 query 區內
    qs, qe = v["query"]["start"], v["query"]["end"]
    assert all(qs <= s < e <= qe for s, e in v["query"]["segments"])


def test_segment_view_cells_sorted_by_abs_z():
    """偏離 cells 依 |z| 遞減排序（NaN 最後）——UI 排序「哪個[參數×統計]偏最多」需穩定排序。"""
    v = segment_view("synthetic", seed=5, drift_strength=1.2)
    zs = [abs(c["z"]) for c in v["drift"]["cells"] if c["z"] is not None]
    assert zs == sorted(zs, reverse=True)
    # NaN（None）cell 一律排在非 None 之後
    nones = [i for i, c in enumerate(v["drift"]["cells"]) if c["z"] is None]
    reals = [i for i, c in enumerate(v["drift"]["cells"]) if c["z"] is not None]
    assert not reals or not nones or max(reals) < min(nones)


def test_segment_view_ssd_method_and_feature_subset():
    """method='ssd' 走 PELT+穩態準則；features 子集 → 只回該子集參數。"""
    v = segment_view("synthetic", seed=5, drift_strength=1.2, method="ssd", features=["x00", "x03", "x07"])
    assert v["method"] == "ssd"
    assert v["params"] == ["x00", "x03", "x07"]
    assert all(p in v["traces"] for p in ["x00", "x03", "x07"])


def test_segment_view_no_drift_falls_back_to_second_half_with_warn():
    """無 drift 標記且未指定 query → 取後半段為比較區並 warn（誠實標，不靜默假裝有真值段）。"""
    import pandas as pd

    from health_index.adapters import registry
    from health_index.adapters.dataframe import from_frame

    name = "_segview_nodrift"

    def _b(**kw):
        rng = np.random.default_rng(0)
        X = rng.normal(0, 1, (400, 3))
        df = pd.DataFrame(X, columns=["a", "b", "c"])
        return from_frame(df, x_columns=["a", "b", "c"], golden=(0, 200), name=name)

    registry.register(name, _b, overwrite=True)
    try:
        with pytest.warns(RuntimeWarning, match="後半|drift"):
            v = segment_view(name)
        assert v["query"]["start"] == 200 and v["query"]["end"] == 400  # 後半
    finally:
        registry._BUILDERS.pop(name, None)


def test_main_path_does_not_touch_feature_layer():
    """**結構不變式（v2 §1）**：主路徑函式 score_timeline/window_detail 不得引用 features/segment_view
    ——特徵層為附加層，其失敗不可能影響健康指標主流程（靠『不耦合』成立，非靠運氣）。"""
    forbidden = ("segment_view", "detect_steady", "segment_drift", "segment_statistics", "preprocess.features")
    for fn in (demo.score_timeline, demo.window_detail):
        src = inspect.getsource(fn)
        for tok in forbidden:
            assert tok not in src, f"主路徑 {fn.__name__} 不應引用特徵層：{tok}"
