"""B3 AC-6 FWER WHY 測試（Rule 9）。

marquee WHY（AC-6，紅隊 N2/N6）：``fwer_alarm`` 把各層對 golden-A null 的 p-value 經 **Holm 校正**成
**單一決策點**，使 golden 誤報率 ≤ ``config.fwer_alpha``——對乾淨/golden（每變數在規格內、無真實
飄移）**不誤報**，同時隱性 drift 仍被抓。裸 OR（``is_alarm``）無此 FWER 保證。當 FWER 控制失效
（golden 誤報率爆掉）或 drift 漏抓時，測試必須失敗。

範圍誠實（Rule 12）：FWER p-value 以 golden split 校準（fit/calib disjoint）+ permutation 兩樣本，
避開 in-sample 控制限低估（M3 in-sample≈2α vs hold-out≈4α gap）。p-value 仍有蒙地卡羅變異 → 以
容忍帶斷言（紅隊 H7）。
"""

import numpy as np
import pytest

from health_index.adapters import synthetic as syn
from health_index.health import HealthIndex, _holm_reject


def _gcd(seed, n=400):
    ds, gt = syn.generate(seed=seed, drift_strength=1.2, n_per_campaign=n)
    cols = list(ds.x_columns)
    Xg = ds.frame.loc[gt.golden_mask, cols].to_numpy()
    a, b, _ = gt.campaign_bounds[2]
    Xc = ds.frame.iloc[a:b][cols].to_numpy()           # clean re-entry（獨立健康抽樣，同 W、無飄移）
    Xd = ds.frame.loc[gt.drift_mask, cols].to_numpy()
    return Xg, Xc, Xd


def test_holm_reject_controls_family():
    # 全 null（大 p）→ 無拒絕；單一極小 p → 只拒該層（單一決策點的 FWER step-down 邏輯）
    assert _holm_reject({"L1": 0.4, "L2": 0.7, "L4": 0.9}, 0.05) == {"L1": False, "L2": False, "L4": False}
    rej = _holm_reject({"L1": 0.001, "L2": 0.7, "L4": 0.9}, 0.05)
    assert rej["L1"] is True and not rej["L2"] and not rej["L4"]
    # 邊界：m=3、α=0.05 → 最小 p 須 ≤ α/3 才拒（Holm 第一步）
    assert not any(_holm_reject({"L1": 0.02, "L2": 0.5, "L4": 0.5}, 0.05).values())  # 0.02 > 0.0167
    assert _holm_reject({"L1": 0.01, "L2": 0.5, "L4": 0.5}, 0.05)["L1"] is True       # 0.01 < 0.0167


@pytest.mark.parametrize("seed", [0, 1, 2, 3])
def test_drift_still_caught(seed):
    # AC 非回歸：單一決策點對隱性 drift 仍告警（FWER 控制不可犧牲偵測力）
    Xg, _, Xd = _gcd(seed)
    hi = HealthIndex().fit(Xg)
    assert hi.fwer_alarm(Xd) is True


def test_golden_fpr_controlled_and_beats_bare_or():
    # marquee WHY（AC-6，紅隊 N2）：clean re-entry（獨立健康、每變數在規格內）多窗下，Holm 單一決策點
    # 把 golden 誤報率壓在 ≤α，而**裸 OR（任一 p<α 即告警）失控 >α**——這正是 B3 取代 OR 的理由。
    # 同一組 p-value 同時導出兩種決策：若把 fwer_alarm 退化成裸 OR（mutant），此測試必失敗（Rule 9）。
    holm_fp = oror_fp = nwin = 0
    alpha = 0.05
    for seed in range(8):
        Xg, Xc, _ = _gcd(seed)
        hi = HealthIndex().fit(Xg)
        for i in range(0, len(Xc) - 60 + 1, 60):
            p = hi.fwer_pvalues(Xc[i:i + 60])
            nwin += 1
            holm_fp += int(any(_holm_reject(p, alpha).values()))   # Holm 單一決策點（實測 ~0.02）
            oror_fp += int(any(v < alpha for v in p.values()))     # 裸 OR mutant（實測 ~0.10）
    holm_fpr, oror_fpr = holm_fp / nwin, oror_fp / nwin
    assert holm_fpr <= alpha                # FWER 真受控 ≤α（非 0.12 鬆帶）
    assert oror_fpr > alpha                 # 裸 OR 失控 >α
    assert oror_fpr >= holm_fpr + 0.04      # 兩者明顯分離（殺 Holm→OR mutant）


def test_holm_strictly_stricter_than_bare_or():
    # WHY（B3 存在理由，確定性 mutant-killer）：存在 p 向量使裸 OR 告警、Holm 不告警。
    p = {"L1": 0.03, "L2": 0.04, "L4": 0.9}     # 兩個 <0.05
    assert any(v < 0.05 for v in p.values())            # 裸 OR：告警
    assert not any(_holm_reject(p, 0.05).values())      # Holm：min 0.03 > 0.05/3 → 不告警


