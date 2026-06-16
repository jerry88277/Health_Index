"""P2 導入效益（ROI）估算（生產處長：採購決策依據）。

確定性、config 驅動。**誠實標（Rule 12）**：效益是**情境假設**下的估算，非實測——所有假設明列於回傳的
``assumptions``，數字僅供決策參考，不可當已實現損益。真實 ROI 需上線後以實際避免的非計畫停車回填。
"""

from __future__ import annotations


def estimate_roi(
    incidents: list[dict],
    *,
    avg_loss_per_unplanned_stop: float,
    prevented_fraction: float = 0.5,
    avg_early_warning_hours: float = 4.0,
) -> dict:
    """由已關閉/嚴重事件數，在明列假設下估「避免的非計畫停車」與金額。

    Args:
        incidents: 事件清單（events.IncidentStore.list()）。
        avg_loss_per_unplanned_stop: 一次非計畫停車的平均損失（幣別由呼叫端定）。
        prevented_fraction: 假設「critical 事件中，因提早預警而**真正避免**停車」的比例（保守預設 0.5）。
        avg_early_warning_hours: 假設平均提早預警時數（僅作呈現，不進金額）。

    Returns:
        dict：n_critical / assumed_prevented_stops / est_savings + **assumptions**（透明）。
    """
    n_critical = sum(1 for i in incidents if i.get("severity") == "critical")
    pf = float(max(0.0, min(1.0, prevented_fraction)))
    prevented = n_critical * pf
    savings = prevented * float(avg_loss_per_unplanned_stop)
    return {
        "n_critical_events": n_critical,
        "assumed_prevented_stops": round(prevented, 1),
        "est_savings": round(savings, 0),
        "avg_early_warning_hours": float(avg_early_warning_hours),
        "assumptions": {
            "avg_loss_per_unplanned_stop": float(avg_loss_per_unplanned_stop),
            "prevented_fraction": pf,
            "note": "估算值（情境假設），非實測損益；上線後以實際避免之停車回填校正。",
        },
    }
