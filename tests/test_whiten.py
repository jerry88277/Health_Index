"""#10 殘差自相關 AR 白化 WHY 測試（Rule 9）。

marquee WHY：CUSUM/EWMA 的管制界假設**獨立**觀測；殘差若正自相關，等效樣本數縮水→誤報膨脹、
偵測靈敏度失真（YHistoryMonitor 的經驗 h 校準只吸收**尺度**，吸收不了**相依結構**）。白化＝
以 AR(p) 把殘差轉成 innovations（近 iid），讓管制界回到有效前提。測試鎖：
(a) 自相關殘差→偵測到並配適 AR、白化後 **Ljung-Box 不再顯著**（自相關真的被移除；
    若白化沒真移除相依性，測試要失敗）；
(b) 已近 iid 的殘差→**不套用白化**（order=0、identity）——不對沒壞的東西轉換、且不白白丟前 p 點；
(c) NaN 缺口→innovation 為 NaN（不捏造推補）；
(d) 接進 residual monitor：資訊揭露且 iid 情形下行為與過去一致（向後相容）。
確定性（Rule 5）：OLS + 固定檢定，無 RNG。
"""

import numpy as np

from health_index.batch_avm.mapping import fit_batch_model
from health_index.batch_avm.residual import fit_residual_monitor, score_residuals
from health_index.batch_avm.whiten import fit_whitener, ljung_box, whiten


def _ar1(n=300, phi=0.75, seed=0, sd=1.0):
    rng = np.random.default_rng(seed)
    e = np.zeros(n)
    for t in range(1, n):
        e[t] = phi * e[t - 1] + sd * rng.normal()
    return e


def _iid(n=300, seed=2):
    # 註：閘門是 5% 顯著水準的檢定，故約 5% 的 iid 抽樣會（依設計）被判顯著；此處取代表性抽樣
    # （seed=2 → p≈0.49）。閘門本身的校準由 test_ljung_box_gate_is_calibrated 鎖住。
    return np.random.default_rng(seed).normal(size=n)


def test_autocorrelated_residuals_are_detected_and_whitened():
    # WHY(a)：AR(1) 自相關被偵測→配適→白化後 Ljung-Box 不再顯著（相依性真的移除）。
    e = _ar1()
    w = fit_whitener(e)
    assert w.applied is True and w.order >= 1
    assert w.lb_p_before < 0.05                    # 白化前顯著自相關
    inn = whiten(w, e)
    q, p_after = ljung_box(inn[np.isfinite(inn)])
    assert p_after > 0.05                          # 白化後不顯著＝已近 iid
    assert w.lb_p_after is not None and w.lb_p_after > 0.05


def test_iid_residuals_are_not_whitened():
    # WHY(b)：已近 iid → 不套用（order=0、identity），不做無謂轉換也不丟點。
    e = _iid()
    w = fit_whitener(e)
    assert w.applied is False and w.order == 0
    out = whiten(w, e)
    assert np.array_equal(out, e)                  # identity


def test_nan_gaps_yield_nan_innovations():
    # WHY(c)：缺口不推補——lag 視窗含 NaN 的點 innovation 為 NaN（誠實不評）。
    e = _ar1(n=120)
    e[50] = np.nan
    w = fit_whitener(e)
    assert w.applied is True
    inn = whiten(w, e)
    assert np.isnan(inn[50])                       # 該點本身缺
    assert np.isnan(inn[51])                       # lag 視窗含缺口 → 不評
    assert np.isfinite(inn[60])                    # 遠離缺口者正常


def test_ar_phi_recovers_true_coefficient():
    # WHY：白化係數須真反映相依性（配歪＝白化無效）。AR(1) φ=0.75 應被近似還原。
    e = _ar1(n=800, phi=0.75, seed=3)
    w = fit_whitener(e, max_order=1)
    assert abs(float(w.phi[0]) - 0.75) < 0.1


def test_ljung_box_gate_is_calibrated():
    # WHY：白化與否全繫於此閘門——閘門偏誤會導致**過度白化**（無謂丟點+轉換）或**不足白化**
    # （相依殘差仍用 iid 界→誤報膨脹）。鎖住：對 iid 拒絕率≈名目 5%、對 AR(1) 有檢定力。
    rej = sum(ljung_box(np.random.default_rng(1000 + s).normal(size=300))[1] < 0.05 for s in range(200))
    assert 0.01 <= rej / 200 <= 0.12          # 名目 5% 附近（非系統性偏誤）
    pw = 0
    for s in range(30):                        # 對真自相關要抓得到
        rng = np.random.default_rng(2000 + s)
        e = np.zeros(300)
        for t in range(1, 300):
            e[t] = 0.6 * e[t - 1] + rng.normal()
        pw += ljung_box(e)[1] < 0.05
    assert pw / 30 >= 0.9


def test_deterministic():
    e = _ar1(seed=5)
    a, b = fit_whitener(e), fit_whitener(e)
    assert a.order == b.order and np.array_equal(a.phi, b.phi) and a.lb_p_before == b.lb_p_before


def test_wired_into_residual_monitor_backward_compatible():
    # WHY(d)：接進 G2 殘差監控且揭露白化資訊；iid 殘差情形下不套用＝行為與過去一致。
    rng = np.random.default_rng(0)
    X = rng.normal(size=(60, 5))
    y = 3.0 * X[:, 0] + 0.1 * rng.normal(size=60)
    m = fit_batch_model(X, y, columns=[f"c{i}" for i in range(5)])
    rm = fit_residual_monitor(m, X, y)
    assert hasattr(rm, "whitener") and rm.whitener is not None
    res = score_residuals(rm, m, X, y)
    w = res["whitening"]
    assert set(w) >= {"applied", "order", "lb_p_before"}
    assert w["applied"] is False                   # 殘差近 iid → 不套用（向後相容）
