"""品質事件 severity/health 決策 WHY 測試（Rule 9；紅隊 A14/A15）。

WHY：品質事件不能在「無實際 Y 落地證據」下灌出 critical——純 Ŷ 水準漂移是由**已漂移的 X 外推**而來
（推論的推論），且該 X 漂移已被 X 側 health 抓＝雙重計數 + 警報疲勞。當 Ŷ-only 路徑又能升 critical、或
health 用硬編 9、或 severity 借 X 側 T² confidence 時，下列測試失敗。
"""

from health_index.config import DEFAULT
from health_index.deploy.demo import quality_incident_decision

_ZREF = DEFAULT.y_trend_z_max  # 3.0


def test_real_y_residual_evidence_can_reach_critical():
    """有實際 Y 殘差證據（map_health 低）＝X→Y 關係真斷 → 可達 critical、計入 KPI、confidence 高。"""
    d = quality_incident_decision({"y_map_health": 0.3, "yhat_drift_z": 5.0})
    assert d["severity"] == "critical" and d["count_in_critical_kpi"] is True
    assert d["health"] == 0.3 and d["confidence"] == 1.0


def test_real_y_mid_and_high_health_grades():
    """有實際 Y：map_health 0.5→warning、0.7→info（severity 由品質側證據定，不借 X confidence/A14）。"""
    assert quality_incident_decision({"y_map_health": 0.5})["severity"] == "warning"
    assert quality_incident_decision({"y_map_health": 0.75})["severity"] == "info"


def test_yhat_only_never_critical_even_at_extreme_z():
    """**marquee（A15）**：無實際 Y（map_health None）＝純 Ŷ 外推 → 即使 z 極大也**絕不 critical**（上限 warning）、
    不計 critical KPI、confidence 低。無此上限＝零 Y 證據灌 critical 污染 KPI＝測試失敗。"""
    for z in (_ZREF, 2 * _ZREF, 50.0, 1e6):
        d = quality_incident_decision({"y_map_health": None, "yhat_drift_z": z})
        assert d["severity"] != "critical", f"純 Ŷ z={z} 不該 critical"
        assert d["count_in_critical_kpi"] is False and d["confidence"] == 0.4


def test_yhat_only_health_uses_explainable_zref_not_magic_9():
    """A15 去 magic 9：純 Ŷ health 用可解釋 z_ref——z=z_ref→0.5、z=2·z_ref→0（非硬編 /9）。"""
    assert quality_incident_decision({"y_map_health": None, "yhat_drift_z": _ZREF})["health"] == 0.5
    assert quality_incident_decision({"y_map_health": None, "yhat_drift_z": 2 * _ZREF})["health"] == 0.0
    # 小 z（< z_ref）→ info、health 高
    d = quality_incident_decision({"y_map_health": None, "yhat_drift_z": 1.0})
    assert d["severity"] == "info" and d["health"] > 0.8


def test_yhat_only_at_threshold_is_warning_not_info():
    """z 達門檻 z_ref → warning（過門檻才告警）；剛好 z_ref 不再是 info。"""
    assert quality_incident_decision({"y_map_health": None, "yhat_drift_z": _ZREF})["severity"] == "warning"
