"""P2 導入效益（ROI）WHY 測試（Rule 9）。

WHY：ROI 看板供生產處長做採購背書，數字一旦灌水、事後實測對不上就反噬信任。紅隊 A17：
效益分母 ``n_critical`` 應**只計已關閉的真實處置事件**（close_reason=='real'）——未關閉(open，
close_reason=None)、已知忽略(ignore)、誤報(false_alarm)都不是「因預警真正避免的停車」，混進分母即把
『未確認的自動告警數 × 自填損失 × 0.5』堆成可觀效益（A17 核心；結合 A1 事件常停在 open 更嚴重）。
當分母退回「計入未關閉/ignore 事件」時，下列測試失敗。
"""

from health_index.deploy.roi import estimate_roi


def _critical(close_reason):
    """一筆 critical 事件，指定 close_reason（None=未關閉 open）。"""
    return {"severity": "critical", "close_reason": close_reason}


def test_denominator_counts_only_real_dispositions():
    """A17：分母只計 close_reason=='real' 的已關閉真實處置；open/ignore/false_alarm 全排除。

    四筆 critical：real（計）、open 未關閉（不計）、ignore 已知忽略（不計）、false_alarm 誤報（不計）
    → n_critical_events 應為 1，而非 4；est_savings 對應 1×0.5×1e6=500k（非 2_000_000）。
    """
    incidents = [
        _critical("real"),         # 已關閉、真實處置 → 唯一計入
        _critical(None),           # 未關閉（open）→ 非已完成的避免停車
        _critical("ignore"),       # 已知狀況忽略 → 非真實處置
        _critical("false_alarm"),  # 誤報 → 不計入效益
    ]
    r = estimate_roi(incidents, avg_loss_per_unplanned_stop=1_000_000, prevented_fraction=0.5)
    assert r["n_critical_events"] == 1                 # 只有 real 那筆
    assert r["assumed_prevented_stops"] == 0.5         # 1 × 0.5
    assert r["est_savings"] == 500_000                 # 1 × 0.5 × 1e6


def test_open_critical_not_counted_until_closed_real():
    """A17 × A1：實務上多數 critical 停在 open（未確認自動告警），絕不可堆進效益分母→否則 ROI 全由自動告警虛灌。"""
    open_only = [_critical(None), _critical(None), _critical(None)]
    r = estimate_roi(open_only, avg_loss_per_unplanned_stop=1_000_000)
    assert r["n_critical_events"] == 0 and r["est_savings"] == 0


def test_non_critical_real_event_excluded():
    """只算 critical：已關閉的 warning/info 真實處置不進 ROI 分母（效益錨定在嚴重事件）。"""
    incidents = [
        {"severity": "warning", "close_reason": "real"},
        {"severity": "critical", "close_reason": "real"},
    ]
    r = estimate_roi(incidents, avg_loss_per_unplanned_stop=1_000_000)
    assert r["n_critical_events"] == 1


def test_assumptions_disclosed():
    """誠實標（Rule 12）：所有乘數假設透明回傳，供決策者判斷非實測。"""
    r = estimate_roi([_critical("real")], avg_loss_per_unplanned_stop=2_000_000, prevented_fraction=0.3)
    a = r["assumptions"]
    assert a["avg_loss_per_unplanned_stop"] == 2_000_000 and a["prevented_fraction"] == 0.3
    assert "估算" in a["note"]
