"""線上模擬 demo orchestration WHY 測試（Rule 9）。

WHY：demo 四步（選資料→建模→確認→看健康指標）的邏輯核心須可獨立於 UI 驗證。marquee＝步驟4 時間線
在 demo 層仍體現三條 DoD（golden 健康/隱性飄移告警/乾淨回歸 vs 殘留飄移可分），且建模→存檔→重載→
評分的契約成立（指紋驗證）。當 demo 層接錯（region 標錯、bundle 路徑斷、golden 範圍錯）時失敗。
"""

import numpy as np
import pytest

from health_index.deploy import demo


def test_available_datasets_lists_public_sets():
    assert "synthetic" in demo.available_datasets()


def test_dataset_overview_shape_and_golden():
    ov = demo.dataset_overview("synthetic", seed=5, drift_strength=1.2)
    assert ov["n_rows"] == 1500 and ov["n_features"] == 10
    assert ov["golden_suggested"] == [0, 300]  # 第一個 A campaign
    assert len(ov["segments"]) == 5 and ov["has_labeled_drift"]


def test_build_save_load_model(tmp_path):
    m = demo.build_and_save_model(
        "synthetic", models_dir=str(tmp_path), created_at="2026-06-15T11:00+08:00", seed=5, drift_strength=1.2
    )
    assert m["golden_range"] == [0, 300] and m["n_golden"] == 300
    from health_index.deploy.bundle import load

    b = load(m["bundle_path"])  # verify=True 指紋通過
    assert b.product == "synthetic"


def test_build_with_auto_golden(tmp_path):
    """WHY：建模可用 golden='auto'（桶4b）——無 label 資料的挑選路徑經 demo 層接通。"""
    m = demo.build_and_save_model(
        "synthetic", golden="auto", models_dir=str(tmp_path), created_at="t", seed=5, drift_strength=1.2
    )
    assert m["golden_range"] is not None and m["n_golden"] > 0


def test_score_timeline_reflects_dod(tmp_path):
    """marquee：demo 層時間線——golden 健康、drift 告警、乾淨回歸不誤報且與 drift 明確分離。"""
    m = demo.build_and_save_model(
        "synthetic", models_dir=str(tmp_path), created_at="t", seed=5, drift_strength=1.2
    )
    tl = demo.score_timeline(m["bundle_path"], "synthetic", window=60, seed=5, drift_strength=1.2)
    by = {}
    for p in tl["points"]:
        by.setdefault(p["region"], []).append(p)
    assert {"golden", "drift", "clean_reentry"} <= set(by)
    assert all(p["health_index"] > 0.8 and not p["raw_alarm"] for p in by["golden"])
    assert all(p["raw_alarm"] for p in by["drift"])
    assert all(p["health_index"] > 0.8 and not p["raw_alarm"] for p in by["clean_reentry"])
    clean_min = min(p["health_index"] for p in by["clean_reentry"])
    drift_max = max(p["health_index"] for p in by["drift"])
    assert clean_min - drift_max > 0.3  # 乾淨回歸 vs 殘留飄移明確分離
    assert tl["n_alarms"] > 0


def test_score_timeline_carries_mspc_metrics(tmp_path):
    """C1 WHY：時間線每窗帶 X-only AVM 指標（GSI/T²/SPE 均值）——使 demo 能呈現「SPE 升起」等細節，
    非只有摺疊後的 health_index。drift 窗 SPE 均值須明顯高於 golden 窗（marquee）。"""
    m = demo.build_and_save_model("synthetic", models_dir=str(tmp_path), created_at="t", seed=5, drift_strength=1.2)
    tl = demo.score_timeline(m["bundle_path"], "synthetic", window=60, seed=5, drift_strength=1.2)
    p0 = tl["points"][0]
    assert {"spe_mean", "t2_mean", "gsi_mean"} <= set(p0)
    by = {}
    for p in tl["points"]:
        by.setdefault(p["region"], []).append(p)
    golden_spe = max(p["spe_mean"] for p in by["golden"])
    drift_spe = min(p["spe_mean"] for p in by["drift"])
    assert drift_spe > golden_spe  # SPE 在 drift 窗升起（隱性飄移主訊號）


def test_window_detail_surfaces_gsi_rbc_pvalues(tmp_path):
    """C1 marquee：window_detail 攤開 subscores 摺疊掉的 AVM 細節——GSI/T²/SPE 原始與限、RBC 肇因排行、
    各層 p-value 與分層語義。drift 窗 SPE 越限比例高、RBC 排行非空。回應『看不到 GSI/RI 等詳細指標』。"""
    m = demo.build_and_save_model("synthetic", models_dir=str(tmp_path), created_at="t", seed=5, drift_strength=1.2)
    # 取一個 drift 窗（synthetic 最後一段 A_drift）
    from health_index.adapters import synthetic as syn

    _ds, gt = syn.generate(seed=5, drift_strength=1.2)
    didx = np.flatnonzero(np.asarray(gt.drift_mask))
    s0 = int(didx[0])
    d = demo.window_detail(m["bundle_path"], "synthetic", s0, s0 + 60, compute_fwer=True, seed=5, drift_strength=1.2)
    assert {"GSI_mean", "T2_mean", "T2_limit", "SPE_mean", "SPE_limit", "SPE_exceed_frac"} <= set(d["mspc"])
    assert d["mspc"]["SPE_exceed_frac"] > 0.3            # drift 窗 SPE 大幅越限
    assert len(d["rbc_ranking"]) == 10 and d["rbc_ranking"][0][1] >= d["rbc_ranking"][-1][1]  # 降序排行
    assert set(d["fwer_pvalues"]) == {"L1", "L2", "L4"}  # 各層 p-value 攤開
    assert all(d["layers"][k]["name"] for k in ("L1", "L2", "L4"))  # 分層語義
    assert d["alarm"] is True                            # drift 窗告警


def test_window_detail_compute_fwer_false_skips_pvalues(tmp_path):
    """WHY（成本旋鈕）：compute_fwer=False 時 p_value 全 None、仍給 GSI/T²/SPE/RBC（cheap 路徑）。"""
    m = demo.build_and_save_model("synthetic", models_dir=str(tmp_path), created_at="t", seed=5)
    d = demo.window_detail(m["bundle_path"], "synthetic", 0, 60, compute_fwer=False, seed=5)
    assert d["fwer_pvalues"] is None
    assert d["mspc"]["GSI_mean"] >= 0 and len(d["rbc_ranking"]) > 0


def test_score_timeline_rejects_corrupt_bundle(tmp_path):
    """WHY：步驟4 載入 bundle 走 verify——指紋不符（版本漂移/損毀）拒載，不靜默用壞模型評分。"""
    m = demo.build_and_save_model("synthetic", models_dir=str(tmp_path), created_at="t", seed=5)
    # 竄改存檔 bundle 的指紋期望 → 重載 verify 失敗
    from health_index.deploy.bundle import BundleIntegrityError, load, save

    b = load(m["bundle_path"], verify=False)
    b.fingerprint_hi += 0.5
    save(b, m["bundle_path"])
    with pytest.raises(BundleIntegrityError):
        demo.score_timeline(m["bundle_path"], "synthetic", window=60, seed=5)
