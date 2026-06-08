"""後端 API WHY 測試（FastAPI TestClient）。

WHY：API 是判斷鏈的薄封裝。marquee＝**判斷鏈經 HTTP 端到端仍能區分 drift vs golden/clean
並告警**（與直接呼叫核心一致），且 re-entry 經 API 正確標記。若 API 把鏈接錯或回傳格式壞掉，
這些測試必須失敗。
"""

import os

import pytest

pytest.importorskip("fastapi")  # 他機未裝 [api] 依賴時跳過，不讓 collection 失敗
pytest.importorskip("httpx")    # TestClient 間接依賴 httpx（紅隊 B：守門缺口）

from fastapi.testclient import TestClient  # noqa: E402

from health_index.api.server import app  # noqa: E402

client = TestClient(app)


def test_health_endpoint():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_datasets_lists_synthetic_and_tep():
    r = client.get("/datasets")
    assert r.status_code == 200
    ids = [d["id"] for d in r.json()]
    assert "synthetic" in ids and "tep" in ids


_TEP_DATA = os.path.join("data", "tep", "m1d00.mat")


@pytest.mark.skipif(not os.path.exists(_TEP_DATA), reason="TEP .mat 未下載（data/tep/）")
def test_tep_through_api_marquee():
    # TEP 經 HTTP 端到端：golden/乾淨回歸健康、drift 回歸告警（X 健康抓到注入隱性飄移），re-entry 正確
    r = client.post("/analyze", json={"dataset_id": "tep", "seed": 0, "drift_strength": 1.0})
    assert r.status_code == 200
    data = r.json()
    camps = {c["campaign_id"]: c for c in data["campaigns"]}
    assert camps[0]["is_alarm"] is False                          # golden 健康
    assert camps[2]["is_alarm"] is False                          # 乾淨換線回歸健康
    assert camps[4]["is_alarm"] is True                           # drift 回歸告警
    assert camps[4]["health_index"] < camps[2]["health_index"] - 0.2
    assert data["reentry_campaigns"] == [2, 4]
    assert len(data["variables"]) == 22                            # XMEAS1-22


@pytest.mark.skipif(not os.path.exists(_TEP_DATA), reason="TEP .mat 未下載（data/tep/）")
def test_tep_yhealth_flags_product_change_not_injected_drift():
    # Y-MSPC（Y 分布健康）：換產品 B/C(G/H 比例變)被旗標、注入 drift(Y 分布不變)不旗標——與軟測量互補
    d = client.post("/yhealth", json={"dataset_id": "tep", "seed": 0, "drift_strength": 1.0}).json()
    assert d["available"] is True and d["quality_vars"] == ["yq_G", "yq_H"]
    camps = {c["campaign_id"]: c for c in d["campaigns"]}
    assert camps[1]["y_flagged"] is True and camps[3]["y_flagged"] is True   # B, C 產品分布變
    assert camps[0]["y_flagged"] is False                                     # golden Y 健康
    assert camps[4]["y_flagged"] is False                                     # drift：Y 分布不變(只 X→Y 斷)


def test_yhealth_synthetic_unavailable():
    # 純量品質資料集 → Y 分布健康不適用（available=False，不誤導）
    d = client.post("/yhealth", json={"dataset_id": "synthetic", "seed": 5}).json()
    assert d["available"] is False and d["campaigns"] == []


@pytest.mark.skipif(not os.path.exists(_TEP_DATA), reason="TEP .mat 未下載（data/tep/）")
def test_tep_softsensor_mapping_drift():
    # Y 健康（軟測量）：drift 段 X→Y 映射被破壞 → Ŷ 偏離實際 Y（量測層抓到）
    import numpy as np

    d = client.post("/softsensor", json={"dataset_id": "tep", "seed": 0, "drift_strength": 1.0}).json()
    span = {s["campaign_id"]: s for s in d["campaigns"]}
    yhat = np.array(d["yhat"])
    ya = np.array([np.nan if v is None else v for v in d["y_actual"]])

    def mae(cid):
        s, e = span[cid]["start"], span[cid]["end"]
        obs = np.isfinite(ya[s:e])
        return float(np.abs(yhat[s:e][obs] - ya[s:e][obs]).mean()) if obs.any() else 0.0

    assert mae(4) > mae(0)              # drift 回歸的映射誤差 > golden（軟測量 Y 健康抓到）


