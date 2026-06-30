"""G3 生產驗收報告 WHY 測試（Rule 9）。

WHY：部署 gate 的存在理由＝**在 hold-out golden 上確認 golden 不誤報、事故抓得到、SPC 盲**，
擋下不該上線的模型。當 gate 變成 rubber-stamp（對壞輸入也 PASS）時，下列測試失敗。
hold-out 用時間連續 split（保自相關、避桶5 §3.3 非平穩假象）。
"""

import numpy as np
import pytest

from health_index.adapters import registry
from health_index.deploy.acceptance import AcceptanceReport, acceptance_from_dataset, acceptance_report
from health_index.deploy.bundle import build_bundle
from health_index.health import HealthIndex


def _bundle(seed=5, ds=1.2):
    d, gt = registry.build("synthetic", seed=seed, drift_strength=ds)
    cols = list(gt.x_columns)
    gm = np.asarray(gt.golden_mask)
    gidx = np.flatnonzero(gm)
    cut = gidx[0] + len(gidx) // 2
    Xfit = d.frame.iloc[gidx[gidx < cut]][cols].to_numpy()
    Xhold = d.frame.iloc[gidx[gidx >= cut]][cols].to_numpy()
    Xdrift = d.frame.loc[np.asarray(gt.drift_mask), cols].to_numpy()
    b = build_bundle("A", HealthIndex().fit(Xfit), cols, golden=Xfit, created_at="t")
    return b, Xhold, Xdrift


def test_acceptance_passes_good_model():
    """marquee：好模型在 hold-out golden 上 FPR≤目標、事故 recall 高、SPC 盲 → PASS。"""
    r = acceptance_from_dataset("synthetic", seed=5, drift_strength=1.2, window=40, compute_fwer=False)
    assert r.holdout_golden_fpr <= 0.05 and r.fpr_ok
    assert r.drift_recall > 0.5 and r.recall_ok
    assert r.spc_blind is True
    assert r.passed


def test_acceptance_fpr_gate_is_falsifiable():
    """WHY（gate 非 rubber-stamp）：把**事故段當作 hold-out golden** 餵入 → FPR 應爆高 → fpr_ok=False
    → 不 PASS。證明 FPR gate 真的會擋（而非恆 PASS）。"""
    b, _Xhold, Xdrift = _bundle()
    r = acceptance_report(b, Xdrift, target_fpr=0.05, window=40, compute_fwer=False)  # drift 冒充 golden
    assert r.holdout_golden_fpr > 0.5 and r.fpr_ok is False and r.passed is False


def test_acceptance_recall_gate_catches_blind_model():
    """WHY：模型在事故段抓不到（recall 低）→ recall_ok=False → 不 PASS。用「golden 當 drift」模擬
    無訊號（健康段不該觸發）→ recall≈0 → gate 擋。"""
    b, Xhold, _ = _bundle()
    r = acceptance_report(b, Xhold, target_fpr=0.5, window=40, drift=Xhold, compute_fwer=False)  # drift=golden→無事故訊號
    assert r.drift_recall < 0.5 and r.recall_ok is False and r.passed is False


def test_acceptance_report_passed_skips_na_criteria():
    """WHY（誠實標）：無事故標記時 recall/spc 判準回 None、不計入 passed；passed 僅看適用判準。"""
    r = AcceptanceReport(
        product="A", window=40, n_golden_holdout=100, holdout_golden_fpr=0.0, golden_floor=0.9,
        drift_recall=None, spc_exceedance_excess=None, fpr_ok=True, recall_ok=None, spc_blind=None,
    )
    assert r.passed is True
    r2 = AcceptanceReport(**{**r.__dict__, "fpr_ok": False})
    assert r2.passed is False


def test_verdict_distinguishes_fpr_vs_recall_failure():
    """WHY（紅隊 B#3）：verdict 須區分 FPR 失敗（校準/平穩性）vs recall 失敗（偵測力），不讓使用者
    把兩種截然不同的故障誤讀為『模型整體爛』。"""
    base = dict(product="A", window=40, n_golden_holdout=100, golden_floor=0.9, spc_exceedance_excess=0.0, spc_blind=True)
    fpr_fail = AcceptanceReport(holdout_golden_fpr=0.3, drift_recall=0.9, fpr_ok=False, recall_ok=True, **base)
    assert "誤報率" in fpr_fail.verdict() and "recall" not in fpr_fail.verdict().split("；")[0]
    recall_fail = AcceptanceReport(holdout_golden_fpr=0.0, drift_recall=0.1, fpr_ok=True, recall_ok=False, **base)
    assert "偵測力" in recall_fail.verdict()
    ok = AcceptanceReport(holdout_golden_fpr=0.0, drift_recall=0.9, fpr_ok=True, recall_ok=True, **base)
    assert ok.verdict().startswith("PASS")


