"""INC-2 batch-AVM 資料品質/完整度視圖 WHY 測試（Rule 9）。

marquee WHY（精靈第 6 關 + DQIy 裁決）：建模前使用者必須看到「資料夠不夠好」——X 側用 fresh
DQIxGate 對 X* 打分（不碰 live L1 物件，隔離裁決），Y 側用**確定性品質准入閘**取代已砍除的
ART2 DQIy（准入閘≠漂移偵測；garbage-in 的 Y 會毒化 G1 歷史基準——風險稽核 R13）。
若「Y 沒量到」被當成「Y 沒異常」、或壞 Y（卡值/單位錯）靜默進基準，本檔測試必須失敗。
"""

import numpy as np

from health_index.batch_avm.quality import batch_quality_view


def _mk(n_batches=6, per=20, p=2, seed=0):
    rng = np.random.default_rng(seed)
    X = rng.normal(size=(n_batches * per, p))
    batches = [(i * per, (i + 1) * per) for i in range(n_batches)]
    return X, batches


def test_y_coverage_counts_missing():
    # WHY：稀疏 Y 是常態（實驗室量測）；「未量測」須明確標示、不得計入健康/異常任何一邊。
    X, batches = _mk()
    y = np.array([1.0, np.nan, 1.1, np.nan, 0.9, np.nan])
    v = batch_quality_view(X, y, batches, ("a", "b"))
    assert v["is_advisory"] is True
    present = [b["y_present"] for b in v["per_batch"]]
    assert present == [True, False, True, False, True, False]
    assert v["summary"]["n_y_present"] == 3
    assert abs(v["summary"]["y_coverage"] - 0.5) < 1e-12


def test_y_stuck_run_flagged():
    # WHY：量測儀卡值（連續多批一模一樣的值）是 garbage-in 的典型形態；ART2 已砍，這裡是替代的確定性閘。
    X, batches = _mk(n_batches=8)
    y = np.array([1.00, 1.03, 2.50, 2.50, 2.50, 1.01, 0.99, 1.02])
    v = batch_quality_view(X, y, batches, ("a", "b"), y_stuck_run=3)
    stuck = [b["y_stuck"] for b in v["per_batch"]]
    assert stuck[2] and stuck[3] and stuck[4]
    assert not any(stuck[:2]) and not any(stuck[5:])


def test_y_out_of_bounds_flagged():
    # WHY：單位換算錯/打錯小數點（100×）必須在進基準前被攔下，否則 G1 歷史基準被毒化。
    X, batches = _mk(n_batches=8, seed=1)
    y = np.array([1.0, 1.1, 0.95, 1.05, 105.0, 1.02, 0.98, 1.0])
    v = batch_quality_view(X, y, batches, ("a", "b"))
    oob = [b["y_out_of_bounds"] for b in v["per_batch"]]
    assert oob[4] is True
    assert sum(1 for f in oob if f) == 1


def test_dqi_x_flags_outlier_batch_with_fresh_gate():
    # WHY：X 側域效度用 fresh DQIxGate 對 X* 打分（隔離裁決：不 route 過 live L1 物件）；
    # 整批 X 大幅偏移 → 該批 X* 離 golden 域 → dqi 超門檻，供第 6 關「建模前」就看到。
    rng = np.random.default_rng(2)
    per, nb = 30, 25
    X = rng.normal(size=(nb * per, 2))
    X[-per:] += 8.0  # 最後一批整批偏移
    batches = [(i * per, (i + 1) * per) for i in range(nb)]
    y = np.ones(nb)
    v = batch_quality_view(X, y, batches, ("a", "b"), golden_batches=list(range(20)), stats=("mean", "std"))
    pb = v["per_batch"]
    assert pb[-1]["dqi_x_over"] is True
    golden_over = [b["dqi_x_over"] for b in pb[:20]]
    assert sum(1 for f in golden_over if f) <= 2  # golden 大多在域內
    assert v["summary"]["dqi_available"] is True


def test_no_golden_means_no_dqi_but_view_still_works():
    # WHY：第 6 關可能在選 golden 前就看完整度——DQI 缺 golden 就誠實回 None，不假評（Rule 12）。
    X, batches = _mk()
    y = np.ones(6)
    v = batch_quality_view(X, y, batches, ("a", "b"))
    assert v["summary"]["dqi_available"] is False
    assert all(b["dqi_x"] is None for b in v["per_batch"])


def test_batch_length_out_of_family_flagged():
    # WHY：設計 §4 的 n 一致性閘——批長脫離常態（中止批/取樣率變）→ 極值統計不可比，須標記。
    per = 20
    spans = [(0, 20), (20, 40), (40, 60), (60, 80), (80, 100), (100, 106)]  # 最後一批只有 6 點
    X = np.random.default_rng(3).normal(size=(106, 2))
    y = np.ones(6)
    v = batch_quality_view(X, y, spans, ("a", "b"), trim_frac=0.0)
    flags = [b["n_out_of_family"] for b in v["per_batch"]]
    assert flags[-1] is True and not any(flags[:-1])


def test_deterministic():
    X, batches = _mk(n_batches=10, seed=4)
    y = np.arange(10, dtype=float)
    v1 = batch_quality_view(X, y, batches, ("a", "b"), golden_batches=[0, 1, 2, 3, 4, 5])
    v2 = batch_quality_view(X, y, batches, ("a", "b"), golden_batches=[0, 1, 2, 3, 4, 5])
    assert v1 == v2