def test_analyze_chain_through_http():
    # API-level marquee：判斷鏈經 HTTP 仍區分 drift vs golden/clean + 告警
    r = client.post("/analyze", json={"dataset_id": "synthetic", "seed": 5, "drift_strength": 1.2})
    assert r.status_code == 200
    data = r.json()
    camps = {c["campaign_id"]: c for c in data["campaigns"]}
    assert set(camps) == {0, 1, 2, 3, 4}
    # golden(0) 健康不告警；drift(4) 低分告警
    assert camps[0]["health_index"] > 0.8 and camps[0]["is_alarm"] is False
    assert camps[4]["health_index"] < camps[0]["health_index"] - 0.2
    assert camps[4]["is_alarm"] is True
    # re-entry 標記正確
    assert data["reentry_campaigns"] == [2, 4]
    assert camps[4]["is_reentry"] is True and camps[0]["is_reentry"] is False
    # 子分數齊備
    assert set(camps[4]["subscores"]) == {"L1", "L2", "L4"}


def test_analyze_unknown_dataset_404():
    r = client.post("/analyze", json={"dataset_id": "nope"})
    assert r.status_code == 404


def test_analyze_validation_error_422():
    # drift_strength 須 > 0（schema gt=0）→ 非法輸入回 422
    r = client.post("/analyze", json={"dataset_id": "synthetic", "drift_strength": -1.0})
    assert r.status_code == 422


def test_analyze_negative_seed_is_422_not_500():
    # WHY（紅隊 🔴）：負 seed 是非法輸入，應 422（schema ge=0），不可穿到 numpy 變未捕捉 500
    r = client.post("/analyze", json={"dataset_id": "synthetic", "seed": -5})
    assert r.status_code == 422


def test_analyze_deterministic():
    # WHY：偵測器確定性 → 同 request 兩次回傳完全相同（鎖 API 層決定性）
    body = {"dataset_id": "synthetic", "seed": 5, "drift_strength": 1.2}
    a = client.post("/analyze", json=body)
    b = client.post("/analyze", json=body)
    assert a.status_code == 200 and a.json() == b.json()


# --- B1：時間軸端點 + RBC 肇因 ---
_B1 = {"dataset_id": "synthetic", "seed": 5, "drift_strength": 1.2}


def test_timeline_shape_and_spans():
    r = client.post("/timeline", json=_B1)
    assert r.status_code == 200
    d = r.json()
    assert len(d["t2"]) == len(d["spe"]) == len(d["gsi"]) == 1500  # 5 campaigns × 300
    spans = {s["campaign_id"]: s for s in d["campaigns"]}
    assert set(spans) == {0, 1, 2, 3, 4}
    assert spans[0]["start"] == 0 and spans[4]["end"] == 1500 and spans[4]["grade"] == "A"


def test_timeline_spe_exceeds_limit_in_drift_not_golden():
    # WHY（時序鑑別）：逐樣本 SPE 在 drift campaign 大量越限、golden/乾淨回歸幾乎不越限 →
    # 時間軸忠實反映「何時」隱性飄移。若 timeline 把序列接錯/重算分歧，這裡會破。
    import numpy as np

    d = client.post("/timeline", json=_B1).json()
    spe = np.array(d["spe"])
    lim = d["spe_limit"]
    span = {s["campaign_id"]: s for s in d["campaigns"]}

    def rate(cid):
        s = span[cid]
        return (spe[s["start"] : s["end"]] > lim).mean()

    assert rate(4) > 0.5                       # drift A 大量越限
    assert rate(0) < 0.1 and rate(2) < 0.1     # golden / 乾淨回歸 幾乎不越限


def test_contribution_names_hidden_drift_vars_spc_blind():
    # marquee WHY（B1 核心，index 存在的理由）：drift campaign 的 top-RBC 變數，其單變數 3σ 越界率
    # 近 0 → RBC 點名了單變數 SPC 看不到的隱性飄移變數；且 drift RBC 強度遠大於 golden（非全 0 假綠）。
    d = client.post("/contribution", json=_B1).json()
    camps = {c["campaign_id"]: c for c in d["campaigns"]}
    c4 = camps[4]["top_variables"]
    assert all(v["spc_exceedance"] < 0.1 for v in c4)               # 隱性：單變數 SPC 盲
    assert c4[0]["rbc"] > 0.5                                       # 有實質肇因（非噪聲地板）
    assert c4[0]["rbc"] > camps[0]["top_variables"][0]["rbc"] * 3   # drift RBC 遠大於 golden
    assert camps[4]["is_reentry"] is True
    assert c4 == sorted(c4, key=lambda v: v["rbc"], reverse=True)   # RBC 降序排列


