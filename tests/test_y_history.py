"""G1 純 Y-vs-歷史監控 WHY 測試（Rule 9）。

marquee WHY（G1 存在理由）：量測 Y 在**管制限內緩慢漂移**（隱性）——單點 3σ 永遠不響，
但 Y 已系統性偏離歷史。G1 必須：(a) **只看 Y**（獨立於 X 與 CL spec——結構性：API 無 X、
模組不 import 偵測鏈）；(b) 對隱性 creep **早於單點 3σ** 報警（CUSUM 層）；(c) 對 step 位移
由滑窗分布層（KS，3–5 筆）抓到；(d) 平穩 Y 不誤報。若 G1 對「始終在 3σ 內的 creep」不再
報警、或開始吃 X，本檔測試必須失敗。
ground truth＝合成儀器漂移 adapter（TEP 的 Y=f(X) 結構性不可證 G1，使用者定案合成資料）。
"""

import ast
import inspect

import numpy as np
import pytest

from health_index.adapters import instrument_drift
from health_index.y_history import YHistoryMonitor


def test_g1_catches_creep_that_is_systematically_spc_blind():
    # 緩漂 1.5σ/150 筆＝「隱性」：單點 3σ 對它**非系統性可見**（越限僅偶發雜訊，比例低——
    # 比照 TEP covert 的 univ≈0.04 口徑；裸 3σ 的偶發假警不算「看見」），G1 必須系統性抓到。
    yg, yo, truth = instrument_drift.generate(drift_total_sigma=1.5, seed=7)
    m = YHistoryMonitor().fit(yg)
    res = m.score(yo)
    s = res["summary"]
    assert s["alarm"] is True
    assert s["first_alarm_idx"] >= truth["drift_start"]   # 不在漂移前亂報
    z = np.abs((yo - m.med_) / m.mad_sigma_)
    univ_frac = float(np.mean(z[truth["drift_start"]:] > 3.0))
    assert univ_frac < 0.2                                # 單點 SPC 盲（漂移段越限比例低）
    assert s["direction"] == "up"


def test_no_alarm_on_stationary_y():
    yg, yo, _ = instrument_drift.generate(drift_total_sigma=0.0, n_drift=150, seed=11)
    res = YHistoryMonitor().fit(yg).score(yo)
    assert res["summary"]["alarm"] is False


def test_step_shift_caught_by_ks_window_layer():
    yg, yo, truth = instrument_drift.generate(drift_total_sigma=0.0, step_sigma=1.5, step_at=60, seed=13)
    res = YHistoryMonitor().fit(yg).score(yo)
    s = res["summary"]
    assert s["alarm"] is True and s["first_alarm_idx"] >= truth["step_at"]
    assert any(p["ks_alarm"] for p in res["points"])   # 分布層有貢獻
    assert s["direction"] == "up"


def test_onset_estimate_between_drift_start_and_k_crossing():
    # CUSUM onset（C± 最後歸零點）的正確語意：≈漂移**超過 allowance k** 的時點，非物理起點——
    # 緩漂前段斜率 < k 時 z−k<0、C± 持續歸零是數學必然。可行動的誠實區間＝[物理起點, k 交越點+餘裕]。
    yg, yo, truth = instrument_drift.generate(drift_total_sigma=2.0, seed=17)
    m = YHistoryMonitor().fit(yg)
    res = m.score(yo)
    onset = res["summary"]["onset_idx"]
    assert onset is not None
    slope = truth["drift_total_sigma"] / 150.0            # σ/步
    t_k_cross = truth["drift_start"] + m.config.g1_cusum_k / slope
    assert truth["drift_start"] <= onset <= t_k_cross + 15


def test_pure_y_by_construction_no_detector_imports():
    # WHY（G1 定義）：獨立於 X——模組只准 import numpy/scipy/config；API 無任何 X 參數。
    import health_index.y_history as mod
    tree = ast.parse(inspect.getsource(mod))
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
    for m_ in imported:
        assert not any(b in m_ for b in ("health", "detectors", "deploy", "preprocess", "batch_avm", "interface")), \
            f"G1 模組不得依賴偵測鏈/X 側：{m_}"
    sig = inspect.signature(YHistoryMonitor.score)
    assert "X" not in sig.parameters and "x" not in sig.parameters


def test_fail_loud_on_tiny_golden_and_deterministic():
    with pytest.raises(ValueError, match="歷史 Y"):
        YHistoryMonitor().fit(np.arange(5.0))
    yg, yo, _ = instrument_drift.generate(seed=19)
    r1 = YHistoryMonitor().fit(yg).score(yo)
    r2 = YHistoryMonitor().fit(yg).score(yo)
    assert r1 == r2