def test_acceptance_uses_holdout_not_fit_set():
    """WHY（誠實 hold-out）：報告的 golden FPR 來自與 fit disjoint 的 hold-out 段（非 in-sample 自評）。
    n_golden_holdout 應為 golden 後半、非全段。"""
    d, gt = registry.build("synthetic", seed=5)
    n_golden = int(np.asarray(gt.golden_mask).sum())
    r = acceptance_from_dataset("synthetic", seed=5, holdout_frac=0.5, window=40, compute_fwer=False)
    assert 0 < r.n_golden_holdout < n_golden  # 只用 hold-out 段（約半）


def test_acceptance_y_dimension_none_for_sparse_y():
    """#3：稀疏 Y（synthetic 5%）→ hold-out 窗 Y 觀測不足 → Y 側誤報率不適用回 None（誠實標、不假評），
    且不影響 X 側 passed。"""
    r = acceptance_from_dataset("synthetic", seed=5, drift_strength=1.2, window=40, compute_fwer=False)
    assert r.y_holdout_fpr is None and r.y_fpr_ok is None
    assert r.fpr_ok is True


def test_acceptance_includes_y_dimension_for_dense_clean_y():
    """#3：dense 且 X→Y 乾淨 → 驗收評得出 Y 側誤報率且過（軟測量在正常段不亂報品質飄移）。

    WHY：原驗收完全不含 Y 維度，含品質飄移/Y 校準爛的模型照樣 PASS。納入 Y 側 hold-out 誤報率後，gate 才涵蓋品質。
    """
    import pandas as pd

    from health_index.adapters.dataframe import from_frame

    name = "_acc_y_dense"

    def _b(**kw):
        rng = np.random.default_rng(0)
        w = np.array([1.0, 0.5, -0.3])
        X = rng.normal(0, 1, (400, 3))
        y = X @ w + rng.normal(0, 0.05, 400)  # 乾淨 X→Y、dense Y
        df = pd.DataFrame(X, columns=["a", "b", "c"])
        df["yq"] = y
        return from_frame(df, x_columns=["a", "b", "c"], y_value="yq", golden=(0, 400), name=name)

    registry.register(name, _b, overwrite=True)
    try:
        r = acceptance_from_dataset(name, window=40, compute_fwer=False)
        assert r.y_holdout_fpr is not None and r.y_fpr_ok is True  # 乾淨→Y 側不誤報、納入 gate
    finally:
        registry._BUILDERS.pop(name, None)


def test_user_selected_golden_discloses_selection_bias():
    """WHY（紅隊 A10 p-hacking 防護，誠實標 Option-A）：使用者圈 golden 段 → FPR 在該段上評。
    若反覆改選 golden 段直到 fpr_ok=True（跨次選擇偏誤/多重比較），此 FPR 是「選最佳」估計、非獨立
    out-of-sample 保證。報告須**自陳**此偏誤，不可讓使用者把 PASS 當全域保證。

    當使用者顯式傳 golden 規格 → golden_selected_by_user=True 且 selection_disclosure 揭露選擇偏誤；
    且 verdict() 含揭露語（PASS 也要附）。無此揭露＝靜默把 p-hacking 後的 FPR 當誠實估計＝測試失敗。
    """
    r = acceptance_from_dataset("synthetic", seed=5, window=40, compute_fwer=False, golden=(0, 300))
    assert r.golden_selected_by_user is True
    assert r.selection_disclosure is not None and "選擇" in r.selection_disclosure
    assert "選擇" in r.verdict()  # PASS/FAIL 都附揭露


def test_groundtruth_golden_no_selection_disclosure():
    """對偶：未傳 golden（用資料集固定真值段）→ 無使用者選段、不觸發選擇偏誤揭露（不過度告警）。"""
    r = acceptance_from_dataset("synthetic", seed=5, drift_strength=1.2, window=40, compute_fwer=False)
    assert r.golden_selected_by_user is False
    assert r.selection_disclosure is None
    assert "選擇" not in r.verdict()


def test_selection_disclosure_default_off_for_direct_report():
    """直接建 AcceptanceReport（不經 from_dataset）預設不揭露——欄位有預設、向後相容既有建構。"""
    r = AcceptanceReport(
        product="A", window=40, n_golden_holdout=100, holdout_golden_fpr=0.0, golden_floor=0.9,
        drift_recall=None, spc_exceedance_excess=None, fpr_ok=True, recall_ok=None, spc_blind=None,
    )
    assert r.golden_selected_by_user is False and r.selection_disclosure is None
    assert r.passed is True  # 揭露不影響 passed（只是誠實標，非 gate）
