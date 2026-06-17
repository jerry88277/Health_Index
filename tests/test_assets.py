"""增量7 模型 registry WHY 測試（Rule 9）：製程/模型解耦的不變式與生命週期。

編碼紅隊揪出的不變式——這些測試在 registry 退回「檔名綁死/版本碰撞/孤兒事件/軟刪除刪檔」時必須失敗。
"""

import json

import pytest

from health_index.deploy.assets import AssetStore
from health_index.deploy.events import IncidentStore


def _store(tmp_path):
    return AssetStore(str(tmp_path / "registry.json"))


def test_create_process_is_placeholder(tmp_path):
    """建立製程＝placeholder：無現役模型、未刪、版本計數從 1 起。"""
    s = _store(tmp_path)
    p = s.create_process(display_name="合成製程 A", dataset="synthetic", by="王工")
    assert p["current_model_id"] is None and p["deleted"] is False and p["next_version"] == 1
    assert p["dataset"] == "synthetic" and p["display_name"] == "合成製程 A"
    assert s.list_processes() and s.list_processes()[0]["id"] == p["id"]
    # log 存取：建製程入稽核
    assert any(a["action"] == "create_process" and a["actor"] == "王工" for a in s.audit_log())


def test_dataset_must_be_registered(tmp_path):
    """dataset 必須 ∈ registry.available()（否則總覽會默默全紅）——不存在即 fail loud。"""
    s = _store(tmp_path)
    with pytest.raises(ValueError):
        s.create_process(display_name="X", dataset="不存在的資料集_xyz")


def test_build_sets_current_and_versions_monotonic(tmp_path):
    """record_build：首版 current 指它(build_model)；第二版 current 指新版(swap_model)；版本單調。"""
    s = _store(tmp_path)
    p = s.create_process(display_name="A", dataset="synthetic")
    m1 = s.record_build(p["id"], path="A__v1.joblib", dataset="synthetic", golden_range=[0, 600], fingerprint_hi=0.9)
    assert m1["version"] == 1 and s.get_process(p["id"])["current_model_id"] == m1["id"]
    assert s.current_model(p["id"])["id"] == m1["id"]
    m2 = s.record_build(p["id"], path="A__v2.joblib", dataset="synthetic", golden_range=[0, 700], fingerprint_hi=0.92)
    assert m2["version"] == 2 and s.get_process(p["id"])["current_model_id"] == m2["id"]
    acts = [a["action"] for a in s.audit_log(p["id"])]
    assert "build_model" in acts and "swap_model" in acts  # v1=build, v2=swap


def test_version_counter_no_collision_after_delete(tmp_path):
    """刪最高版後再建：version 由單調計數器給，不重用→不碰撞 id/path（紅隊 RT-1#2）。"""
    s = _store(tmp_path)
    p = s.create_process(display_name="A", dataset="synthetic")
    m1 = s.record_build(p["id"], path="A__v1.joblib", dataset="synthetic", golden_range=[0, 1], fingerprint_hi=0.9)
    m2 = s.record_build(p["id"], path="A__v2.joblib", dataset="synthetic", golden_range=[0, 1], fingerprint_hi=0.9)
    s.soft_delete_model(m2["id"])
    m3 = s.record_build(p["id"], path="A__v3.joblib", dataset="synthetic", golden_range=[0, 1], fingerprint_hi=0.9)
    assert m3["version"] == 3 and m3["id"] != m2["id"] and m3["path"] != m2["path"]


def test_soft_delete_current_model_falls_back(tmp_path):
    """軟刪現役模型→current 退回同製程最高版未刪；無則 null。current 永不指向已刪（不變式）。"""
    s = _store(tmp_path)
    p = s.create_process(display_name="A", dataset="synthetic")
    m1 = s.record_build(p["id"], path="A__v1.joblib", dataset="synthetic", golden_range=[0, 1], fingerprint_hi=0.9)
    m2 = s.record_build(p["id"], path="A__v2.joblib", dataset="synthetic", golden_range=[0, 1], fingerprint_hi=0.9)
    s.soft_delete_model(m2["id"], reason="過擬合")
    cur = s.get_process(p["id"])["current_model_id"]
    assert cur == m1["id"]  # 退回 v1
    s.soft_delete_model(m1["id"])
    assert s.get_process(p["id"])["current_model_id"] is None  # 全刪→無現役
    assert any(a["action"] == "delete_model" for a in s.audit_log(p["id"]))


