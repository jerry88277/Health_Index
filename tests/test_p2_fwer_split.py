"""P2 FWER 時間連續 split 回歸測試（Rule 9，紅隊揪出 P2 原零測試保護）。

P2：自相關（block）路徑的 FWER 校準從「fit 全 golden + null 取 in-sample」改為「fit 前 2/3 連續段、
L1/L2 null 取後 1/3 連續段（out-of-sample，保自相關）；**L4 例外保持 fit 全 golden**（window-vs-window
自校準、不需 split，否則對非平穩後段誤報——紅隊 A#4 揪出的 P2 引入 regression）」。

下列測試殺 mutant：(a) revert 成 in-sample null → 結構性 _fwer_block_cal_ 應為 None；(b) 把 L4 改 fit
前 2/3 → _fwer_drift_ 樣本數變 2/3。CI 用合成 AR(1)（不需 TEP）鎖結構；FPR 數字鎖在 TEP-gated 測試。
"""

import os

import numpy as np
import pytest

from health_index.health import HealthIndex

_TEP_DATA = os.path.join("data", "tep", "m1d00.mat")


def _ar1_golden(n=900, p=6, rho=0.9, seed=1):
    """合成多變量 AR(1) 自相關 golden（觸發 block 路徑，不需 TEP）。"""
    r = np.random.default_rng(seed)
    L = np.random.default_rng(99).standard_normal((p, p)) * 0.3 + np.eye(p)
    X = np.zeros((n, p))
    e = r.standard_normal((n, p))
    for t in range(1, n):
        X[t] = rho * X[t - 1] + e[t]
    return X @ L


def test_block_path_uses_out_of_sample_continuous_cal():
    """marquee mutant-kill：自相關 golden → 走 block 路徑，FWER null 取自**out-of-sample 連續尾段**
    （_fwer_block_cal_ 非 None、disjoint 於 fit 前段）。revert 成 in-sample（_fwer_block_cal_=None）→ 失敗。"""
    G = _ar1_golden()
    hi = HealthIndex().fit(G)
    assert hi.drift_.block_len_ > 1  # 確認自相關觸發 block 路徑
    hi.fwer_pvalues(G[:60])  # 觸發 lazy 校準
    assert hi._fwer_l2_block_ is True and hi._fwer_split_ is True
    assert hi._fwer_block_cal_ is not None  # out-of-sample 連續尾段（殺 in-sample mutant）
    # cal 段為 golden 尾段、長度約 1/3（disjoint 於 mspc fit 的前 2/3）
    n = len(G)
    assert len(hi._fwer_block_cal_) == n - (2 * n) // 3


def test_l4_fit_on_full_golden_not_split():
    """mutant-kill（紅隊 A#4 的 L4 regression）：L4(drift) 須 fit 於**全 golden**（非前 2/3）——
    否則對非平穩後段誤報（golden FPR 0.04→0.12）。_fwer_drift_ 的 golden 分數樣本數＝全 golden。"""
    G = _ar1_golden()
    hi = HealthIndex().fit(G)
    hi.fwer_pvalues(G[:60])
    assert hi._fwer_drift_.Sg_.shape[0] == len(G)  # L4 fit 全 golden；改成 2/3 → 失敗
    # 對照：L2(mspc) 確實 fit 前 2/3（split 有作用於 L1/L2）
    assert hi._fwer_mspc_.mean_.shape[0] == G.shape[1]  # mspc 已 fit（健全性）


def test_iid_path_unchanged_backward_compat():
    """WHY（向後相容）：iid golden（block_len_=1）走原 shuffle split 路徑，不受 P2 影響、無 _fwer_block_cal_。"""
    rng = np.random.default_rng(3)
    G = rng.standard_normal((600, 6))  # iid → block_len_=1
    hi = HealthIndex().fit(G)
    assert hi.drift_.block_len_ == 1
    hi.fwer_pvalues(G[:60])
    assert hi._fwer_l2_block_ is False and hi._fwer_block_cal_ is None  # 走 iid 分支


def test_block_fallback_when_too_short_warns():
    """WHY（紅隊 B#4，block fallback 零覆蓋）：自相關但 golden 太短無法連續 split → 退回 in-sample + warn。"""
    G = _ar1_golden(n=40, p=6, rho=0.9)  # 自相關但短
    hi = HealthIndex().fit(G)
    if hi.drift_.block_len_ <= 1:
        pytest.skip("此短序列未觸發 block 路徑")
    import warnings

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        hi.fwer_pvalues(G[:20])
    if not hi._fwer_split_:  # 確實走 fallback
        assert hi._fwer_block_cal_ is None
        assert any("連續 split 停用" in str(x.message) for x in w)


@pytest.mark.skipif(not os.path.exists(_TEP_DATA), reason="TEP .mat 未下載")
def test_tep_l2_insample_optimism_fixed():
    """FPR 鎖（TEP-gated）：自相關 tep_tp 上，L2 fwer hold-out golden FPR 用 P2 out-of-sample null
    顯著低於 in-sample null（紅隊實證 0.44→0.04）。鎖住 P2 對 L2 的真實校準效果。"""
    from health_index.adapters import registry

    d, gt = registry.build("tep_tp", seed=0, drift_strength=0.7)
    cols = list(gt.x_columns)
    gidx = np.flatnonzero(np.asarray(gt.golden_mask))
    cut = gidx[0] + len(gidx) // 2
    Xfit = d.frame.iloc[gidx[gidx < cut]][cols].to_numpy()
    Xhold = d.frame.iloc[gidx[gidx >= cut]][cols].to_numpy()
    hi = HealthIndex().fit(Xfit)
    hi.fwer_pvalues(Xhold[:60])  # trigger
    a = hi.config.fwer_alpha
    w = 60

    def l2_fpr(cal_series):
        hits = nw = 0
        for i in range(0, len(Xhold) - w + 1, w):
            spe_x = hi._fwer_mspc_.spe(Xhold[i : i + w])
            p2 = hi._block_window_pvalue(hi._fwer_mspc_.spe(cal_series), float(np.mean(spe_x)), w)
            hits += p2 < a
            nw += 1
        return hits / nw

    fpr_p2 = l2_fpr(hi._fwer_block_cal_)  # out-of-sample（P2）
    fpr_insample = l2_fpr(hi._golden_)  # in-sample（mutant）
    assert fpr_p2 <= fpr_insample  # P2 不比 in-sample 差
    assert fpr_p2 <= 0.15  # L2 out-of-sample FPR 受控（紅隊實證 ~0.04）
