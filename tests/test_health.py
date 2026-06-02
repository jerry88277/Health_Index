"""Health Index 融合 + re-entry WHY 測試（Rule 9）。

marquee WHY（成功判準 1+3）：融合 0–1 Health Index 對 golden / 乾淨換線回歸維持**高分（健康）**，
對殘留 drift 的 A campaign 掉到**低分並告警**——把四層偵測器收斂成單一可解讀的健康度，且
告警在隱性飄移上成立（單變數 SPC 看不到）。當融合喪失鑑別力時測試必須失敗。
"""

import numpy as np
import pytest

from health_index import interface as I
from health_index.adapters import synthetic as syn
from health_index.health import HealthIndex, detect_reentry_campaigns
from health_index.preprocess import segment as seg


def _campaigns(seed):
    ds, gt = syn.generate(seed=seed, drift_strength=1.2)
    cols = ds.x_columns
    Xg = ds.frame.loc[gt.golden_mask, list(cols)].to_numpy()
    a, b, g = gt.campaign_bounds[2]
    assert g == "A"
    Xc = ds.frame.iloc[a:b][list(cols)].to_numpy()
    Xd = ds.frame.loc[gt.drift_mask, list(cols)].to_numpy()
    return Xg, Xc, Xd


@pytest.mark.parametrize("seed", [5, 7, 11, 13, 17])
def test_health_index_discriminates_and_alarms(seed):
    Xg, Xc, Xd = _campaigns(seed)
    hi = HealthIndex().fit(Xg)
    hi_g, hi_c, hi_d = hi.health_index(Xg), hi.health_index(Xc), hi.health_index(Xd)
    assert hi_g > 0.8 and hi_c > 0.8           # golden / 乾淨回歸維持高分（判準 1）
    assert hi_d < hi_c - 0.2                    # drift 明顯較低（判準 3）
    assert hi_d < hi.config.hi_alarm_threshold  # 融合分數本身即告警（不靠硬閘；鎖融合鑑別力，紅隊 R1）
    # 逐層 ablation：鎖每層對鑑別的承載貢獻（紅隊 🔴-1：防旁路 L2/L4 仍綠）
    sd, sc = hi.subscores(Xd), hi.subscores(Xc)
    assert sd["L2"] < sc["L2"] - 0.3            # L2（隱性飄移主訊號）在 drift 上顯著低
    assert sd["L4"] < sc["L4"] - 0.3            # L4 漂移子分數在 drift 上顯著低
    assert hi.is_alarm(Xd) is True             # drift 告警
    assert hi.is_alarm(Xg) is False and hi.is_alarm(Xc) is False  # golden/clean 不告警


@pytest.mark.parametrize("seed", [5, 7, 11, 13, 17])
def test_hi_alarms_where_univariate_spc_blind(seed):
    # WHY（成功判準 2，紅隊 🔴-3）：隱性飄移對單變數 3σ SPC 隱形，但 HI 告警 → 勝過單變數 SPC
    Xg, _, Xd = _campaigns(seed)
    gm, gs = Xg.mean(0), Xg.std(0)
    spc_drift = (np.abs(Xd - gm) > 3 * gs).any(axis=1).mean()
    hi = HealthIndex().fit(Xg)
    assert spc_drift < 0.1                       # 單變數 SPC 對 drift 幾乎不告警（盲）
    assert hi.health_index(Xd) < hi.config.hi_alarm_threshold  # HI 卻判不健康（融合鑑別）


def test_hard_gate_path_alarms_independent_of_fusion(monkeypatch):
    # WHY（H8 安全網機制）：即使融合分數高(看似健康)，任一硬閘觸發 → is_alarm True（致命破壞不被
    # 融合平均稀釋）。誠實註(Rule 12)：合成資料漂移使硬閘與融合同時動，無法自然產生「融合漏、硬閘
    # 獨抓」case；此為機制性驗證，自然場景待 TEP 真實單層致命故障。
    Xg, _, _ = _campaigns(5)
    hi = HealthIndex().fit(Xg)
    monkeypatch.setattr(hi, "health_index", lambda X: 0.99)         # 融合很高（會漏）
    monkeypatch.setattr(hi, "hard_gates", lambda X: {"L2": True})   # 但硬閘破限
    assert hi.is_alarm(Xg) is True
    monkeypatch.setattr(hi, "hard_gates", lambda X: {"L2": False})
    assert hi.is_alarm(Xg) is False             # 無硬閘 + 融合高 → 不告警（證明硬閘是告警來源）


def test_golden_fpr_multi_seed():
    # WHY（DoD#1，紅隊 🟡）：golden 期多 seed hold-out 不誤報（型一受控，非單一 seed）
    alarms = 0
    for seed in range(6):
        ds, gt = syn.generate(seed=seed)
        Xg = ds.frame.loc[gt.golden_mask, list(ds.x_columns)].to_numpy()
        h = len(Xg) // 2
        alarms += int(HealthIndex().fit(Xg[:h]).is_alarm(Xg[h:]))  # hold-out
    assert alarms <= 1   # 6 seed 至多 1 次（容忍帶）


def test_health_index_in_unit_range():
    Xg, _, Xd = _campaigns(5)
    hi = HealthIndex().fit(Xg)
    for X in (Xg, Xd):
        v = hi.health_index(X)
        assert 0.0 <= v <= 1.0


def test_health_index_monotone_with_anomaly():
    # 越離域/越異常 → Health Index 越低（單調）
    Xg, _, _ = _campaigns(5)
    hi = HealthIndex().fit(Xg)
    assert hi.health_index(Xg) > hi.health_index(Xg + 3.0) > hi.health_index(Xg + 10.0)


def test_hard_gate_catches_drift():
    # 單層硬閘：drift campaign 至少觸發一個硬閘（不被融合平均稀釋）
    Xg, Xc, Xd = _campaigns(5)
    hi = HealthIndex().fit(Xg)
    assert any(hi.hard_gates(Xd).values())
    assert not any(hi.hard_gates(Xc).values())  # 乾淨回歸不觸發硬閘


def test_detect_reentry_campaigns():
    # WHY（觸發語義）：re-entry = 非 A 之後的第一段 A；第一個 golden A 不算
    ds, gt = syn.generate(seed=5)
    fr = seg.segment(ds)
    ds2 = I.ProcessDataset(frame=fr, x_columns=ds.x_columns, name="t")
    reentry = detect_reentry_campaigns(ds2)
    assert reentry == [2, 4]   # A_clean(after B), A_drift(after C)
    assert 0 not in reentry    # 第一個 golden A 不是 re-entry


def test_deterministic():
    Xg, _, Xd = _campaigns(5)
    hi = HealthIndex().fit(Xg)
    assert hi.health_index(Xd) == hi.health_index(Xd)
