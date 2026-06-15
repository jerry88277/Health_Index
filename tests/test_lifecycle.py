"""G4 模型生命週期 WHY 測試（Rule 9）。

WHY：單一產品一個模型；製程刻意變更或基準老化後須重建。模型庫須能存取 per-product 現役模型；時效評估
須在「近期確認-正常資料被現役模型持續判不健康」時**建議重建**（需人決，不自動），否則基準與現況脫節而無人知。
"""

import numpy as np
import pytest

from health_index.adapters import registry as ds_registry
from health_index.deploy.bundle import build_bundle
from health_index.deploy.lifecycle import (
    ModelRegistry,
    assess_model_currency,
    rebuild_model,
)
from health_index.health import HealthIndex


def _golden(seed=5, ds=1.2):
    d, gt = ds_registry.build("synthetic", seed=seed, drift_strength=ds)
    cols = list(gt.x_columns)
    Xg = d.frame.loc[np.asarray(gt.golden_mask), cols].to_numpy()
    Xdrift = d.frame.loc[np.asarray(gt.drift_mask), cols].to_numpy()
    return cols, Xg, Xdrift


def test_registry_per_product_crud(tmp_path):
    """WHY：模型庫存取 per-product 現役模型；無模型時 fail-loud。"""
    reg = ModelRegistry(str(tmp_path))
    cols, Xg, _ = _golden()
    assert reg.list_models() == [] and not reg.has_model("A")
    b = build_bundle("A", HealthIndex().fit(Xg), cols, golden=Xg, created_at="t")
    reg.save_model(b)
    assert reg.has_model("A") and reg.list_models() == ["A"]
    loaded = reg.load_model("A")  # verify=True 指紋
    assert loaded.product == "A"
    with pytest.raises(FileNotFoundError, match="B"):
        reg.load_model("B")


def test_currency_current_on_fresh_golden(tmp_path):
    """WHY：現役模型對近期確認-正常 golden 判健康 → recommendation=CURRENT（基準仍貼合）。"""
    cols, Xg, _ = _golden()
    b = build_bundle("A", HealthIndex().fit(Xg[:150]), cols, golden=Xg[:150], created_at="t")
    rep = assess_model_currency(b, Xg[150:], window=40)  # 後半 golden＝近期正常
    assert rep.recommendation == "CURRENT" and rep.recent_alarm_rate <= 0.3


def test_currency_recommends_rebuild_when_baseline_stale(tmp_path):
    """marquee：餵入「現場宣稱正常」但其實已偏移的資料（用 drift 段模擬基準與現況不符）→ 告警率高
    → REBUILD_RECOMMENDED（需人決）。當評估對脫節基準仍說 CURRENT 時失敗。"""
    cols, Xg, Xdrift = _golden()
    b = build_bundle("A", HealthIndex().fit(Xg), cols, golden=Xg, created_at="t")
    rep = assess_model_currency(b, Xdrift, window=40)  # 近期資料已與基準不符
    assert rep.recommendation == "REBUILD_RECOMMENDED" and rep.recent_alarm_rate > 0.3


def test_rebuild_replaces_active_model(tmp_path):
    """WHY：重建以新 golden 替換現役模型（製程刻意變更後）；替換後載入為新基準。"""
    reg = ModelRegistry(str(tmp_path))
    cols, Xg, Xdrift = _golden()
    reg.save_model(build_bundle("A", HealthIndex().fit(Xg), cols, golden=Xg, created_at="t1"))
    # 製程刻意變更 → 以新操作點 golden 重建
    new_golden = Xdrift  # 模擬新配方成為新正常
    nb = rebuild_model(reg, "A", new_golden, cols, created_at="t2")
    assert nb.created_at == "t2"
    reloaded = reg.load_model("A")
    assert reloaded.created_at == "t2"  # 現役模型已替換為新基準
    # 新基準對新操作點判健康（重建成功貼合新正常）
    assert reloaded.health.health_index(new_golden[:60]) > reloaded.config.hi_alarm_threshold


def test_currency_short_data_is_honest(tmp_path):
    """WHY（誠實）：近期資料不足一窗 → 不假裝評估，回 CURRENT 並說明資料不足。"""
    cols, Xg, _ = _golden()
    b = build_bundle("A", HealthIndex().fit(Xg), cols, golden=Xg, created_at="t")
    rep = assess_model_currency(b, Xg[:10], window=60)
    assert "不足" in rep.reason