def test_soft_delete_never_touches_bundle_file(tmp_path):
    """軟刪除絕不刪 .joblib（歷史頁要能重放；紅隊 RT-1#8）——store 只翻旗標，不碰檔案系統。"""
    bundle = tmp_path / "A__v1.joblib"
    bundle.write_text("dummy")
    s = _store(tmp_path)
    p = s.create_process(display_name="A", dataset="synthetic")
    m1 = s.record_build(p["id"], path="A__v1.joblib", dataset="synthetic", golden_range=[0, 1], fingerprint_hi=0.9)
    s.soft_delete_model(m1["id"])
    assert bundle.exists()  # 檔仍在


def test_deleted_hidden_but_in_history(tmp_path):
    """軟刪除製程：list_processes 預設不列（完全隱藏），但 history/include_deleted 仍可見（log存取）。"""
    s = _store(tmp_path)
    p = s.create_process(display_name="A", dataset="synthetic")
    s.record_build(p["id"], path="A__v1.joblib", dataset="synthetic", golden_range=[0, 1], fingerprint_hi=0.9)
    s.soft_delete_process(p["id"], reason="停用")
    assert all(x["id"] != p["id"] for x in s.list_processes())            # 總覽隱藏
    assert any(x["id"] == p["id"] for x in s.list_processes(include_deleted=True))
    hist = s.history(p["id"])
    assert hist["process"]["deleted"] is True and len(hist["models"]) == 1
    assert any(a["action"] == "delete_process" for a in hist["audit"])


def test_delete_process_closes_orphan_incidents(tmp_path):
    """軟刪製程強制關閉其 active incidents（解孤兒：否則虛報 open/MTTR/ROI；紅隊一致）。"""
    inc_path = str(tmp_path / "inc.json")
    store = IncidentStore(inc_path)
    s = _store(tmp_path)
    p = s.create_process(display_name="A", dataset="synthetic")
    s.record_build(p["id"], path="A__v1.joblib", dataset="synthetic", golden_range=[0, 1], fingerprint_hi=0.9)
    store.open_incident(product=p["id"], window=[0, 60], health=0.4, confidence=0.9, top_cause="x1")
    assert store.stats()["active"] == 1
    s.soft_delete_process(p["id"], reason="停用", incident_store=store)
    assert store.stats()["active"] == 0  # 孤兒已關
    closed = store.list(product=p["id"])[0]
    assert closed["status"] == "closed" and closed["close_reason"] == "process_deleted"


def test_restore_process(tmp_path):
    """還原製程（入口在歷史頁，呼應『完全隱藏只在歷史可見』）。"""
    s = _store(tmp_path)
    p = s.create_process(display_name="A", dataset="synthetic")
    s.soft_delete_process(p["id"], reason="誤刪")
    s.restore_process(p["id"])
    assert any(x["id"] == p["id"] for x in s.list_processes())
    assert any(a["action"] == "restore_process" for a in s.audit_log(p["id"]))


def test_id_slug_from_chinese_name_and_dedup(tmp_path):
    """id 由 display_name slug（中文落空→退回 dataset）+ 衝突去重；中文名不入路徑（紅隊 RT-1#9）。"""
    s = _store(tmp_path)
    p1 = s.create_process(display_name="反應器", dataset="synthetic")
    p2 = s.create_process(display_name="反應器", dataset="synthetic")  # 同名
    assert p1["id"] != p2["id"]  # 去重
    assert all(c.isalnum() or c in "-_" for c in p1["id"])  # ascii-safe（可入路徑）


def test_persists_across_instances(tmp_path):
    """持久化：新 AssetStore 實例讀同檔得同狀態（原子寫入後可重啟）。"""
    path = str(tmp_path / "registry.json")
    s1 = AssetStore(path)
    p = s1.create_process(display_name="A", dataset="synthetic")
    s1.record_build(p["id"], path="A__v1.joblib", dataset="synthetic", golden_range=[0, 1], fingerprint_hi=0.9)
    s2 = AssetStore(path)
    assert s2.get_process(p["id"])["current_model_id"] is not None
    assert json.load(open(path, encoding="utf-8"))["schema_version"] == 1


def test_acceptance_snapshot_in_history(tmp_path):
    """歷史頁每版含 acceptance 快照（工程師判 rollback 依據；紅隊 RT-3）。"""
    s = _store(tmp_path)
    p = s.create_process(display_name="A", dataset="synthetic")
    acc = {"passed": True, "holdout_golden_fpr": 0.02, "drift_recall": 0.8, "verdict": "通過"}
    s.record_build(p["id"], path="A__v1.joblib", dataset="synthetic", golden_range=[0, 1],
                   fingerprint_hi=0.9, acceptance=acc)
    m = s.history(p["id"])["models"][0]
    assert m["acceptance"]["passed"] is True and m["acceptance"]["holdout_golden_fpr"] == 0.02
