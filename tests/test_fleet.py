"""#4 多產線健康總覽（北極星）WHY 測試（Rule 9）。

marquee WHY：北極星＝一屏看全部產線健康 → 點某線就地展開三部分（線上即時記錄／告警歷史／
模型建立資訊），且告警歷史能下鑽到**偏移的 X 參數或 Y 量測**。測試鎖住：
(a) 總覽逐線健康燈忠實反映 assets_overview（綠健康/紅告警/待建模）；
(b) 點線→三部分都由**該線**資料組出、不串到別線（line-scoped）；
(c) 告警下鑽到肇因 top_cause（哪個參數/量測偏移）——這正是本畫面存在的理由，
    喪失下鑽（只顯示有告警、不指名肇因）的測試是錯的；
(d) 即時記錄忠實反映鑑別：drift 段健康低於 golden 段、產生告警（接錯不上色/接錯 y 會被抓）。
方案 B（使用者定調）：一線＝一既有監控點(process/dataset)，per-line 健康沿用既有 lamp、
即時記錄用 score_timeline 離線逐窗。UI 視覺/點擊未在本環境渲染（NOT VERIFIED-visual）。
"""

from frontend import fleet as flt
from health_index.deploy import demo
from health_index.deploy.events import IncidentStore

_AT = "2026-07-06T10:00:00+08:00"


def _reg(tmp_path):
    return str(tmp_path / "registry.json"), str(tmp_path), str(tmp_path / "inc.json")


def _built_line(tmp_path, name="蒸餾A", area="常壓"):
    reg, md, inc = _reg(tmp_path)
    p = demo.create_process(reg, display_name=name, dataset="synthetic", at=_AT, area=area)
    demo.build_model_for_process(reg, md, p["id"], golden=(0, 300), window=60, at=_AT)
    return reg, md, inc, p["id"]


def test_fleet_overview_reflects_per_line_health(tmp_path):
    # WHY(a)：總覽逐線燈必須來自 assets_overview 的真實 status/version，不杜撰。
    reg, md, inc, pid = _built_line(tmp_path)
    ov = flt.fleet_overview(reg, md, inc, window=60)
    a = next(x for x in ov["assets"] if x["process_id"] == pid)
    assert a["status"] in ("healthy", "alarm") and a["version"] == 1
    assert ov["plant_status"] in ("healthy", "alarm")


def test_placeholder_line_has_no_fabricated_health(tmp_path):
    # WHY：待建模的線 health=None、realtime 標 unavailable，誠實不假裝正常。
    reg, md, inc = _reg(tmp_path)
    p = demo.create_process(reg, display_name="待建A", dataset="synthetic", at=_AT)
    ov = flt.fleet_overview(reg, md, inc, window=60)
    a = ov["assets"][0]
    assert a["status"] == "placeholder" and a["health"] is None
    d = flt.line_detail_data(reg, md, inc, p["id"], overview=ov, window=60)
    assert "unavailable" in d["realtime"]


def test_line_detail_is_line_scoped(tmp_path):
    # WHY(b)：三部分都綁該線——別線的告警/歷史不得混入。
    reg, md, inc, pidA = _built_line(tmp_path, name="A線", area="區1")
    pB = demo.create_process(reg, display_name="B線", dataset="synthetic", at=_AT, area="區2")
    demo.build_model_for_process(reg, md, pB["id"], golden=(0, 300), window=60, at=_AT)
    IncidentStore(inc).open_incident(product=pidA, window=[0, 60], health=0.4, confidence=0.9, top_cause="x03")
    IncidentStore(inc).open_incident(product=pB["id"], window=[0, 60], health=0.4, confidence=0.9, top_cause="x07")
    d = flt.line_detail_data(reg, md, inc, pidA, window=60)
    assert d["model_info"]["process"]["display_name"] == "A線"
    assert d["alarms"] and all(it["product"] == pidA for it in d["alarms"])  # 只 A 線的告警
    assert all(it["top_cause"] != "x07" for it in d["alarms"])               # B 線肇因不混入


def test_alarm_history_drills_to_offending_param(tmp_path):
    # WHY(c)：告警歷史必須指名偏移的 X 參數/Y 量測（top_cause）——喪失下鑽即失去本畫面理由。
    reg, md, inc, pid = _built_line(tmp_path)
    IncidentStore(inc).open_incident(product=pid, window=[120, 180], health=0.35,
                                     confidence=0.92, top_cause="x08")
    d = flt.line_detail_data(reg, md, inc, pid, window=60)
    top = [it["top_cause"] for it in d["alarms"]]
    assert "x08" in top  # 下鑽肇因保留


def test_realtime_reflects_health_discrimination(tmp_path):
    # WHY(d)：即時記錄逐窗健康須真反映鑑別——drift 段健康 < golden 段、且有告警窗。
    reg, md, inc, pid = _built_line(tmp_path)
    d = flt.line_detail_data(reg, md, inc, pid, window=60)
    rt = d["realtime"]
    assert "unavailable" not in rt and rt["points"]
    golden = [p["health_index"] for p in rt["points"] if p["region"] == "golden"]
    drift = [p["health_index"] for p in rt["points"] if p["region"] == "drift"]
    assert golden and drift and min(golden) > max(drift)   # golden 全高於 drift（鑑別）
    assert rt["n_alarms"] >= 1


def test_realtime_figure_colors_by_alarm(tmp_path):
    # WHY(d 續)：即時記錄圖須依 persisted_alarm 上色（紅告警/綠健康），接錯上色喪失鑑別。
    reg, md, inc, pid = _built_line(tmp_path)
    rt = flt.line_detail_data(reg, md, inc, pid, window=60)["realtime"]
    fig = flt.realtime_figure(rt)
    assert len(fig.data) >= 1
    marker = fig.data[0].marker.color
    pts = rt["points"]
    assert any(c == flt._BAD for c, p in zip(marker, pts) if p["persisted_alarm"])
    assert any(c == flt._OK for c, p in zip(marker, pts) if not p["persisted_alarm"])


def test_layout_builds_with_expected_ids():
    # WHY：fleet 殼可組建且含三部分容器/選線 store（callback ID 對齊錯會在組建時炸）。
    ids = _collect_ids(flt.layout())
    assert {"fleet-metrics", "fleet-line", "fleet-detail"} <= ids


def test_mounted_in_demo_app():
    # WHY：掛進 demo_app 後整個 app layout 可組建且有 scr-fleet 屏與 nav-fleet 入口。
    from frontend import demo_app
    ids = _collect_ids(demo_app.app.layout)
    assert "scr-fleet" in ids and "nav-fleet" in ids


def _collect_ids(component) -> set:
    ids = set()
    if isinstance(component, (list, tuple)):  # layout() 回傳 list
        for c in component:
            ids |= _collect_ids(c)
        return ids
    cid = getattr(component, "id", None)
    if isinstance(cid, str):
        ids.add(cid)
    children = getattr(component, "children", None)
    if isinstance(children, (list, tuple)):
        for c in children:
            ids |= _collect_ids(c)
    elif children is not None and hasattr(children, "children"):
        ids |= _collect_ids(children)
    return ids
