"""CV+/jackknife+ 小 n 可信度 WHY 測試（Rule 9）。

marquee WHY：golden 是單一 campaign，n 常 < cp_min_calibration(200) → split-CP 退回 GSI，
Ŷ 失去可信區間。CV+/jackknife+ 以 K-fold leave-fold-out 讓**每點 both fit both 校準**，
在小 n 仍可上線（**自有門檻，獨立於 cp_min_calibration=200**）。若 CV+ 在小 n 不可用、
或覆蓋跌破最壞 1−2α 底線，此性質消失——以下測試須失敗。
誠實口徑（紅隊 A11 / must-fix #2）：CV+ 保證是 worst-case ≥1−2α，非 split-CP 的 ≥1−α。
"""

import numpy as np
import pytest

from health_index.adapters import synthetic as syn
from health_index.config import DEFAULT
from health_index.detectors.conformal_cv import CVPlusConformal
from health_index.detectors.soft_sensor import SoftSensor


def _xy(ds, mask):
    X = ds.frame.loc[mask, list(ds.x_columns)].to_numpy()
    y = ds.frame.loc[mask, "y_value"].to_numpy()
    return X, y


def _iid_xy(n, seed):
    # 乾淨 i.i.d. 迴歸 DGP：殘差可交換，隔離 CV+ 數學（製程自相關對覆蓋的影響另於設計文件記錄）
    rng = np.random.default_rng(seed)
    X = rng.normal(size=(n, 3))
    y = X @ np.array([1.0, -0.5, 0.3]) + rng.normal(scale=0.2, size=n)
    return X, y


def test_cv_plus_available_when_split_cp_is_not_at_small_n():
    # marquee WHY（must-fix #1）：n=120 < cp_min_calibration(200) → split-CP 不可用（退 GSI）；
    # CV+ 必須可用，否則小 n 修法對「正是要救的情況」失效。
    ds, gt = syn.generate(seed=5, n_per_campaign=800, y_every=1)
    X, y = _xy(ds, gt.golden_mask)
    X, y = X[:120], y[:120]

    ss = SoftSensor(DEFAULT).fit(X, y).calibrate_cp(X, y)  # in-sample，仍 < 200
    assert ss.cp_available is False

    cv = CVPlusConformal(DEFAULT).fit(lambda: SoftSensor(DEFAULT), X, y)
    assert cv.available is True
    lo, hi = cv.predict_interval(X[:5])
    assert lo.shape == (5,) and hi.shape == (5,)
    assert np.all(hi > lo) and np.all(np.isfinite(lo)) and np.all(np.isfinite(hi))


def test_cv_plus_coverage_meets_1_minus_2alpha_floor():
    # WHY：CV+ 在小 n 仍給可用覆蓋；誠實最壞底線 ≥1−2α（α=0.1→0.80），實務常近 1−α。
    covs = []
    for seed in (5, 7, 11):
        X, y = _iid_xy(320, seed)
        tr = 120  # < cp_min_calibration
        cv = CVPlusConformal(DEFAULT).fit(lambda: SoftSensor(DEFAULT), X[:tr], y[:tr])
        assert cv.available
        lo, hi = cv.predict_interval(X[tr:])
        yt = y[tr:]
        covs.append(float(((yt >= lo) & (yt <= hi)).mean()))
    mean_cov = float(np.mean(covs))
    assert mean_cov >= 1.0 - 2 * DEFAULT.cp_alpha   # ≥ 0.80 最壞底線
    assert mean_cov <= 0.999                         # 非無限寬恆覆蓋


def test_cv_plus_coverage_floor_is_honest_not_strict_1_minus_alpha():
    # WHY（must-fix #2）：CV+ 誠實回報 coverage_floor = 1−2α（=0.80），
    # 不得沿用 split-CP 的 ≥1−α（0.90）宣稱。
    cv = CVPlusConformal(DEFAULT)
    assert abs(cv.coverage_floor - (1.0 - 2 * DEFAULT.cp_alpha)) < 1e-12
    assert cv.band_kind == "CV+"


def test_cv_plus_unavailable_below_min_obs():
    # WHY：低於 cv_plus_min_obs 時不可用，predict_interval fail loud（不靜默給假區間）。
    X, y = _iid_xy(8, 0)  # < cv_plus_min_obs
    cv = CVPlusConformal(DEFAULT).fit(lambda: SoftSensor(DEFAULT), X, y)
    assert cv.available is False
    with pytest.raises(RuntimeError):
        cv.predict_interval(X[:2])


def test_cv_plus_deterministic():
    # Rule 5：折分配按 index（無 RNG）→ 完全可重現。
    X, y = _iid_xy(100, 5)
    lo1, hi1 = CVPlusConformal(DEFAULT).fit(lambda: SoftSensor(DEFAULT), X, y).predict_interval(X[:10])
    lo2, hi2 = CVPlusConformal(DEFAULT).fit(lambda: SoftSensor(DEFAULT), X, y).predict_interval(X[:10])
    assert np.allclose(lo1, lo2) and np.allclose(hi1, hi2)


def test_jackknife_plus_is_cv_plus_with_k_equals_n():
    # WHY：jackknife+ = CV+ 的 K=n（逐一 LOO）特例；設 n_folds≥n 觸發（capped 至 n）。
    X, y = _iid_xy(40, 7)
    jk = CVPlusConformal(DEFAULT, n_folds=999).fit(lambda: SoftSensor(DEFAULT), X, y)
    assert jk.available
    assert jk.n_folds_effective_ == 40  # capped to n
    lo, hi = jk.predict_interval(X[:5])
    assert np.all(hi > lo)