def test_fwer_pvalues_valid_and_drift_significant():
    Xg, _, Xd = _gcd(5)
    hi = HealthIndex().fit(Xg)
    pg, pd = hi.fwer_pvalues(Xg), hi.fwer_pvalues(Xd)
    for v in list(pg.values()) + list(pd.values()):
        assert 0.0 < v <= 1.0                         # 合法 p-value 範圍
    assert pd["L2"] < 0.05 and pd["L4"] < 0.05        # drift 的隱性飄移主訊號（L2/L4）顯著


def test_split_calibration_enabled():
    # WHY：golden 夠大時應啟用 split 校準（out-of-sample null），否則 FWER 會 in-sample 低估而失控。
    # （lazy：校準在首次呼叫 fwer 時才建，Rule 6 不拖慢共同路徑）
    hi = HealthIndex().fit(_gcd(5)[0])
    assert not hasattr(hi, "_fwer_split_")     # fit 後尚未建（lazy）
    hi.fwer_pvalues(_gcd(5)[2])                 # 觸發 lazy 校準
    assert hi._fwer_split_ is True


def test_small_golden_warns_and_falls_back():
    # WHY（Rule 12 fail loud）：golden 太小無法 split → FWER 退 in-sample 校準，須發 RuntimeWarning
    # 讓呼叫端知道「AC-6 此時不保證 ≤α」，而非靜默失準。
    rng = np.random.default_rng(0)
    hi = HealthIndex().fit(rng.standard_normal((25, 8)))   # n=25 < 3·min_samples_per_dim
    with pytest.warns(RuntimeWarning, match="FWER split"):
        hi.fwer_pvalues(rng.standard_normal((25, 8)))
    assert hi._fwer_split_ is False


def test_fwer_deterministic():
    Xg, _, Xd = _gcd(5)
    hi = HealthIndex().fit(Xg)
    assert hi.fwer_alarm(Xd) == hi.fwer_alarm(Xd)
    assert hi.fwer_pvalues(Xd) == hi.fwer_pvalues(Xd)


# --- ① block-aware L2 FWER：消自相關 in-sample 過度拒絕 ---
def _ar1(n, phi, rng, p=1):
    x = np.zeros((n, p))
    for t in range(1, n):
        x[t] = phi * x[t - 1] + np.sqrt(1 - phi**2) * rng.standard_normal(p)
    return x


def test_l2_block_window_pvalue_controls_autocorr_fp_keeps_power():
    # marquee WHY（①）：自相關序列下，window-vs-window 區塊 p-value 對**同分佈 in-sample 窗**的 FP≈名目，
    # 而 permutation（假 iid，mutant）顯著**過度拒絕**；對位移窗仍顯著（功效不犧牲）。鎖住 ② 揭露的
    # L2 既有債之修正——若把 L2 退回純 permutation，in-sample FWER 失控（實測 0.22≫α）。
    hi = HealthIndex()
    rng = np.random.default_rng(0)
    g = _ar1(6000, 0.9, rng).ravel()
    s = 300
    starts = list(range(0, 6000 - s, 120))
    block_fp = float(np.mean([hi._block_window_pvalue(g, g[a : a + s].mean(), s) <= 0.05 for a in starts]))
    ref = g[3000:4000]
    perm_fp = float(np.mean([hi._perm_two_sample(ref, g[a : a + s]) <= 0.05 for a in starts]))
    assert block_fp <= 0.12                 # 區塊化：FP 受控 ≈名目（實測 0.062）
    assert perm_fp > block_fp + 0.08        # permutation 假 iid → 過度拒絕（實測 0.167；殺「不修」mutant）
    assert hi._block_window_pvalue(g, g.mean() + 3 * g.std(), s) <= 0.05  # 位移窗仍顯著（功效）


def test_l2_fwer_block_active_only_under_autocorrelation():
    # WHY（向後相容不變式）：iid golden（synthetic）→ L2 維 permutation（_fwer_l2_block_=False，逐位元
    # 相容既有 fwer 測試）；自相關 golden → 切 window-vs-window 區塊路徑（_fwer_l2_block_=True）。
    hi_iid = HealthIndex().fit(_gcd(5)[0])   # synthetic（iid）
    hi_iid.fwer_pvalues(_gcd(5)[2])          # 觸發 lazy 校準
    assert hi_iid._fwer_l2_block_ is False
    rng = np.random.default_rng(1)
    ar = _ar1(800, 0.9, rng, p=6)            # 強自相關多變量 golden
    hi_ac = HealthIndex().fit(ar)
    hi_ac.fwer_pvalues(ar[:200])
    assert hi_ac._fwer_l2_block_ is True
