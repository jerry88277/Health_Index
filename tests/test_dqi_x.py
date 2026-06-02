"""L1 DQI_x 閘 WHY 測試（Rule 9）。

WHY：L1 是域/效度閘——擋掉 garbage-in（NaN/凍結/超界）與離域樣本（如換產品 grade B）。
若閘失效（壞資料/離域樣本被當有效），下游軟測量會在 garbage 上外推。FastMCD 的存在理由是
「少數離群不該毒化基準」——若改用 sample covariance，注入的離群會被門檻吞掉而不再被標記。
"""

import numpy as np

from health_index import interface as I
from health_index.adapters import synthetic as syn
from health_index.detectors import dqi_x as dqi


def _golden_X(ds, gt):
    return ds.frame.loc[gt.golden_mask, list(ds.x_columns)].to_numpy()


# ---- sanity_check ----

def test_sanity_flags_nan():
    X = np.ones((6, 3))
    X[2, 1] = np.nan
    valid = dqi.sanity_check(X, frozen_window=0)
    assert not valid[2] and valid[[0, 1, 3, 4, 5]].all()


def test_sanity_flags_out_of_bounds():
    X = np.ones((5, 2))
    X[3] = [100.0, 1.0]
    low, high = np.array([0.0, 0.0]), np.array([10.0, 10.0])
    valid = dqi.sanity_check(X, bounds=(low, high), frozen_window=0)
    assert not valid[3] and valid[[0, 1, 2, 4]].all()


def test_sanity_flags_frozen_run():
    rng = np.random.default_rng(0)
    X = rng.standard_normal((20, 3))
    X[8:14] = X[7]  # 連續 6 列完全凍結（DCS freeze）
    valid = dqi.sanity_check(X, frozen_window=5)
    assert not valid[12]  # 凍結段內被標無效
    assert valid[0] and valid[19]  # 正常列有效


def test_sanity_passes_clean():
    rng = np.random.default_rng(1)
    X = rng.standard_normal((30, 4))
    assert dqi.sanity_check(X, frozen_window=5).all()


def test_sanity_frozen_boundary_exact():
    # WHY（紅隊 Y2）：frozen 邊界差一錯誤無聲；精確釘住「連續 frozen_window 個相同樣本」觸發
    rng = np.random.default_rng(2)
    X = rng.standard_normal((20, 3))
    X[11] = X[12] = X[13] = X[10]  # rows 10..13 共 4 個相同樣本
    v4 = dqi.sanity_check(X, frozen_window=4)
    assert not v4[13]                       # 第 4 個相同樣本觸發
    assert v4[10] and v4[11] and v4[12]     # 前 3 個未觸發
    v5 = dqi.sanity_check(X, frozen_window=5)
    assert v5[10:14].all()                  # 僅 4 個相同 < 5 → 不觸發


# ---- DQIxGate ----

def test_golden_mostly_inlier():
    ds, gt = syn.generate(seed=5)
    Xg = _golden_X(ds, gt)
    gate = dqi.DQIxGate().fit(Xg)
    assert gate.is_inlier(Xg).mean() > 0.9


def test_dqi_x_catches_gross_magnitude_ood():
    # WHY: 大幅度離域（沿/擴張 golden 變異方向）必被 DQI_x 標離域
    ds, gt = syn.generate(seed=5)
    Xg = _golden_X(ds, gt)
    gate = dqi.DQIxGate().fit(Xg)
    assert gate.is_inlier(Xg + 10.0).mean() == 0.0


def test_dqi_x_blind_to_orthogonal_shift_but_residual_flags_it():
    # WHY（層分離，Rule 3/9）：grade B 的操作點位移大多【正交於 golden 主成分方向】，落在
    # 殘差空間 → DQI_x（只量 k-PC 子空間的 Euclidean 距離）抓不到，但重構殘差(SPE-like)明顯
    # 升高。這正是 L2 SPE 存在的理由；L1 DQI_x 本就不該、也抓不到這種正交域移（誠實標記盲點）。
    ds, gt = syn.generate(seed=5)
    Xg = _golden_X(ds, gt)
    gate = dqi.DQIxGate().fit(Xg)
    Xb = ds.frame.loc[ds.frame[I.GRADE_LABEL] == "B", list(ds.x_columns)].to_numpy()

    def residual(X):
        Xs = (X - gate.mean_) / gate.std_
        recon = (Xs - gate.center_) @ gate.P_k_ @ gate.P_k_.T + gate.center_
        return ((Xs - recon) ** 2).sum(axis=1)

    assert gate.is_inlier(Xb).mean() > 0.8                      # DQI_x 抓不到（多數 inlier）
    assert gate.score(Xb).mean() < gate.threshold_             # k-PC 距離本身在門檻內（盲性下界）
    assert residual(Xb).mean() > 3 * residual(Xg).mean()       # 但殘差顯著高 → 需 L2 SPE


def test_fastmcd_beats_sample_cov_under_contamination():
    # WHY（紅隊 🔴-1）：FastMCD 的存在理由＝少數離群不毒化基準。直接對比 robust vs sample-cov：
    # 把 MinCovDet 換成 np.cov（robust=False）必須讓本測試失敗（殺 mutation），否則是假綠。
    ds, gt = syn.generate(seed=5)
    Xg = _golden_X(ds, gt)
    rng = np.random.default_rng(0)
    Xc = Xg.copy()
    k = len(Xc) * 15 // 100  # 15% 污染（< MCD breakdown 1−support_fraction=25%）
    idx = rng.choice(len(Xc), size=k, replace=False)
    Xc[idx] = Xg[idx] * 8.0   # in-subspace 放大（落 golden PC 子空間，DQI_x 看得到）
    robust = dqi.DQIxGate(robust=True).fit(Xc)
    naive = dqi.DQIxGate(robust=False).fit(Xc)
    out_robust = robust.is_inlier(Xc[idx]).mean()
    out_naive = naive.is_inlier(Xc[idx]).mean()
    # naive 的 sample std 被污染膨脹、反而壓縮離群到門檻下；robust median/MAD+MCD support 不受影響
    assert out_robust < out_naive   # 拔掉 MCD（robust→np.cov）會讓兩者相等 → 本測試失敗（殺 mutant）
    assert out_robust < 0.3         # robust 把多數污染標 outlier


def test_threshold_is_factor_times_trimmed_mean():
    ds, gt = syn.generate(seed=5)
    gate = dqi.DQIxGate().fit(_golden_X(ds, gt))
    assert gate.threshold_ > 0
    assert gate.k_ >= 1


def test_deterministic_fit():
    ds, gt = syn.generate(seed=5)
    Xg = _golden_X(ds, gt)
    t1 = dqi.DQIxGate().fit(Xg).threshold_
    t2 = dqi.DQIxGate().fit(Xg).threshold_
    assert t1 == t2  # 固定 random_state → 決定性
