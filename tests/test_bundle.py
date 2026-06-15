"""G1 模型打包 WHY 測試（Rule 9）。

WHY：線上部署的第一塊地基＝把凍結模型存檔、之後重載評分。存檔/重載若**默默改變模型輸出**（版本漂移、
損毀），整條線上監測就建在沙上。指紋重放的存在理由＝重載時行為不一致就**拒載**（fail-loud），而非
靜默用壞模型。當 verify 對「輸出已變」仍放行時，本測試必須失敗。
"""

import numpy as np
import pytest

from health_index.adapters import registry
from health_index.deploy.bundle import (
    BundleIntegrityError,
    ModelBundle,
    build_bundle,
    load,
    save,
)
from health_index.health import HealthIndex


def _fit_golden(seed=1):
    ds, gt = registry.build("synthetic", seed=seed)
    cols = list(gt.x_columns)
    Xg = ds.frame.loc[np.asarray(gt.golden_mask), cols].to_numpy()
    return HealthIndex().fit(Xg), cols, Xg


def test_save_load_roundtrip_preserves_output(tmp_path):
    """marquee：存檔→重載後，模型對同一新窗的 health_index 與原模型逐位元一致（序列化不改行為）。"""
    hi, cols, Xg = _fit_golden()
    before = hi.health_index(Xg)
    b = build_bundle("A", hi, cols, golden=Xg, created_at="2026-06-15T10:00:00+08:00")
    p = save(b, str(tmp_path / "A.joblib"))
    b2 = load(p)  # verify=True
    assert b2.product == "A" and b2.x_columns == tuple(cols)
    assert np.isclose(b2.health.health_index(Xg), before, rtol=1e-9)


def test_verify_catches_drifted_output():
    """WHY（指紋重放的存在理由）：若重載的模型對指紋給出**不同**輸出（模擬版本漂移），verify 須
    BundleIntegrityError 拒載——不靜默用行為已變的模型。"""
    hi, cols, Xg = _fit_golden()
    b = build_bundle("A", hi, cols, golden=Xg, created_at="t")
    object.__setattr__(b, "fingerprint_hi", b.fingerprint_hi + 0.5)  # 模擬重載後輸出漂移
    with pytest.raises(BundleIntegrityError, match="指紋"):
        b.verify()


def test_verify_catches_subscore_drift():
    """WHY：即使融合 HI 偶然相符，任一層子分數漂移也須被抓（多層指紋，降低偽通過）。"""
    hi, cols, Xg = _fit_golden()
    b = build_bundle("A", hi, cols, golden=Xg, created_at="t")
    b.fingerprint_sub["L2"] = b.fingerprint_sub["L2"] - 0.3
    with pytest.raises(BundleIntegrityError, match="子分數"):
        b.verify()


def test_load_rejects_non_bundle(tmp_path):
    """WHY：載到非 ModelBundle 檔（誤檔/損毀）須 fail-loud，不回半殘物件。"""
    import joblib

    p = str(tmp_path / "bad.joblib")
    joblib.dump({"not": "a bundle"}, p)
    with pytest.raises(BundleIntegrityError, match="ModelBundle"):
        load(p)


def test_load_can_skip_verify(tmp_path):
    """WHY：verify=False 供診斷（明知漂移仍想載來檢視）；預設 True 才是安全路徑。"""
    hi, cols, Xg = _fit_golden()
    b = build_bundle("A", hi, cols, golden=Xg, created_at="t")
    b.fingerprint_hi += 0.5
    p = save(b, str(tmp_path / "A.joblib"))
    loaded = load(p, verify=False)  # 不重放 → 不拋
    assert isinstance(loaded, ModelBundle)
    with pytest.raises(BundleIntegrityError):
        load(p, verify=True)


def test_build_bundle_validates_golden():
    """WHY：空 golden 無法建指紋 → fail-loud（不產出無法重放驗證的 bundle）。"""
    hi, cols, _ = _fit_golden()
    with pytest.raises(ValueError, match="golden"):
        build_bundle("A", hi, cols, golden=np.empty((0, len(cols))), created_at="t")


def test_versions_captured():
    """WHY：建模環境版本須隨 bundle 存（指紋不符時供診斷根因）。"""
    hi, cols, Xg = _fit_golden()
    b = build_bundle("A", hi, cols, golden=Xg, created_at="t")
    assert {"python", "numpy", "sklearn", "joblib"} <= set(b.versions)
