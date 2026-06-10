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


# --- 桶2a：PLS 軟測量（可擴展/共線穩健）+ 規模選擇器 ---
from health_index.detectors.soft_sensor import (  # noqa: E402
    PLSSoftSensor,
    _split_conformal_q,
    make_soft_sensor,
)


def _collinear_xy(n=600, p=128, r=3, seed=0):
    """高維**共線** X（p 維由 r≪p 個潛因子生成）+ Y=潛因子線性組合——軟測量的典型場景，
    GPR(RBF) 在此高維退化、O(n³) 貴；PLS 投影潛在成分天然處理。"""
    rng = np.random.default_rng(seed)
    Z = rng.standard_normal((n, r))
    load = rng.standard_normal((r, p))
    beta = rng.standard_normal(r)
    X = Z @ load + 0.1 * rng.standard_normal((n, p))
    y = Z @ beta + 0.05 * rng.standard_normal(n)
    return X, y


def test_pls_recovers_high_dim_collinear_y():
    # marquee WHY（桶2a 存在理由）：128 維共線 X，PLS held-out R² 高、成分數受 cap——這正是「多製程
    # 參數」泛化時 GPR/RBF 退化、O(n³) 不可擴展之處。若 PLS 喪失此能力（R² 崩），測試失敗。
    X, y = _collinear_xy()
    ss = PLSSoftSensor().fit(X[:400], y[:400])
    yhat = ss.predict(X[400:])
    yt = y[400:]
    r2 = 1 - np.sum((yt - yhat) ** 2) / np.sum((yt - yt.mean()) ** 2)
    assert r2 > 0.9
    assert ss.n_components_ == min(PLSSoftSensor().config.pls_components, X.shape[1], 399)


def test_pls_cp_coverage_at_target():
    # WHY：split-CP 為 model-agnostic——以 PLS 為基底仍給有限樣本覆蓋保證（≈1−α）
    X, y = _collinear_xy(n=900)
    from dataclasses import replace

    cfg = replace(PLSSoftSensor().config, cp_min_calibration=100)
    n = len(X)
    tr, ca = n // 3, 2 * n // 3
    ss = PLSSoftSensor(cfg).fit(X[:tr], y[:tr]).calibrate_cp(X[tr:ca], y[tr:ca])
    assert ss.cp_available
    lo, hi = ss.predict_interval(X[ca:])
    cov = ((y[ca:] >= lo) & (y[ca:] <= hi)).mean()
    assert cov >= (1.0 - cfg.cp_alpha) - 0.05 and cov <= 0.999  # 覆蓋保證、非無限寬


def test_pls_interface_matches_gpr_and_unavailable_raises():
    # WHY（互換性）：PLS 與 SoftSensor 同介面；CP 不足時 predict_interval fail loud
    X, y = _collinear_xy(n=120)
    ss = PLSSoftSensor().fit(X, y)
    assert hasattr(ss, "predict") and hasattr(ss, "calibrate_cp") and hasattr(ss, "cp_available")
    yh, std = ss.predict(X[:5], return_std=True)
    assert yh.shape == (5,) and std.shape == (5,) and np.all(std == std[0])  # 同方差 std
    ss.calibrate_cp(X, y)  # calib < cp_min_calibration(200) → 不可用
    assert not ss.cp_available
    import pytest

    with pytest.raises(RuntimeError):
        ss.predict_interval(X[:5])


def test_make_soft_sensor_selects_by_scale():
    # WHY（選擇器）：低維小資料 → GPR（向後相容）；高維 或 大 n → PLS（可擴展）
    assert isinstance(make_soft_sensor(n_samples=100, n_features=10), SoftSensor)
    assert isinstance(make_soft_sensor(n_samples=445, n_features=128), PLSSoftSensor)
    assert isinstance(make_soft_sensor(n_samples=2000, n_features=10), PLSSoftSensor)


def test_split_conformal_q_helper_edges():
    # WHY：CP 分位 helper 的兩個 None 情形（calib 不足 / α 太小 k>n）+ 正常回第 k 小
    s = np.arange(1.0, 101.0)  # 100 個殘差
    assert _split_conformal_q(s, n_min=200, alpha=0.1) is None          # n<n_min
    assert _split_conformal_q(s, n_min=50, alpha=0.001) is None         # k=ceil(101*0.999)=101>100
    q = _split_conformal_q(s, n_min=50, alpha=0.1)
    assert q == np.sort(s)[int(np.ceil(101 * 0.9)) - 1]                 # 第 k 小（k=91）


def test_pls_deterministic():
    X, y = _collinear_xy(n=200)
    p1 = PLSSoftSensor().fit(X, y).predict(X[:10])
    p2 = PLSSoftSensor().fit(X, y).predict(X[:10])
    assert np.allclose(p1, p2)


def test_pls_constant_x_fails_loud():
    # 紅隊 A-D2：全常數 X → PLS deflation 內部 NaN crash，改在 fit 邊界 fail loud（清楚訊息）
    import pytest

    with pytest.raises(ValueError, match="常數"):
        PLSSoftSensor().fit(np.ones((50, 5)), np.arange(50.0))
