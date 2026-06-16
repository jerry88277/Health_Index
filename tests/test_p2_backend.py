"""P2 後端 WHY 測試（Rule 9）：全廠視圖 / 匯出 / ROI——處長決策與稽核所需。"""

from health_index.deploy import demo
from health_index.deploy.events import IncidentStore
from health_index.deploy.roi import estimate_roi


def test_plant_overview_aggregates_assets(tmp_path):
    """全廠視圖：列各裝置健康燈 + 彙總全廠總燈；提供 incidents_path 時附各裝置 active 事件數。"""
    demo.build_and_save_model("synthetic", models_dir=str(tmp_path), created_at="t", seed=5, drift_strength=1.2)
    inc = str(tmp_path / "inc.json")
    IncidentStore(inc).open_incident(product="synthetic", window=[0, 60], health=0.4, confidence=0.9,
                                     top_cause="x1", detected_at="2026-06-16T10:00:00+08:00")
    ov = demo.plant_overview(str(tmp_path), incidents_path=inc, window=60)
    assert ov["n_assets"] == 1 and ov["plant_status"] in {"healthy", "alarm"}
    assert ov["assets"][0]["product"] == "synthetic"
    assert ov["assets"][0]["active_incidents"] == 1  # 未結事件數附上


def test_plant_hierarchy_groups_by_config(tmp_path):
    """廠區階層（處長）：無 config → 未分區；有 plant.json(product→區域) → 依區域分組。"""
    import json as _j

    demo.build_and_save_model("synthetic", models_dir=str(tmp_path), created_at="t", seed=5, drift_strength=1.2)
    h0 = demo.plant_hierarchy(str(tmp_path))
    assert h0["configured"] is False and h0["areas"][0]["area"] == "未分區"
    _j.dump({"synthetic": "常壓蒸餾"}, open(str(tmp_path / "plant.json"), "w", encoding="utf-8"))
    h1 = demo.plant_hierarchy(str(tmp_path))
    assert h1["configured"] is True and any(a["area"] == "常壓蒸餾" for a in h1["areas"])


def test_incidents_to_csv_has_header_and_rows():
    inc = [{"id": "INC-0001", "product": "A", "detected_at": "t", "severity": "critical", "status": "closed",
            "health": 0.4, "confidence": 0.9, "top_cause": "T1", "mttr_sec": 1800.0, "close_note": "ok"}]
    csv = demo.incidents_to_csv(inc)
    assert "id,product,detected_at" in csv and "INC-0001" in csv and "1800.0" in csv


def test_timeline_to_csv_has_header():
    pts = [{"ts": "2026-06-16T10:00:00", "start": 0, "end": 60, "region": "golden", "health_index": 0.95,
            "confidence": 0.93, "spe_mean": 0.1, "t2_mean": 1.0, "gsi_mean": 1.0, "raw_alarm": False,
            "persisted_alarm": False}]
    csv = demo.timeline_to_csv(pts)
    assert "ts,start,end,region,health_index" in csv and "golden" in csv


def test_ingest_incidents_and_event_overview(tmp_path):
    """增量5：評分→persisted alarm 開成事件（防重複）；event_overview 給清單+stats(MTTR)+ROI。"""
    m = demo.build_and_save_model("synthetic", models_dir=str(tmp_path), created_at="t", seed=5, drift_strength=1.2)
    store = str(tmp_path / "inc.json")
    r = demo.ingest_incidents(m["bundle_path"], "synthetic", store, window=60, seed=5, drift_strength=1.2)
    assert r["opened"] is True and r["incident_id"]
    demo.ingest_incidents(m["bundle_path"], "synthetic", store, window=60, seed=5, drift_strength=1.2)  # 再掃
    ov = demo.event_overview(store)
    assert ov["stats"]["active"] == 1            # 同裝置防重複，仍只 1 件 active
    assert len(ov["incidents"]) == 1 and "roi" in ov and "stats" in ov


def test_estimate_roi_is_assumption_driven():
    """ROI＝情境假設估算：savings = n_critical × prevented_fraction × loss；assumptions 必透明（誠實標）。"""
    inc = [{"severity": "critical"}, {"severity": "critical"}, {"severity": "warning"}]
    r = estimate_roi(inc, avg_loss_per_unplanned_stop=1_000_000, prevented_fraction=0.5)
    assert r["n_critical_events"] == 2
    assert r["assumed_prevented_stops"] == 1.0 and r["est_savings"] == 1_000_000
    assert "assumptions" in r and r["assumptions"]["prevented_fraction"] == 0.5
