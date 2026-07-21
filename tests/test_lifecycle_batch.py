"""#9 批次生命週期 runtime WHY 測試（Rule 9）。

marquee WHY：4h CSTR 批的監控時序（使用者 2026-07-02）＝10min 起監 X → 2h 算 Ŷ_middle（越域→通知）
→ 4h 算 Ŷ_final（越域→通知）→ 真實 Y 出爐比歷史（G1）→ 歸因 X（G2）→ 通知。測試鎖：
(a) **G1 不可能在真實 Y 出爐前判定**——Ŷ 相位只出 G3，絕不出 G1（結構性；搶跑＝假訊號）；
(b) G3 在 middle/final 越域即通知，且**同批不重複發**（重複＝重複告警／未來重複扣費 SMTP）；
(c) Y 出爐→G1 觸發時帶 G2 的 X 歸因；同批先前已發 G3 者，總計仍是**兩封獨立信**（#8 鎖定決策）
    且不重送 G3；
(d) 相位冪等 + resume-safe（已完成相位重入不重發）；
(e) **誠實標記**：10min/2h 相位的 X* 來自部分批資料、與 golden 全批 X* 不可交換 →
    `partial_basis=True`（假裝已校準＝違 Rule 12，測試要失敗）。
確定性（Rule 5）。
"""

import numpy as np

from health_index.batch_avm.lifecycle import (
    DEFAULT_SCHEDULE,
    LifecycleState,
    due_phases,
    run_phase,
)
from health_index.batch_avm.mapping import fit_batch_model
from health_index.y_history import YHistoryMonitor


def _setup(n=60, p=5, seed=0):
    rng = np.random.default_rng(seed)
    X = rng.normal(size=(n, p))
    y = 3.0 * X[:, 0] + 0.1 * rng.normal(size=n)
    m = fit_batch_model(X, y, columns=[f"c{i}" for i in range(p)])
    ym = YHistoryMonitor().fit(y)
    return m, X, y, ym


def test_due_phases_follow_4h_schedule():
    # WHY：排程＝10min 起監 X、2h Ŷ_middle、4h Ŷ_final。
    assert due_phases(0.05, schedule=DEFAULT_SCHEDULE, completed=()) == []
    assert due_phases(0.2, schedule=DEFAULT_SCHEDULE, completed=()) == ["x_monitor"]
    assert due_phases(2.0, schedule=DEFAULT_SCHEDULE, completed=("x_monitor",)) == ["yhat_middle"]
    assert due_phases(4.0, schedule=DEFAULT_SCHEDULE,
                      completed=("x_monitor", "yhat_middle")) == ["yhat_final"]
    # 已完成不再 due（冪等）
    assert due_phases(4.0, schedule=DEFAULT_SCHEDULE,
                      completed=("x_monitor", "yhat_middle", "yhat_final")) == []


def test_yhat_phases_never_emit_g1():
    # WHY(a)：G1＝實際 Y vs 歷史，Y 未出爐前**結構上不可判**；Ŷ 相位搶跑 G1＝假訊號。
    m, X, _y, _ym = _setup()
    st = LifecycleState(batch_index=0)
    for ph, t in (("x_monitor", 0.2), ("yhat_middle", 2.0), ("yhat_final", 4.0)):
        ev, st = run_phase(m, st, phase=ph, t_hours=t, xstar_row=X[0])
        assert ev.g1_alarm is False
        assert all(n.goal != "G1" for n in ev.notifications)


def test_partial_phases_marked_partial_basis():
    # WHY(e)：部分批 X* 與 golden 全批 X* 不可交換 → 誠實標，不假裝已校準。
    m, X, _y, _ym = _setup()
    st = LifecycleState(batch_index=1)
    ev_x, st = run_phase(m, st, phase="x_monitor", t_hours=0.2, xstar_row=X[0])
    ev_mid, st = run_phase(m, st, phase="yhat_middle", t_hours=2.0, xstar_row=X[0])
    ev_fin, st = run_phase(m, st, phase="yhat_final", t_hours=4.0, xstar_row=X[0])
    assert ev_x.partial_basis is True and ev_mid.partial_basis is True
    assert ev_fin.partial_basis is False           # 全批才算校準基準
    assert "部分批" in ev_mid.detail.get("caveat", "")


