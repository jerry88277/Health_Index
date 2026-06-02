"""L4 campaign 分佈漂移 WHY 測試（Rule 9）。

marquee WHY（成功判準 3）：在 PCA 分數空間，**殘留 drift 的 A campaign 被判漂移、乾淨換線
後回歸的 A campaign 不被判漂移**——這正是「區分乾淨回歸 vs 殘留飄移」的能力。drift 改的是
相關結構（邊際分佈與 golden 相同），故須在分數空間量測。當此區分力消失時測試必須失敗。
"""

import numpy as np
import pytest

from health_index.adapters import synthetic as syn
from health_index.detectors.drift import DriftDetector


def _seg(ds, mask_or_slice, cols):
    if isinstance(mask_or_slice, np.ndarray):
        return ds.frame.loc[mask_or_slice, list(cols)].to_numpy()
    s, e = mask_or_slice
    return ds.frame.iloc[s:e][list(cols)].to_numpy()


def _campaigns(seed):
    ds, gt = syn.generate(seed=seed, drift_strength=1.2)
    cols = ds.x_columns
    Xg = _seg(ds, gt.golden_mask, cols)
    s, e, g = gt.campaign_bounds[2]  # clean re-entry A
    assert g == "A"
    Xc = _seg(ds, (s, e), cols)
    Xd = _seg(ds, gt.drift_mask, cols)
    return Xg, Xc, Xd


@pytest.mark.parametrize("seed", [5, 7, 11, 13, 17])
def test_drift_detected_clean_reentry_not(seed):
    Xg, Xc, Xd = _campaigns(seed)
    det = DriftDetector().fit(Xg)
    assert det.is_drift(Xd) is True       # 殘留 drift 被判漂移
    assert det.is_drift(Xc) is False      # 乾淨回歸不被判漂移（判準 3）


def test_golden_vs_golden_not_drift():
    # null：golden 兩半互比不應判漂移（型一控制）
    ds, gt = syn.generate(seed=5)
    Xg = ds.frame.loc[gt.golden_mask, list(ds.x_columns)].to_numpy()
    det = DriftDetector().fit(Xg[: len(Xg) // 2])
    assert det.is_drift(Xg[len(Xg) // 2 :]) is False


def test_wasserstein_magnitude_drift_gg_clean():
    # 量級（對 null 標準化的 z）：drift ≫ clean，且 clean 接近 null（z 小）
    Xg, Xc, Xd = _campaigns(5)
    det = DriftDetector().fit(Xg)
    z_clean = det.wasserstein_magnitude(Xc)
    z_drift = det.wasserstein_magnitude(Xd)
    assert z_drift > 5 * abs(z_clean)  # drift 量級遠大於乾淨回歸（abs 防負 z 使斷言 vacuous）
    assert abs(z_clean) < 5            # 乾淨回歸接近 golden null（雙尾）
    assert z_drift > 10                # drift 遠離 null


def test_wasserstein_z_sample_size_invariant():
    # WHY（紅隊 🔴-1）：同分佈段的 z 不可隨段長爆走（否則健康段誤報，威脅 DoD#1）。
    rng = np.random.default_rng(0)
    Xg = rng.standard_normal((600, 5))
    det = DriftDetector().fit(Xg)
    zs = [abs(det.wasserstein_magnitude(rng.standard_normal((m, 5)))) for m in (30, 120, 300, 600)]
    assert max(zs) < 5  # 全長度 |z| 受控，無爆走


def test_is_drift_layered_and_and_cost_tiering(monkeypatch):
    # WHY（紅隊 R1）：is_drift 是「KS first-pass → MMD 升級、兩者皆顯著才判漂移」的分層 AND。
    # 鎖住：(a) KS 不顯著 → 不呼叫 MMD（成本分層）；(b) KS 顯著但 MMD 不顯著 → False（AND 否決）。
    Xg, _, Xd = _campaigns(5)
    det = DriftDetector().fit(Xg)
    calls = {"mmd": 0}

    def fake_mmd(X, **k):
        calls["mmd"] += 1
        return fake_mmd.ret

    monkeypatch.setattr(det, "mmd_pvalue", fake_mmd)
    monkeypatch.setattr(det, "ks_min_pvalue", lambda X: 0.5)  # KS 不顯著
    fake_mmd.ret = 0.0
    assert det.is_drift(Xd) is False and calls["mmd"] == 0  # MMD 未被呼叫
    monkeypatch.setattr(det, "ks_min_pvalue", lambda X: 0.0)  # KS 顯著
    fake_mmd.ret = 0.9  # MMD 不顯著
    assert det.is_drift(Xd) is False and calls["mmd"] == 1  # AND 否決
    fake_mmd.ret = 0.0  # MMD 顯著
    assert det.is_drift(Xd) is True


def test_block_perm_is_valid_permutation():
    # WHY（紅隊 Y3）：block-permutation 須為合法 permutation（保短程相依、不重不漏）
    rng = np.random.default_rng(0)
    for bs in (1, 3, 7):
        perm = DriftDetector._block_perm(20, bs, rng)
        assert sorted(perm.tolist()) == list(range(20))


def test_ks_first_pass_separates():
    Xg, Xc, Xd = _campaigns(5)
    det = DriftDetector().fit(Xg)
    assert det.ks_min_pvalue(Xd) < det.config.ks_alpha   # drift 觸發
    assert det.ks_min_pvalue(Xc) >= det.config.ks_alpha  # 乾淨回歸不觸發


def test_psi_drift_gt_clean():
    # PSI 僅供溝通：drift 的 PSI 應高於乾淨回歸
    Xg, Xc, Xd = _campaigns(5)
    det = DriftDetector().fit(Xg)
    assert det.psi(Xd) > det.psi(Xc)


def test_mmd_pvalue_deterministic():
    Xg, Xc, Xd = _campaigns(5)
    det = DriftDetector().fit(Xg)
    assert det.mmd_pvalue(Xd) == det.mmd_pvalue(Xd)  # 固定 random_state → 決定性
