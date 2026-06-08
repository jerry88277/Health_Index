"""TEP adapter WHY 測試（真實 TEP 正常資料 + 注入隱性飄移情境）。

marquee WHY：在真實 TEP 正常資料（Mode1/2/3 平穩 pool iid 重抽）+ 注入關係飄移的情境上，三條成功
判準成立——golden/clean 健康、drift 被多變量抓且**單變數 3σ 盲**、drift 明顯低於乾淨回歸。資料缺則 skip。

範圍誠實（Rule 12）：drift 為**注入**（已驗證真實 TEP 9 故障皆非單變數隱形）；clean 用 pool iid 重抽
消除 TEP 72h 內非平穩造成的假誤報。當注入飄移不再被多變量抓、或開始被單變數抓時，這些測試必須失敗。
"""

import os

import numpy as np
import pytest

DATA = os.path.join("data", "tep", "m1d00.mat")
pytestmark = pytest.mark.skipif(not os.path.exists(DATA), reason="TEP .mat 未下載（data/tep/）")

from health_index.adapters import tep  # noqa: E402
from health_index.health import HealthIndex  # noqa: E402


def _campaigns(drift_strength=0.7):
    ds, gt = tep.generate(drift_strength=drift_strength)
    cols = list(ds.x_columns)
    Xg = ds.frame.loc[gt.golden_mask, cols].to_numpy()
    a, b, g = gt.campaign_bounds[2]
    assert g == "A"
    Xc = ds.frame.iloc[a:b][cols].to_numpy()
    Xd = ds.frame.loc[gt.drift_mask, cols].to_numpy()
    return Xg, Xc, Xd


def test_tep_hidden_drift_caught_while_spc_blind():
    # 判準 1+2+3：golden/clean 健康、drift 被融合抓且告警、單變數 3σ 對注入飄移近乎盲
    Xg, Xc, Xd = _campaigns()
    hi = HealthIndex().fit(Xg)
    hg, hc, hd = hi.health_index(Xg), hi.health_index(Xc), hi.health_index(Xd)
    assert hg > 0.8 and hc > 0.8           # golden / 乾淨回歸健康
    assert hd < hc - 0.2                    # drift 明顯較低（區分乾淨 vs 殘留飄移）
    assert hi.is_alarm(Xd) and not hi.is_alarm(Xc) and not hi.is_alarm(Xg)
    gm, gs = Xg.mean(0), Xg.std(0) + 1e-9
    spc = (np.abs(Xd - gm) > 3 * gs).any(axis=1).mean()
    assert spc < 0.15                       # 單變數 SPC 對隱性（注入）飄移近乎盲（index 存在的理由）


def test_tep_drift_preserves_marginals():
    # WHY（鎖 SPC 盲根因）：注入只打亂相關、保各欄邊際 → drift 各欄 std ≈ golden（重抽同 pool）
    Xg, _, Xd = _campaigns()
    ratio = Xd.std(0) / (Xg.std(0) + 1e-9)
    assert np.all(np.abs(ratio - 1.0) < 0.4)   # 邊際大致保留（含 iid 重抽變異）


def test_tep_grades_and_reentry_structure():
    _, gt = tep.generate()
    assert [g for _, _, g in gt.campaign_bounds] == ["A", "B", "A", "C", "A"]


def test_tep_deterministic():
    a, _ = tep.generate()
    b, _ = tep.generate()
    assert np.array_equal(
        a.frame[list(a.x_columns)].to_numpy(), b.frame[list(b.x_columns)].to_numpy()
    )


# --- ② 保時序情境（time_preserving）：block-bootstrap 使連續乾淨回歸不誤報、殘留飄移仍偵測 ---
def _tp_campaigns(drift_strength=0.7):
    ds, gt = tep.generate(drift_strength=drift_strength, time_preserving=True)
    cols = list(ds.x_columns)
    b = gt.campaign_bounds
    seg = lambda i: ds.frame.iloc[b[i][0] : b[i][1]][cols].to_numpy()  # noqa: E731
    return ds.frame.loc[gt.golden_mask, cols].to_numpy(), seg(2), seg(4), seg(1)  # golden,clean,drift,B


def test_tep_time_preserving_clean_healthy_drift_detected():
    # marquee WHY（②）：保**真實時序/自相關**（不 iid 重抽）下，block-bootstrap 使乾淨連續回歸
    # **不誤報**、殘留隱性飄移仍被偵測——這正是先前（iid null）判為不可行、現經 ② 修正後可行的能力。
    # 當 block-bootstrap 失效（退回 iid null）時，乾淨連續窗會誤報 → 本測試必失敗。
    Xg, Xc, Xd, Xb = _tp_campaigns()
    hi = HealthIndex().fit(Xg)
    assert hi.drift_.block_len_ > 1            # 保序自相關 → 觸發 block 路徑（iid 才 =1）
    assert not hi.fwer_alarm(Xg)              # golden 健康
    assert not hi.fwer_alarm(Xc)              # 乾淨連續回歸不誤報（②核心修正）
    assert hi.fwer_alarm(Xd)                  # 殘留隱性飄移被偵測
    assert hi.fwer_alarm(Xb)                  # 換產品 B（真分佈位移）仍被偵測（未失鑑別力）


def test_tep_time_preserving_drift_is_l2_spe_while_spc_and_l4_blind():
    # WHY（誠實歸因，②）：保時序下注入關係飄移由 **L2 SPE 殘差空間** 抓；保邊際 → 單變數 3σ 與 L4
    # 分數空間皆盲（與 iid 重抽情境「L4 主抓」相反，誠實標記轉移）。鎖住攻擊面：若改成 L4 主抓或
    # 宣稱單變數抓得到，本測試必失敗。
    Xg, _, Xd, _ = _tp_campaigns()
    hi = HealthIndex().fit(Xg)
    pv = hi.fwer_pvalues(Xd)
    assert pv["L2"] <= hi.config.fwer_alpha    # L2 SPE 抓到殘留飄移（主訊號）
    assert pv["L4"] > hi.config.fwer_alpha     # L4 分數空間盲（保邊際 → window-vs-window 看不到）
    gm, gs = Xg.mean(0), Xg.std(0) + 1e-9
    assert (np.abs(Xd - gm) > 3 * gs).any(axis=1).mean() < 0.15  # 單變數 SPC 盲
