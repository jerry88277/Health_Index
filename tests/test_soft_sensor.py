"""L3 軟測量 WHY 測試（Rule 9）。

marquee WHY：split-Conformal Prediction 取代 AVM RI 的關鍵理由＝**有限樣本邊際覆蓋保證**
（P(y∈Ĉ)≥1−α）。若 CP 失去校準（區間覆蓋率遠離 1−α，或退化為恆覆蓋的無限寬區間），
此性質消失，下游就不該信任 Ŷ——以下測試必須失敗。
"""

import numpy as np

from health_index.adapters import synthetic as syn
from health_index.detectors.soft_sensor import SoftSensor


def _xy(ds, mask):
    X = ds.frame.loc[mask, list(ds.x_columns)].to_numpy()
    y = ds.frame.loc[mask, "y_value"].to_numpy()
    return X, y


def _coverage_one(seed):
    # 大樣本 + dense Y，切 train/calib/test 驗 CP 覆蓋率
    ds, gt = syn.generate(seed=seed, n_per_campaign=800, y_every=1)
    X, y = _xy(ds, gt.golden_mask)
    n = len(X)
    tr, ca = n // 3, 2 * n // 3
    ss = SoftSensor().fit(X[:tr], y[:tr]).calibrate_cp(X[tr:ca], y[tr:ca])
    assert ss.cp_available  # calib ≈ 260 ≥ cp_min_calibration(200)
    lo, hi = ss.predict_interval(X[ca:])
    yt = y[ca:]
    return ((yt >= lo) & (yt <= hi)).mean(), (hi - lo).mean()


def test_cp_coverage_at_target():
    target = 1.0 - SoftSensor().config.cp_alpha  # 0.90
    covs, widths = zip(*[_coverage_one(s) for s in (5, 7, 11, 13, 17)])
    mean_cov = float(np.mean(covs))
    # 覆蓋率 ≈ 1−α：不顯著低於目標（有限樣本保證），也非退化的恆覆蓋（區間有限寬）
    assert mean_cov >= target - 0.05      # ≥ 0.85，覆蓋保證
    assert mean_cov <= 0.99               # 非無限寬恆覆蓋
    assert all(np.isfinite(widths)) and all(w > 0 for w in widths)


def test_cp_unavailable_when_labels_sparse():
    # WHY（紅隊 H1）：標籤稀少（calib < cp_min_calibration）時 CP 不可上線 → cp_available=False
    ds, gt = syn.generate(seed=5)  # 預設 y_every=20 → golden 僅 ~14 個觀測 Y
    X, y = _xy(ds, gt.golden_mask)
    ss = SoftSensor().fit(X, y).calibrate_cp(X, y)
    assert not ss.cp_available
    try:
        ss.predict_interval(X[:5])
        assert False, "calibration 不足卻給了區間"
    except RuntimeError:
        pass


def test_cp_unavailable_when_alpha_too_small_for_calibration():
    # WHY（紅隊 R-1）：α 過小使 k=ceil((n+1)(1−α))>n 時 conformal 分位為 +∞，無法以有限區間達標
    # → cp_available=False（不靜默把 q clip 成 max(scores) 而違反覆蓋保證）。
    from dataclasses import replace

    ds, gt = syn.generate(seed=5, n_per_campaign=800, y_every=1)
    X, y = _xy(ds, gt.golden_mask)
    cfg = replace(SoftSensor().config, cp_min_calibration=50, cp_alpha=0.001)
    ss = SoftSensor(config=cfg).fit(X[:100], y[:100]).calibrate_cp(X[100:160], y[100:160])
    assert not ss.cp_available  # calib=60, k=ceil(61*0.999)=61>60 → 不可用


def test_gpr_predicts_golden_y():
    # 軟測量能以 X 預測 Y（取代抽樣）：held-out R² 明顯為正
    ds, gt = syn.generate(seed=5, n_per_campaign=800, y_every=1)
    X, y = _xy(ds, gt.golden_mask)
    n = len(X)
    h = n // 2
    ss = SoftSensor().fit(X[:h], y[:h])
    yhat = ss.predict(X[h:])
    yt = y[h:]
    r2 = 1 - np.sum((yt - yhat) ** 2) / np.sum((yt - yt.mean()) ** 2)
    assert r2 > 0.5


def test_smaller_alpha_widens_interval():
    # 風險預算越小（α↓）→ 區間越寬（覆蓋越保守）
    ds, gt = syn.generate(seed=5, n_per_campaign=800, y_every=1)
    X, y = _xy(ds, gt.golden_mask)
    from dataclasses import replace

    base = SoftSensor().config
    n = len(X)
    tr, ca = n // 3, 2 * n // 3
    ss10 = SoftSensor(config=replace(base, cp_alpha=0.10)).fit(X[:tr], y[:tr]).calibrate_cp(X[tr:ca], y[tr:ca])
    ss01 = SoftSensor(config=replace(base, cp_alpha=0.01)).fit(X[:tr], y[:tr]).calibrate_cp(X[tr:ca], y[tr:ca])
    assert ss01.cp_q_ >= ss10.cp_q_


def test_deterministic_fit():
    ds, gt = syn.generate(seed=5, n_per_campaign=400, y_every=1)
    X, y = _xy(ds, gt.golden_mask)
    p1 = SoftSensor().fit(X, y).predict(X[:10])
    p2 = SoftSensor().fit(X, y).predict(X[:10])
    assert np.allclose(p1, p2)