def test_g3_out_of_domain_notifies_once_per_batch():
    # WHY(b)：Ŷ 越域→通知；同批不重複發（防重複告警/重複扣費）。
    m, X, _y, _ym = _setup()
    q = X.mean(axis=0).copy()
    q[0] += 6.0                                    # Ŷ 遠超 golden 範圍 → G3 AD 觸發
    st = LifecycleState(batch_index=2)
    ev_mid, st = run_phase(m, st, phase="yhat_middle", t_hours=2.0, xstar_row=q)
    assert ev_mid.g3_alarm is True
    assert [n.goal for n in ev_mid.notifications] == ["G3"]
    ev_fin, st = run_phase(m, st, phase="yhat_final", t_hours=4.0, xstar_row=q)
    assert ev_fin.g3_alarm is True                 # 仍越域（誠實回報狀態）
    assert ev_fin.notifications == []              # 但同批不重送 G3


def test_y_measured_fires_g1_with_g2_attribution():
    # WHY(c)：Y 出爐→G1；觸發時帶 G2 的 X 歸因。
    m, X, y, ym = _setup()
    y_online = np.concatenate([y[:30], y[:30] + 6.0])   # 後段明顯偏移 → G1
    st = LifecycleState(batch_index=3, completed=("x_monitor", "yhat_middle", "yhat_final"))
    ev, st = run_phase(m, st, phase="y_measured", t_hours=4.1, xstar_row=X[0],
                       y_online=y_online, y_monitor=ym)
    assert ev.g1_alarm is True
    g1s = [n for n in ev.notifications if n.goal == "G1"]
    assert len(g1s) == 1 and "c" in g1s[0].cause    # 帶 G2 歸因參數


def test_g1_and_prior_g3_total_two_emails_no_resend():
    # WHY(c 續)：同批 G3（先）+ G1（後）＝總計兩封獨立信，且不重送 G3（#8 鎖定決策）。
    m, X, y, ym = _setup()
    q = X.mean(axis=0).copy()
    q[0] += 6.0
    y_online = np.concatenate([y[:30], y[:30] + 6.0])
    st = LifecycleState(batch_index=4)
    ev_fin, st = run_phase(m, st, phase="yhat_final", t_hours=4.0, xstar_row=q)
    ev_y, st = run_phase(m, st, phase="y_measured", t_hours=4.1, xstar_row=q,
                         y_online=y_online, y_monitor=ym)
    goals = [n.goal for n in ev_fin.notifications] + [n.goal for n in ev_y.notifications]
    assert sorted(goals) == ["G1", "G3"]            # 恰兩封、各一
    assert ev_y.detail.get("co_g3") is True         # G1 那封知道同批曾 G3（交叉引用全貌）


def test_phase_idempotent_and_resume_safe(tmp_path):
    # WHY(d)：已完成相位重入→不重發通知；狀態可存載續跑。
    m, X, _y, _ym = _setup()
    q = X.mean(axis=0).copy()
    q[0] += 6.0
    st = LifecycleState(batch_index=5)
    ev1, st = run_phase(m, st, phase="yhat_final", t_hours=4.0, xstar_row=q)
    assert len(ev1.notifications) == 1
    ev2, st2 = run_phase(m, st, phase="yhat_final", t_hours=4.0, xstar_row=q)
    assert ev2.notifications == [] and ev2.detail.get("skipped") is True
    s = st2.to_json()
    back = LifecycleState.from_json(s)
    assert back.completed == st2.completed and back.g3_notified == st2.g3_notified


def test_deterministic():
    m, X, _y, _ym = _setup(seed=4)
    a, _ = run_phase(m, LifecycleState(batch_index=6), phase="yhat_final", t_hours=4.0, xstar_row=X[2])
    b, _ = run_phase(m, LifecycleState(batch_index=6), phase="yhat_final", t_hours=4.0, xstar_row=X[2])
    assert a.yhat == b.yhat and a.g3_alarm == b.g3_alarm
