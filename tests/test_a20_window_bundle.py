"""評分窗長存入 bundle＝單一真相 WHY 測試（Rule 9；紅隊 A20）。

WHY：評分窗長原由各消費端各自帶（精靈/score/下鑽/匯出/總覽燈）→ 建模與下鑽/匯出可能用不同窗長，治理
不可轉移、匯出與螢幕對不上。存入 bundle 後，一切以 bundle.window 為單一真相。當 score_timeline/下鑽不讀
bundle.window 而各自預設時，本測試失敗。窗長不入指紋（與 fit 時凍結的控制限解耦）→ verify 不受影響。
"""

from health_index.deploy.bundle import load
from health_index.deploy.demo import build_and_save_model, score_timeline


def test_window_stored_in_bundle_and_returned(tmp_path):
    """建模傳 window → 存入 bundle.window 且回傳；重載讀回一致。"""
    r = build_and_save_model("synthetic", golden=(0, 300), models_dir=str(tmp_path), created_at="t", seed=5, window=120)
    assert r["window"] == 120
    assert load(r["bundle_path"]).window == 120


def test_score_timeline_defaults_to_bundle_window(tmp_path):
    """score_timeline window=None → 讀 bundle.window（單一真相），非硬編 60；顯式傳值則覆寫。"""
    r = build_and_save_model("synthetic", golden=(0, 300), models_dir=str(tmp_path), created_at="t", seed=5, window=120)
    assert score_timeline(r["bundle_path"], "synthetic", window=None, seed=5)["window"] == 120  # 讀 bundle
    assert score_timeline(r["bundle_path"], "synthetic", window=40, seed=5)["window"] == 40      # 顯式覆寫


def test_bundle_without_window_falls_back(tmp_path):
    """未傳 window（模擬舊 bundle）→ bundle.window None → score_timeline window=None → getattr fallback 60。"""
    r = build_and_save_model("synthetic", golden=(0, 300), models_dir=str(tmp_path), created_at="t", seed=5)
    assert load(r["bundle_path"]).window is None
    assert score_timeline(r["bundle_path"], "synthetic", window=None, seed=5)["window"] == 60


def test_verify_unaffected_by_window(tmp_path):
    """window 不入指紋 → 載入 verify 通過（窗長與 fit 凍結的控制限解耦，紅隊已確認）。"""
    r = build_and_save_model("synthetic", golden=(0, 300), models_dir=str(tmp_path), created_at="t", seed=5, window=90)
    load(r["bundle_path"], verify=True)  # 不拋 BundleIntegrityError = 指紋不受 window 影響
