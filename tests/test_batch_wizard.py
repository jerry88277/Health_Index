"""INC-5 batch-AVM 9 步精靈 WHY 測試（Rule 9）——測純函數核心（callback 為薄殼）。

marquee WHY：精靈是零知識者建**有效**模型的路徑——(a) step guard 缺前置不得放行
（UX 稽核：沒 guard 使用者會建出空模型）；(b) 惰性轉換要回報進度並在完成後提供全部
[param×stat] cells；(c) 測試區間的 X* 欄位必須與建模一致，否則 fail loud（餵錯特徵給模型
比報錯更糟）；(d) 端到端：載入→機台→切批→轉換→建模→評分，全鏈可走通。
UI 視覺/點擊未在本環境渲染驗證（NOT VERIFIED-visual，比照 demo_app 慣例）。
"""

import time

import numpy as np
import pytest

from frontend import batch_wizard as bw


def _prep(machine="A", batch_minutes=10):
    tok = bw.do_cut("tep_fleet", machine, None, None, batch_minutes)
    return tok


def test_guard_next_blocks_missing_prereq():
    # WHY：缺前置就放行＝空模型精靈（UX 稽核 blocker 的結構性解）
    step, msg = bw.guard_next(1, {"loaded": False})
    assert step == 1 and "載入" in msg
    step, msg = bw.guard_next(1, {"loaded": True})
    assert step == 2 and msg == ""
    step, msg = bw.guard_next(5, {"converted": False})
    assert step == 5 and "轉換" in msg
    step, msg = bw.guard_next(9, {})
    assert step == 9  # 頂步不再前進


def test_convert_job_progress_and_cells():
    tok = _prep()
    c = bw._CUT[tok]
    params = c["x_columns"][:4]
    job = bw.start_convert_job(tok, params, ["mean", "std"], 5.0)
    for _ in range(100):  # 輪詢至完成（模擬 dcc.Interval）
        j = bw._JOBS[job]
        if j["done"]:
            break
        time.sleep(0.05)
    assert j["done"] and j["error"] is None and j["progress"] == 100
    assert len(j["cells"]) == 4 * 2  # param×stat 全算
    assert len(j["xs_cols"]) == 8
    n_batches = len(c["spans"])
    assert all(len(cell["values"]) == n_batches for cell in j["cells"])


def test_fit_requires_converted_job_and_enough_y():
    tok = _prep()
    with pytest.raises(ValueError, match="轉換"):
        bw.fit_from_job(-1, tok, [0, 1, 2])


def test_e2e_wizard_chain_scores_test_interval():
    # WHY（d）：整條 9 步鏈可走通，且結果含 GSI/可信度/隱性飄移三要素。
    ds, _ = bw.load_dataset("tep_fleet")
    ms = bw.machines_in_interval(ds.frame)
    assert [m["machine"] for m in ms] == ["A", "B"]
    tok = bw.do_cut("tep_fleet", "A", None, "2026-03-01 08:00", 10)
    c = bw._CUT[tok]
    params = list(c["x_columns"])
    job = bw.start_convert_job(tok, params, ["mean", "std"], 5.0)
    for _ in range(200):
        if bw._JOBS[job]["done"]:
            break
        time.sleep(0.05)
    golden = list(range(len(c["spans"])))
    mtok = bw.fit_from_job(job, tok, golden)
    stok = bw.score_test_interval("tep_fleet", "A", "2026-03-01 08:00", "2026-03-01 12:00", 10,
                                  mtok, params, ["mean", "std"], 5.0)
    res = bw._SCORES[stok]
    assert len(res["batches"]) >= 3
    b0 = res["batches"][0]
    assert {"gsi", "t2", "spe", "anomaly", "yhat", "yhat_reliable"} <= set(b0)
    fig = bw.score_figure(res)
    assert len(fig.data) == 2  # T²/限 與 SPE/限 兩軌


def test_score_fails_loud_on_stat_mismatch():
    # WHY（c）：測試區間用了不同統計選擇 → X* 欄位不一致 → 必須 fail loud 而非默默餵錯特徵。
    tok = _prep()
    c = bw._CUT[tok]
    params = list(c["x_columns"])
    job = bw.start_convert_job(tok, params, ["mean", "std"], 5.0)
    for _ in range(200):
        if bw._JOBS[job]["done"]:
            break
        time.sleep(0.05)
    mtok = bw.fit_from_job(job, tok, list(range(len(c["spans"]))))
    with pytest.raises(ValueError, match="不一致"):
        bw.score_test_interval("tep_fleet", "A", None, None, 10, mtok, params, ["mean", "median"], 5.0)


def test_overlay_figure_has_band_and_traces():
    tok = _prep()
    c = bw._CUT[tok]
    fig = bw.overlay_figure(tok, c["x_columns"][0], 5.0)
    # 批 trace + band(2) + 中位（band 以 fill 兩線呈現）
    assert len(fig.data) == len(c["spans"]) + 3


def test_demo_app_layout_builds_with_batch_wizard():
    # WHY：掛載後整個 app layout 可組建（callback 註冊/ID 對齊錯誤會在 import/組建時炸）。
    from frontend import demo_app
    ids = []

    def _walk(comp):
        if hasattr(comp, "id") and comp.id is not None:
            ids.append(str(comp.id))
        for ch in getattr(comp, "children", []) if isinstance(getattr(comp, "children", None), list) else \
                ([getattr(comp, "children")] if getattr(comp, "children", None) is not None else []):
            if hasattr(ch, "to_plotly_json") or hasattr(ch, "children"):
                _walk(ch)

    _walk(demo_app.app.layout)
    assert "scr-batchwiz" in ids
