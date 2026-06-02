"""後端 API WHY 測試（FastAPI TestClient）。

WHY：API 是判斷鏈的薄封裝。marquee＝**判斷鏈經 HTTP 端到端仍能區分 drift vs golden/clean
並告警**（與直接呼叫核心一致），且 re-entry 經 API 正確標記。若 API 把鏈接錯或回傳格式壞掉，
這些測試必須失敗。
"""

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


def test_datasets_lists_synthetic():
    r = client.get("/datasets")
    assert r.status_code == 200
    ids = [d["id"] for d in r.json()]
    assert "synthetic" in ids


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
