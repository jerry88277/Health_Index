"""降採樣 persistence 口徑揭露 WHY 測試（Rule 9；紅隊 A6）。

WHY：高維/長資料集降採樣（step>window）時，persistence/consecutive 把**相隔 step 的非相鄰窗**當「連續 N 窗」
→ 濾單窗毛刺的物理語義失真、n_alarms 不可跨不同降採樣設定比較。系統必須**揭露此口徑改變**（Rule 12 不靜默），
否則使用者把降採樣下的「連續告警」誤讀為物理連續。當降採樣下不揭露 persistence 口徑時，本測試失敗。
"""

from health_index.deploy.demo import build_and_save_model, score_timeline


def test_persistence_disclosed_when_subsampled(tmp_path):
    """降採樣（max_windows 小、step>window）→ persistence_spans_gaps=True + persistence_note 揭露口徑。"""
    r = build_and_save_model("synthetic", golden=(0, 300), models_dir=str(tmp_path), created_at="t", seed=5)
    tl = score_timeline(r["bundle_path"], "synthetic", window=60, max_windows=8, seed=5)
    assert tl["subsampled"] is True and tl["step"] > tl["window"]
    assert tl["persistence_spans_gaps"] is True
    assert tl["persistence_note"] and "非物理相鄰" in tl["persistence_note"]


def test_no_persistence_disclosure_when_full_coverage(tmp_path):
    """不降採樣（step==window，全覆蓋）→ persistence_spans_gaps=False、無口徑揭露（不過度標註）。"""
    r = build_and_save_model("synthetic", golden=(0, 300), models_dir=str(tmp_path), created_at="t", seed=5)
    tl = score_timeline(r["bundle_path"], "synthetic", window=60, max_windows=1000, seed=5)
    assert tl["subsampled"] is False and tl["step"] == tl["window"]
    assert tl["persistence_spans_gaps"] is False and tl["persistence_note"] is None
