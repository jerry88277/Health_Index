"""跨資料集 DoD benchmark WHY 測試（桶6，Rule 9）。

marquee WHY：泛化的**證明**＝同一判斷鏈經統一協定跑通結構不同的多資料集、且**通過相同 DoD**
（golden 健康 / 隱性飄移被抓且早於單變數 SPC / 區分乾淨 vs 殘留）。當任一資料集 DoD 退化（漏抓飄移、
誤報乾淨、或單變數 SPC 其實抓得到），benchmark 必須失敗——它是泛化不退化的守門。
"""

import os

import numpy as np
import pytest

from health_index.adapters.base import GroundTruth, Segment
from health_index.validation.benchmark import (
    DatasetDoD,
    _segment_roles,
    evaluate_dataset,
    run_benchmark,
)

_TEP_DATA = os.path.join("data", "tep", "m1d00.mat")


def test_benchmark_synthetic_passes_all_dod():
    # marquee（無需資料）：合成集經統一協定通過三條 DoD
    r = evaluate_dataset("synthetic", seed=5, drift_strength=1.2)
    assert r.golden_healthy and r.drift_caught and r.spc_blind_on_drift and r.clean_not_flagged
    assert r.passed
    # 量化：drift 融合 HI 明顯低於 golden，且單變數 SPC 近乎盲（index 存在理由）
    assert r.drift_health < r.golden_health - 0.2
    assert r.spc_exceedance_drift < 0.15


def test_dod_criteria_are_falsifiable_not_vacuous():
    # WHY（鎖判準非恆真）：把 golden 門檻設到不可能（1.0）→ golden_healthy=False → passed=False；
    # 把 SPC 盲上限設 0 → spc_blind=False。證 DoD 真有鑑別、非 rubber-stamp。
    strict = evaluate_dataset("synthetic", seed=5, drift_strength=1.2, golden_health_min=1.0)
    assert strict.golden_healthy is False and strict.passed is False
    spc = evaluate_dataset("synthetic", seed=5, drift_strength=1.2, spc_blind_max=0.0)
    assert spc.spc_blind_on_drift is False


def test_segment_roles_identifies_golden_clean_drift():
    # WHY：角色抽取須正確——golden（被 golden_mask 覆蓋）、drift（與 drift_mask 交集）、
    # clean（同 golden 標籤的另一段）。接錯角色→評錯段→DoD 失真。
    n = 50
    gm = np.zeros(n, bool)
    gm[:10] = True
    dm = np.zeros(n, bool)
    dm[40:] = True
    segs = (
        Segment(0, 0, 10, "A"),
        Segment(1, 10, 20, "B"),
        Segment(2, 20, 30, "A"),
        Segment(3, 30, 40, "C"),
        Segment(4, 40, 50, "A"),
    )
    gt = GroundTruth(x_columns=("x",), golden_mask=gm, segments=segs, drift_mask=dm)
    golden, clean, drift = _segment_roles(gt)
    assert golden.id == 0 and drift.id == 4 and clean.id == 2  # clean＝同 A、非 golden/drift


def test_no_drift_dataset_only_evaluates_golden():
    # WHY（誠實標）：無 drift 真值（drift_mask=None，如真實老化集）→ 飄移/clean 判準 None、不假裝；
    # passed 僅看 golden_healthy。
    n = 30
    gm = np.zeros(n, bool)
    gm[:10] = True
    segs = (Segment(0, 0, 10, "x"), Segment(1, 10, 30, "x"))
    # 構造一個無 drift 的 DatasetDoD（直接驗 passed 邏輯）
    r = DatasetDoD(
        dataset="d", golden_health=0.9, clean_health=None, drift_health=None,
        drift_fwer_alarm=None, clean_fwer_alarm=None, spc_exceedance_drift=None,
        golden_healthy=True, drift_caught=None, spc_blind_on_drift=None, clean_not_flagged=None,
    )
    assert r.passed is True   # 只有 golden 判準適用且通過
    r2 = DatasetDoD(**{**r.__dict__, "golden_healthy": False})
    assert r2.passed is False
    # _segment_roles 對 drift_mask=None → drift=None
    gt = GroundTruth(x_columns=("x",), golden_mask=gm, segments=segs, drift_mask=None)
    _, _, drift = _segment_roles(gt)
    assert drift is None


def test_run_benchmark_returns_results_skips_missing():
    # WHY：run_benchmark 對可建資料集回結果、資料缺者略過（不讓整體失敗）
    out = run_benchmark((("synthetic", {"seed": 5, "drift_strength": 1.2}),))
    assert len(out) == 1 and out[0].dataset == "synthetic" and out[0].passed


def test_run_benchmark_warns_on_missing_data():
    # 紅隊 A-D2：資料缺的資料集被略過時須發 RuntimeWarning（涵蓋率縮水不可靜默）
    with pytest.warns(RuntimeWarning, match="略過"):
        out = run_benchmark((("uci_gas_drift", {"data_dir": "data/__no_such_dir__"}),))
    assert out == []


def test_segment_roles_rejects_drift_overlapping_golden():
    # 紅隊 A-D1：drift_mask 與 golden 段重疊 → 角色不互斥 → fail loud
    n = 20
    gm = np.zeros(n, bool)
    gm[:10] = True
    dm = np.zeros(n, bool)
    dm[5:8] = True  # 落在 golden 段內
    gt = GroundTruth(x_columns=("x",), golden_mask=gm, segments=(Segment(0, 0, 10, "A"), Segment(1, 10, 20, "A")), drift_mask=dm)
    with pytest.raises(ValueError, match="重疊"):
        _segment_roles(gt)


@pytest.mark.skipif(not os.path.exists(_TEP_DATA), reason="TEP .mat 未下載（data/tep/）")
def test_benchmark_tep_variants_pass_dod():
    # marquee（真實 TEP）：iid 與保時序情境皆通過 DoD——同一鏈、不同資料結構、相同判準
    for name, kw in (("tep", {"seed": 0, "drift_strength": 1.0}), ("tep_tp", {"seed": 0, "drift_strength": 0.7})):
        r = evaluate_dataset(name, **kw)
        assert r.passed, f"{name} DoD 未過: {r}"
        assert r.drift_caught and r.spc_blind_on_drift and r.clean_not_flagged
