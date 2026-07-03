"""batch-AVM 前處理 WHY 測試（Rule 9）：疊圖 + [param×stat] 指標轉換。

WHY：新精靈的兩個核心轉換——(1) 多批 temporal 疊圖（各批 trim 後對齊畫圖 + 可選 resample 中位/分位帶）；
(2) 每批 [param×stat] X*（映射模型輸入）。關鍵不變式：count 走**原生格**反映真實批長（餵 DQIx）、
cv 有 |mean| floor 不爆、min/max/range 為極值統計（測其正確但設計層知其跨批長度偏差）、疊圖帶 band_lo≤median≤band_hi。
本層為 advisory 純函數，隔離於主 HealthIndex（結構不變式，另由隔離測試鎖）。
"""

import numpy as np
import pytest

from health_index.preprocess.batch_features import (
    batch_indicator_matrix,
    batch_temporal_overlay,
)


def test_indicator_matrix_stats_and_native_count():
    X = np.array(
        [[1.0, 10.0], [3.0, 20.0], [5.0, 30.0],   # batch0：p0 mean3/std/range4/count3
         [2.0, 0.0], [4.0, 0.0],                    # batch1：p1 mean0 → cv NaN
         [1.0, 1.0], [1.0, 1.0], [1.0, 1.0], [1.0, 1.0], [1.0, 1.0]]  # batch2：p0 常數 → std0
    )
    batches = [(0, 3), (3, 5), (5, 10)]
    cols = ("p0", "p1")
    df = batch_indicator_matrix(
        X, batches, cols,
        stats=("mean", "std", "min", "max", "range", "median", "count", "cv"), trim_frac=0.0,
    )
    assert len(df) == 3
    b0 = df.iloc[0]
    assert b0["p0__mean"] == 3.0 and b0["p0__min"] == 1.0 and b0["p0__max"] == 5.0
    assert b0["p0__range"] == 4.0 and b0["p0__median"] == 3.0
    assert b0["p0__count"] == 3.0                                  # 原生格：真實批長
    assert abs(b0["p0__cv"] - (np.std([1.0, 3.0, 5.0]) / 3.0)) < 1e-12
    assert np.isnan(df.iloc[1]["p1__cv"])                          # |mean| floor：mean≈0 → NaN 非 inf
    assert df.iloc[2]["p0__count"] == 5.0                          # count 反映不同批長
    assert df.iloc[2]["p0__std"] == 0.0


def test_indicator_matrix_trim_uniform():
    X = np.arange(40.0).reshape(20, 2)
    df = batch_indicator_matrix(X, [(0, 20)], ("a", "b"), stats=("count",), trim_frac=0.2)
    assert df.iloc[0]["a__count"] == 12.0   # 丟頭 4 + 丟尾 4 = 中間 12


def test_overlay_native_traces_variable_length():
    rng = np.random.default_rng(0)
    X = rng.normal(size=(30, 1))
    batches = [(0, 8), (8, 20), (20, 30)]     # 長度 8/12/10 不一
    res = batch_temporal_overlay(X, batches, param=0, trim_frac=0.0, resample_n=None)
    assert len(res.traces) == 3
    assert res.traces[0]["values"].shape[0] == 8 and res.traces[1]["values"].shape[0] == 12
    assert res.median is None                 # 未 resample → 無帶
    assert np.all((res.traces[0]["t"] >= 0) & (res.traces[0]["t"] <= 1))


def test_overlay_resample_band_ordering():
    rng = np.random.default_rng(1)
    X = rng.normal(size=(60, 1))
    batches = [(0, 15), (15, 32), (32, 45), (45, 60)]
    res = batch_temporal_overlay(X, batches, param=0, trim_frac=0.05, resample_n=50, band_q=0.1)
    assert res.grid.shape == (50,) and res.median.shape == (50,)
    assert np.all(res.band_lo <= res.median) and np.all(res.median <= res.band_hi)


def test_batch_features_deterministic():
    rng = np.random.default_rng(2)
    X = rng.normal(size=(40, 3))
    batches = [(0, 20), (20, 40)]
    d1 = batch_indicator_matrix(X, batches, ("a", "b", "c"))
    d2 = batch_indicator_matrix(X, batches, ("a", "b", "c"))
    assert d1.equals(d2)
    o1 = batch_temporal_overlay(X, batches, param=1, resample_n=30)
    o2 = batch_temporal_overlay(X, batches, param=1, resample_n=30)
    assert np.array_equal(o1.median, o2.median)


def test_unknown_stat_fails_loud():
    with pytest.raises(ValueError, match="未知統計"):
        batch_indicator_matrix(np.zeros((5, 1)), [(0, 5)], ("a",), stats=("bogus",))