def test_timeline_thin_wrapper_matches_core():
    # WHY（薄封裝，Rule 3）：/timeline 的 SPE 與直接呼叫核心 MSPC 一致 → 零重算分歧。
    import numpy as np

    from health_index.adapters import synthetic as syn
    from health_index.health import HealthIndex

    ds, gt = syn.generate(seed=5, drift_strength=1.2)
    cols = list(ds.x_columns)
    hi = HealthIndex().fit(ds.frame.loc[gt.golden_mask, cols].to_numpy())
    spe_core = np.round(hi.mspc_.spe(ds.frame[cols].to_numpy()), 4)
    spe_api = np.array(client.post("/timeline", json=_B1).json()["spe"])
    assert np.allclose(spe_core, spe_api, atol=1e-4)


def test_timeline_contribution_deterministic():
    assert client.post("/timeline", json=_B1).json() == client.post("/timeline", json=_B1).json()
    assert client.post("/contribution", json=_B1).json() == client.post("/contribution", json=_B1).json()


def test_timeline_unknown_dataset_404():
    assert client.post("/timeline", json={"dataset_id": "nope"}).status_code == 404
    assert client.post("/contribution", json={"dataset_id": "nope"}).status_code == 404


def test_series_shape_and_spc_blind_on_drift():
    # marquee WHY（SPC 視圖）：/series 回傳逐樣本原始值 + golden 3σ 管制線；drift 段每個參數**幾乎都
    # 在 3σ 內**（單變數 SPC 看不到），但 /analyze 同 request 對 drift 告警 → 隱性飄移的核心示範。
    import numpy as np

    d = client.post("/series", json=_B1).json()
    assert len(d["variables"]) == 10
    assert all(len(d["series"][v]) == 1500 for v in d["variables"])
    span = {s["campaign_id"]: s for s in d["campaigns"]}
    s, e = span[4]["start"], span[4]["end"]                 # drift campaign
    M = np.array([d["series"][v][s:e] for v in d["variables"]]).T
    up = np.array([d["spc_upper"][v] for v in d["variables"]])
    lo = np.array([d["spc_lower"][v] for v in d["variables"]])
    any_exceed = ((M > up) | (M < lo)).any(axis=1).mean()
    assert any_exceed < 0.1                                 # 99% 樣本所有參數都在管制內＝SPC 盲
    # 對照：同 request /analyze 對 drift(4) 告警
    a = client.post("/analyze", json=_B1).json()
    assert {c["campaign_id"]: c for c in a["campaigns"]}[4]["is_alarm"] is True


def test_series_unknown_dataset_404():
    assert client.post("/series", json={"dataset_id": "nope"}).status_code == 404


def test_analyze_health_band_brackets_point():
    # WHY（融合分數不確定度）：bootstrap 信賴帶須夾住點估（lo ≤ HI ≤ hi）
    a = client.post("/analyze", json=_B1).json()
    for c in a["campaigns"]:
        assert c["health_lo"] <= c["health_index"] <= c["health_hi"]


def test_softsensor_yhat_deviates_from_y_in_drift():
    # marquee WHY（量測值偏移）：drift 段 X→Y 映射偏移 → |Ŷ−實際Y| 明顯大於 golden 段。
    import numpy as np

    d = client.post("/softsensor", json=_B1).json()
    assert len(d["yhat"]) == 1500 and len(d["band_half"]) == 1500
    span = {s["campaign_id"]: s for s in d["campaigns"]}
    yhat = np.array(d["yhat"])
    ya = np.array([np.nan if v is None else v for v in d["y_actual"]])

    def mae(cid):
        s, e = span[cid]["start"], span[cid]["end"]
        obs = np.isfinite(ya[s:e])
        return float(np.abs(yhat[s:e][obs] - ya[s:e][obs]).mean())

    assert mae(4) > mae(0) * 2          # drift 段預測誤差遠大於 golden（量測層飄移）
    assert d["band_kind"] in ("CP", "GPR_std")


def test_softsensor_unknown_dataset_404():
    assert client.post("/softsensor", json={"dataset_id": "nope"}).status_code == 404
