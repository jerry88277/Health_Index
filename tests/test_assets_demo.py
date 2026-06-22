"""增量7-B WHY 測試：registry orchestration（建製程→建模→總覽三態→更換→刪除→歷史）。

WHY：製程/模型解耦後，總覽必須能同時容納 placeholder 與已監控、且 placeholder 不污染全廠健康燈語意；
「更換模型」必須單調升版且 current 指新版；軟刪製程必須完全隱藏並關閉孤兒事件。
"""

import os

from health_index.adapters import registry
from health_index.deploy import catalog, demo
from health_index.deploy.assets import AssetStore
from health_index.deploy.events import IncidentStore

_AT = "2026-06-17T10:00:00+08:00"


def _reg(tmp_path):
    return str(tmp_path / "registry.json")


def test_catalog_covers_every_registered_dataset():
    """item3：每個已註冊資料集都要有導引說明（title/blurb 非空、window>0）——否則使用者點到會無說明。"""
    for name in registry.available():
        d = catalog.describe(name)
        assert d["title"] and len(d["blurb"]) > 10 and d["default_window"] > 0, f"{name} 缺說明"


def test_dataset_preview_series_and_segments():
    """golden 選擇視覺化：preview 給降採樣偏離度時間線 + campaign 分段(含 id) + 真值建議。"""
    pv = demo.dataset_preview("synthetic", max_points=200)
    assert pv["n_rows"] > 0 and len(pv["series_x"]) == len(pv["series_v"]) and len(pv["series_x"]) <= 200
    assert pv["segments"] and all("id" in s and "start" in s for s in pv["segments"])
    assert pv["golden_suggested"] and pv["golden_suggested"][0] < pv["golden_suggested"][1]


def test_golden_arg_from_spec_forms():
    """spec → build 引數：auto/連續/勾選 三形式（勾選→正確 bool mask）。"""
    import numpy as np
    assert demo.golden_arg_from_spec("synthetic", "auto") == "auto"
    assert demo.golden_arg_from_spec("synthetic", {"range": [0, 300]}) == (0, 300)
    assert demo.golden_arg_from_spec("synthetic", [0, 300]) == (0, 300)
    mask = demo.golden_arg_from_spec("synthetic", {"segments": [0]})
    assert isinstance(mask, np.ndarray) and mask.dtype == bool and mask.any()


def test_resolve_golden_runs_segments_match_bounds():
    """勾選 campaign → runs 對齊該段邊界；auto → 非空（變點切段）。"""
    pv = demo.dataset_preview("synthetic")
    seg0 = pv["segments"][0]
    r = demo.resolve_golden_runs("synthetic", {"segments": [seg0["id"]]})
    assert r["runs"] and r["runs"][0] == [seg0["start"], seg0["end"]] and r["n_selected"] > 0
    assert demo.resolve_golden_runs("synthetic", "auto")["n_selected"] > 0


def test_build_model_accepts_segments_and_auto_spec(tmp_path):
    """更換模型可用勾選/自動 golden（接出 mask/auto）——建模成功且登錄版本。"""
    reg, md = _reg(tmp_path), str(tmp_path)
    p = demo.create_process(reg, display_name="A", dataset="synthetic", at=_AT)
    pv = demo.dataset_preview("synthetic")
    seg0 = pv["segments"][0]
    r = demo.build_model_for_process(reg, md, p["id"], golden={"segments": [seg0["id"]]}, window=60, at=_AT)
    assert r["saved"] is True and r["model"]["version"] == 1


def test_subset_low_recall_warns_not_blocks(tmp_path):
    """增量9（Rule 7）：監控子集丟掉帶訊號參數 → recall 低但 FPR 合格 → **允許上線 + 警告**，非硬擋。

    WHY：FPR 過高＝誤報→操作員警報疲勞→危險，硬擋；recall 低＝漏抓部分 drift，是使用者「少監控幾個參數」
    的知情靈敏度取捨，警告不擋。兩準則風險不同、不平均成一個硬閘（Rule 7）。
    """
    reg, md = _reg(tmp_path), str(tmp_path)
    p = demo.create_process(reg, display_name="子集線", dataset="synthetic", at=_AT)
    feats = [f"x0{i}" for i in range(8)]  # 丟 x08/x09（synthetic drift 訊號所在）→ recall 掉、FPR 仍 0
    r = demo.build_model_for_process(reg, md, p["id"], golden=(0, 300), window=60, at=_AT, features=feats)
    assert r["saved"] is True                       # FPR 合格 → 仍存檔（非硬擋）
    assert r["acceptance"]["fpr_ok"] is True and r["acceptance"]["recall_ok"] is False  # recall 低 → 前端警告
    from health_index.deploy.bundle import load
    assert list(load(os.path.join(md, r["model"]["path"])).x_columns) == feats  # 子集確實落地


