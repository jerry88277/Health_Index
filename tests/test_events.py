"""P1/P2 告警事件閉環 WHY 測試（Rule 9）。

WHY：現場工程師要 ACK/處置/清單、生產處長要事件閉環 + MTTR。事件庫的存在理由＝把「偵測」變成
「偵測→認領→關閉（含 MTTR 與處置留痕）」可稽核的閉環，且**同一裝置持續告警不重複開案**（防重）。
"""

from health_index.deploy.events import IncidentStore, severity_of

_T0 = "2026-06-16T10:00:00+08:00"
_T1 = "2026-06-16T10:30:00+08:00"  # +1800s


def _store(tmp_path):
    return IncidentStore(str(tmp_path / "incidents.json"))


def test_open_and_list(tmp_path):
    s = _store(tmp_path)
    inc = s.open_incident(product="A", window=[600, 660], health=0.40, confidence=0.91, top_cause="T1", detected_at=_T0)
    assert inc.id == "INC-0001" and inc.status == "open" and inc.severity == "critical"  # 低健康+高可信
    assert len(s.list()) == 1 and s.list(product="A")[0]["top_cause"] == "T1"


def test_dedup_one_active_per_product(tmp_path):
    """防重：同 product 已有 active 事件 → 再 open 回同一事件、不開新案；不同 product 才開新案。"""
    s = _store(tmp_path)
    a1 = s.open_incident(product="A", window=[600, 660], health=0.47, confidence=0.9, top_cause="T1", detected_at=_T0)
    a2 = s.open_incident(product="A", window=[660, 720], health=0.46, confidence=0.9, top_cause="T1", detected_at=_T0)
    b1 = s.open_incident(product="B", window=[0, 60], health=0.4, confidence=0.9, top_cause="F1", detected_at=_T0)
    assert a2.id == a1.id          # 同裝置未結 → 不重複開案
    assert b1.id == "INC-0002"     # 不同裝置 → 新案
    assert len(s.list()) == 2


def test_ack_close_mttr(tmp_path):
    """閉環：open→ack→close；MTTR = closed − detected（1800s）；處置留痕、ack_by 保留。"""
    s = _store(tmp_path)
    inc = s.open_incident(product="A", window=[600, 660], health=0.47, confidence=0.9, top_cause="T1", detected_at=_T0)
    s.ack(inc.id, by="王工", at=_T0)
    closed = s.close(inc.id, note="調 FV-101 開度後恢復", by="王工", at=_T1)
    assert closed.status == "closed" and closed.mttr_sec == 1800.0
    assert closed.close_note == "調 FV-101 開度後恢復" and closed.ack_by == "王工"


def test_reopen_after_close(tmp_path):
    """關閉後同裝置再告警 → 開**新**案（episode 結束才開新的）。"""
    s = _store(tmp_path)
    a1 = s.open_incident(product="A", window=[600, 660], health=0.47, confidence=0.9, top_cause="T1", detected_at=_T0)
    s.close(a1.id, note="ok", by="王工", at=_T1)
    a2 = s.open_incident(product="A", window=[700, 760], health=0.45, confidence=0.9, top_cause="T1", detected_at=_T1)
    assert a2.id != a1.id and len(s.list()) == 2


def test_stats_mttr(tmp_path):
    """處長 KPI：計數 + 平均 MTTR（僅 closed）。"""
    s = _store(tmp_path)
    a = s.open_incident(product="A", window=[600, 660], health=0.47, confidence=0.9, top_cause="T1", detected_at=_T0)
    s.close(a.id, note="x", by="工", at=_T1)               # mttr 1800
    s.open_incident(product="B", window=[0, 60], health=0.4, confidence=0.9, top_cause="F1", detected_at=_T0)  # open
    st = s.stats()
    assert st["total"] == 2 and st["closed"] == 1 and st["active"] == 1
    assert st["mean_mttr_sec"] == 1800.0 and st["mean_mttr_hr"] == 0.5


def test_false_alarm_excluded_from_mttr_and_roi(tmp_path):
    """現場工程師/處長：誤報(close_reason=false_alarm)不計入 MTTR 與 ROI（不汙染指標）。"""
    from health_index.deploy.roi import estimate_roi

    s = _store(tmp_path)
    a = s.open_incident(product="A", window=[0, 60], health=0.4, confidence=0.9, top_cause="T", detected_at=_T0)
    s.close(a.id, note="其實沒事", by="工", at=_T0, reason="false_alarm")  # 0s，誤報
    b = s.open_incident(product="B", window=[0, 60], health=0.4, confidence=0.9, top_cause="T", detected_at=_T0)
    s.close(b.id, note="真修", by="工", at=_T1, reason="real")              # 1800s，真實
    st = s.stats()
    assert st["false_alarm"] == 1 and st["closed"] == 2
    assert st["mean_mttr_sec"] == 1800.0  # 只算真實處置(B)，誤報(A,0s)排除
    r = estimate_roi(s.list(), avg_loss_per_unplanned_stop=1_000_000)
    assert r["n_critical_events"] == 1  # A(誤報)排除，只剩 B


def test_severity_rule():
    """確定性嚴重度：低健康+高可信=critical；低可信=warning（存疑不誇大）；健康=info。"""
    assert severity_of(0.40, 0.9) == "critical"
    assert severity_of(0.55, 0.9) == "warning"
    assert severity_of(0.40, 0.5) == "warning"   # 低可信 → 不升 critical
    assert severity_of(0.95, 0.95) == "info"


def test_persist_reload(tmp_path):
    """重啟安全：另一 store 實例讀同檔 → 事件持久。"""
    p = tmp_path / "incidents.json"
    IncidentStore(str(p)).open_incident(product="A", window=[0, 60], health=0.4, confidence=0.9, top_cause="T1", detected_at=_T0)
    assert len(IncidentStore(str(p)).list()) == 1
