"""分段 WHY 測試（Rule 9）。

核心 WHY：golden-A baseline 必須【乾淨且只含第一段穩態 A】。若分段讓 golden 混入
re-entry/drift 段或 transition settling，偵測基準被毒化——這類「基準不再乾淨」的情況
必須讓測試失敗（紅隊 H1）。
"""

import numpy as np
import pandas as pd

from health_index import interface as I
from health_index.adapters import synthetic as syn
from health_index.preprocess import segment as seg


def test_campaign_ids_five_campaigns():
    ds, _ = syn.generate(n_per_campaign=100)
    fr = seg.segment(ds)
    cids = fr[I.CAMPAIGN_ID].to_numpy()
    assert set(np.unique(cids)) == {0, 1, 2, 3, 4}
    assert (np.flatnonzero(np.diff(cids) != 0) + 1).tolist() == [100, 200, 300, 400]


def test_change_points_recover_grade_boundaries():
    # WHY: label-agnostic 偵測器須能在無標籤時找回 grade 邊界（真實資料用）
    ds, _ = syn.generate(n_per_campaign=120, seed=1)
    X = ds.frame[list(ds.x_columns)].to_numpy()
    bkps = seg.detect_change_points(X, n_bkps=4)
    for true_b in (120, 240, 360, 480):
        assert any(abs(b - true_b) <= 5 for b in bkps), f"{true_b} 未被偵測: {bkps}"


def test_pelt_path_default_penalty_runs():
    # WHY: PELT(penalty) 是真實無標籤資料路徑；未給 penalty 須自動取 config.ssd_penalty
    # （單一 config 治理）。此路徑先前無測試覆蓋（紅隊 🔴-2）。
    ds, _ = syn.generate(n_per_campaign=150, seed=2)
    X = ds.frame[list(ds.x_columns)].to_numpy()
    bkps = seg.detect_change_points(X)  # 預設走 PELT + config.ssd_penalty
    assert isinstance(bkps, list)
    assert all(0 < b < len(X) for b in bkps)
    # 強邊界（mean-shift 的 grade 切換）多數應被找到
    hits = sum(any(abs(b - t) <= 10 for b in bkps) for t in (150, 300, 450, 600))
    assert hits >= 3, f"PELT 只找到 {hits}/4 強邊界: {bkps}"


def test_golden_excludes_transition_and_drift():
    ds, gt = syn.generate(n_per_campaign=100)
    fr = seg.segment(ds)  # transition_width 預設 10
    golden = fr[I.IS_GOLDEN_A].to_numpy()
    assert golden[10:100].all()        # 第一段 A 的穩態部分
    assert not golden[:10].any()       # transition settling 排除
    assert not golden[100:].any()      # 後續所有 campaign 排除
    # 關鍵 WHY：drift 段（最後 100）絕不在 golden baseline
    assert not (golden & gt.drift_mask).any()
    # 也不含乾淨 re-entry A（campaign 2）
    s, e, _ = gt.campaign_bounds[2]
    assert not golden[s:e].any()


def test_transition_rows_have_no_run():
    ds, _ = syn.generate(n_per_campaign=100)
    fr = seg.segment(ds)
    trans = fr[I.MODE].to_numpy() == I.Mode.TRANSITION.value
    assert (fr.loc[trans, I.RUN_ID].to_numpy() == -1).all()
    assert trans.sum() == 5 * 10  # 5 campaigns × transition_width(10)


def test_segment_is_deterministic_and_pure():
    ds, _ = syn.generate(seed=3)
    pd.testing.assert_frame_equal(seg.segment(ds), seg.segment(ds))