def test_create_build_overview_healthy(tmp_path):
    reg, md = _reg(tmp_path), str(tmp_path)
    p = demo.create_process(reg, display_name="蒸餾A", dataset="synthetic", at=_AT, area="常壓")
    r = demo.build_model_for_process(reg, md, p["id"], golden=(0, 600), window=60, at=_AT)
    assert r["saved"] is True and r["model"]["version"] == 1
    assert os.path.exists(os.path.join(md, f"{p['id']}__v1.joblib"))  # 版本化 bundle 落地
    ov = demo.assets_overview(reg, md, window=60)
    a = next(x for x in ov["assets"] if x["process_id"] == p["id"])
    assert a["status"] in ("healthy", "alarm") and a["version"] == 1
    assert ov["configured"] is True and any(ar["area"] == "常壓" for ar in ov["areas"])


def test_placeholder_not_in_green_red_denominator(tmp_path):
    """placeholder（待建模）不進綠紅分母——不污染全廠健康語意（紅隊一致）。"""
    reg, md = _reg(tmp_path), str(tmp_path)
    demo.create_process(reg, display_name="待建A", dataset="synthetic", at=_AT)
    ov = demo.assets_overview(reg, md, window=60)
    a = ov["assets"][0]
    assert a["status"] == "placeholder" and a["version"] is None
    assert ov["n_placeholder"] == 1 and ov["n_monitored"] == 0 and ov["plant_status"] == "empty"


def test_swap_model_bumps_version_and_current(tmp_path):
    """更換模型＝重建基準：version 單調+1、current 指新版、舊版成歷史版本。"""
    reg, md = _reg(tmp_path), str(tmp_path)
    p = demo.create_process(reg, display_name="A", dataset="synthetic", at=_AT)
    demo.build_model_for_process(reg, md, p["id"], golden=(0, 600), window=60, at=_AT)
    r2 = demo.build_model_for_process(reg, md, p["id"], golden=(0, 700), window=60, at=_AT)
    assert r2["saved"] and r2["model"]["version"] == 2
    assert AssetStore(reg).get_process(p["id"])["current_model_id"] == r2["model"]["id"]


def test_delete_process_hidden_and_closes_orphan(tmp_path):
    """軟刪製程：總覽完全隱藏 + 孤兒 active 事件強制關閉（解 KPI 虛報）。"""
    reg, md, inc = _reg(tmp_path), str(tmp_path), str(tmp_path / "inc.json")
    p = demo.create_process(reg, display_name="A", dataset="synthetic", at=_AT)
    demo.build_model_for_process(reg, md, p["id"], golden=(0, 600), window=60, at=_AT)
    IncidentStore(inc).open_incident(product=p["id"], window=[0, 60], health=0.4, confidence=0.9, top_cause="x1")
    demo.delete_process(reg, p["id"], reason="停用", at=_AT, incidents_path=inc)
    ov = demo.assets_overview(reg, md, incidents_path=inc, window=60)
    assert all(a["process_id"] != p["id"] for a in ov["assets"])  # 完全隱藏
    assert IncidentStore(inc).stats()["active"] == 0              # 孤兒已關


def test_model_history_merges_versions_acceptance_incidents(tmp_path):
    """歷史頁：版本清單(含 acceptance 快照) + audit log + 服役期 incidents（紅隊 RT-3）。"""
    reg, md, inc = _reg(tmp_path), str(tmp_path), str(tmp_path / "inc.json")
    p = demo.create_process(reg, display_name="A", dataset="synthetic", at=_AT)
    demo.build_model_for_process(reg, md, p["id"], golden=(0, 600), window=60, at=_AT)
    IncidentStore(inc).open_incident(product=p["id"], window=[0, 60], health=0.4, confidence=0.9, top_cause="x1")
    h = demo.model_history(reg, p["id"], incidents_path=inc)
    assert len(h["models"]) == 1 and h["models"][0].get("acceptance") is not None
    assert any(a["action"] == "build_model" for a in h["audit"]) and len(h["incidents"]) == 1
