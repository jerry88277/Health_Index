"""P1 融合層 severity transform 回歸測試（Rule 9，紅隊 B 點 5 揪出 P1 原本零測試保護）。

P1 把 L1/L2 子分數從「超限比例」（二值化後取比例）改為「per-sample 對 golden 標準化嚴重度→exp→窗均值」
（不飽和）。**P1 真正修的是 L1 去飽和**：舊 L1=is_inlier().mean() 對「每樣本都在 DQI 門檻內的 sub-threshold
域偏移」恆=1.0（謊稱完美健康），P1 severity 會隨偏移單調下降。下列測試**殺死 revert mutant**——把
subscores 還原成舊二值比例時必須失敗（否則 P1 的存在理由沒有回歸保護）。

誠實邊界（紅隊）：在現有 synthetic 上，舊 L2（in-control 比例）其實未飽和（相關型 drift 破 SPE 限夠多），
故 P1 的增量主要在 L1 去飽和 + 三層語義一致（非飽和原則）；最弱飄移（ds≲0.3）的覆蓋仍倚賴 fwer_alarm
（runner 已 union），非 P1 融合本身。自相關資料的窗級標準化偏差見 health._severity_health docstring。
"""

import numpy as np
import pytest

from health_index.adapters import synthetic as syn
from health_index.health import HealthIndex


def _golden(seed=5):
    ds, gt = syn.generate(seed=seed, drift_strength=0.8)
    cols = list(gt.x_columns)
    Xg = ds.frame.loc[np.asarray(gt.golden_mask), cols].to_numpy()
    return HealthIndex().fit(Xg), Xg


def test_p1_l1_desaturates_on_subthreshold_shift():
    """marquee mutant-kill：sub-threshold 域偏移下，每樣本仍在 DQI inlier 門檻內（舊 L1=inlier 比例≈1.0、
    謊稱健康），但 P1 L1 severity 須明顯 <1（真實反映偏移）。revert L1 成 is_inlier().mean() → 本測試失敗。"""
    hi, Xg = _golden()
    Xs = Xg + 0.6 * Xg.std(axis=0)  # 溫和域偏移
    inlier_ratio = float(hi.dqi_.is_inlier(Xs).mean())
    p1_l1 = hi.subscores(Xs)["L1"]
    assert inlier_ratio > 0.9          # 舊二值比例會說「健康」（多數樣本仍在門檻內）
    assert p1_l1 < inlier_ratio - 0.05  # P1 severity 顯著低於二值比例 → 不飽和（殺 mutant）


def test_p1_subscores_monotone_in_subthreshold_regime():
    """WHY（不飽和原則）：偏移漸增時 P1 L1 單調下降，而舊二值 inlier 比例在 sub-threshold 區恆≈1（飽和）。
    鎖住「P1 對二值比例看不見的漸變有解析度」。"""
    hi, Xg = _golden()
    sds = Xg.std(axis=0)
    l1s = [hi.subscores(Xg + k * sds)["L1"] for k in (0.0, 0.4, 0.8)]
    ratios = [float(hi.dqi_.is_inlier(Xg + k * sds).mean()) for k in (0.0, 0.4, 0.8)]
    assert l1s[0] > l1s[1] > l1s[2]            # P1 嚴格單調回應
    assert max(ratios) - min(ratios) < 0.1     # 舊二值比例在此區幾乎不動（飽和對照）


def test_p1_subscores_are_unsaturated_exp_form():
    """WHY：三層子分數皆為 exp(−標準化嚴重度) 形（語義一致、值域 (0,1]、golden≈1）。"""
    hi, Xg = _golden()
    s = hi.subscores(Xg)
    assert set(s) == {"L1", "L2", "L4"}
    assert all(0.0 < v <= 1.0 for v in s.values())
    assert s["L1"] > 0.8 and s["L2"] > 0.8  # golden 上各層健康（非飽和但仍高）


def test_p1_window_length_invariance_l1_l2():
    """WHY（紅隊 A 點 4，限定）：per-sample 標準化使 L1/L2 子分數不受窗長影響（與舊比例不同）。
    對同一 drift 段不同窗長，L1/L2 近似不變（L4 因 wasserstein 隨樣本數變，不在此鎖）。"""
    ds, gt = syn.generate(seed=5, drift_strength=0.8)
    cols = list(gt.x_columns)
    Xg = ds.frame.loc[np.asarray(gt.golden_mask), cols].to_numpy()
    hi = HealthIndex().fit(Xg)
    Xd = ds.frame.loc[np.asarray(gt.drift_mask), cols].to_numpy()
    l1_30 = hi._severity_health(hi.dqi_.score(Xd[:30]), hi._dqi_mu_, hi._dqi_sig_)
    l1_120 = hi._severity_health(hi.dqi_.score(Xd[:120]), hi._dqi_mu_, hi._dqi_sig_)
    assert abs(l1_30 - l1_120) < 0.1  # 窗長 30 vs 120 的 L1 近似一致


def test_p1_golden_not_flagged_drift_flagged():
    """DoD 回歸：P1 後 golden 仍不告警、drift 仍告警（修不破壞主判準）。"""
    hi, Xg = _golden()
    ds, gt = syn.generate(seed=5, drift_strength=0.8)
    Xd = ds.frame.loc[np.asarray(gt.drift_mask), list(gt.x_columns)].to_numpy()
    assert hi.health_index(Xg) > hi.config.hi_alarm_threshold and not hi.is_alarm(Xg)
    assert hi.health_index(Xd) < hi.config.hi_alarm_threshold and hi.is_alarm(Xd)
