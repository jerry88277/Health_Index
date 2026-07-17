"""#8 G1×G3 同窗共發通知組裝 WHY 測試（Rule 9）。

marquee WHY：鎖定決策（使用者 2026-07-02）＝G1（實際 Y 偏離歷史）與 G3（Ŷ 越適用域）同窗共發時
**發兩封獨立信、不合併成單一裁決**（兩者正交：G1 是已確認的真實量測偏離、獨立於 X 與 Ŷ；G3 是 Ŷ
預測可信度警訊）。測試鎖：
(a) G1×G3 同批 → **恰兩封**、goal 各異、主旨不同（合併成一封＝被否決的設計，測試要失敗）；
(b) 優先規則：G1 先於 G3（已確認實際偏離 > 預測不可信警訊）；
(c) 兩封**互相交叉引用**（co_fired），收件人看得到全貌；
(d) 每封指名肇因——G1 帶 G2 的 X 歸因、G3 帶越域參數；只一個觸發→只一封（無幻影）。
確定性（Rule 5）：SMTP 傳輸 deferred，本模組只做確定性 payload 組裝。
"""

from health_index.notify import PRECEDENCE, compose_notifications


def test_g1_g3_same_window_makes_two_separate_emails():
    # WHY(a)：同窗共發→恰兩封、不合併。
    ns = compose_notifications(batch_index=7,
                               g1={"drifted": True}, g3={"alarm": True, "top_param": "c2", "reason": "Ŷ範圍"})
    assert len(ns) == 2
    assert {n.goal for n in ns} == {"G1", "G3"}
    assert ns[0].subject != ns[1].subject           # 兩封主旨不同（非合併單一裁決）


def test_precedence_g1_before_g3():
    # WHY(b)：優先規則 G1 > G3。
    ns = compose_notifications(batch_index=1, g1={"drifted": True}, g3={"alarm": True, "top_param": "c0"})
    assert [n.goal for n in ns] == ["G1", "G3"]
    assert ns[0].priority < ns[1].priority
    assert PRECEDENCE["G1"] < PRECEDENCE["G3"]


def test_two_emails_cross_reference_each_other():
    # WHY(c)：兩封互相交叉引用（co_fired），收件人見全貌。
    ns = compose_notifications(batch_index=3, g1={"drifted": True}, g3={"alarm": True, "top_param": "c1"})
    by = {n.goal: n for n in ns}
    assert "G3" in by["G1"].co_fired and "G1" in by["G3"].co_fired


def test_g1_carries_g2_x_attribution():
    # WHY(d)：Y 漂移那封須帶 G2 的 X 歸因（哪個參數推動 Y）。
    ns = compose_notifications(batch_index=2, g1={"drifted": True}, g2={"top_param": "c3"})
    assert len(ns) == 1 and ns[0].goal == "G1"
    assert "c3" in ns[0].cause


def test_g3_names_offending_param():
    ns = compose_notifications(batch_index=2, g3={"alarm": True, "top_param": "c4", "reason": "leverage"})
    assert len(ns) == 1 and ns[0].goal == "G3"
    assert "c4" in ns[0].cause and "leverage" in ns[0].cause


def test_only_one_goal_makes_one_email_no_phantom():
    # WHY(d 續)：只一個觸發→只一封；未觸發不產生幻影信。
    assert compose_notifications(g1={"drifted": False}, g3={"alarm": False}) == []
    assert len(compose_notifications(g3={"alarm": True, "top_param": "c0"})) == 1
    only_g1 = compose_notifications(g1={"drifted": True})
    assert len(only_g1) == 1 and only_g1[0].co_fired == ()


def test_deterministic():
    kw = dict(batch_index=5, g1={"drifted": True}, g2={"top_param": "c2"},
              g3={"alarm": True, "top_param": "c1", "reason": "Ŷ範圍"})
    a = compose_notifications(**kw)
    b = compose_notifications(**kw)
    assert [(n.goal, n.subject, n.cause, n.co_fired) for n in a] == \
           [(n.goal, n.subject, n.cause, n.co_fired) for n in b]
