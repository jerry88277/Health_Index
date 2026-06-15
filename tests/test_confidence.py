"""C2. HealthIndex.confidence() 可信度指標 WHY 測試（Rule 9）。

WHY（使用者：『RI 是信心度指標，判斷健康指標之信心值』，改名不沿用 AVM RI）：confidence 回答
**『此窗 HI 判讀該信多少』**——基於 T² 操作域相似度（操作點在建模 golden 包絡內＝內插可信；包絡外＝
外推應保留）。取 AVM 相似度可靠度閘精神，但用穩健 T²（非數值不穩 GSI），且不沿用 AVM RI 雙模型法。

mutant-kill：把 confidence 還原成常數或直接回 health → test_confidence_drops_out_of_domain 失敗
（confidence 須隨 X 離域單調下降）。
"""

import numpy as np

from health_index.adapters import synthetic as syn
from health_index.health import HealthIndex


def _golden(seed=5, ds=0.8):
    d, gt = syn.generate(seed=seed, drift_strength=ds)
    cols = list(gt.x_columns)
    Xg = d.frame.loc[np.asarray(gt.golden_mask), cols].to_numpy()
    return HealthIndex().fit(Xg), Xg


def test_confidence_high_on_golden():
    """golden 在建模域內 → 可信度高（>0.8）、值域 (0,1]。"""
    hi, Xg = _golden()
    c = hi.confidence(Xg)
    assert 0.0 < c <= 1.0 and c > 0.8


def test_confidence_drops_out_of_domain():
    """marquee：X 離 golden 域越遠（T² 升）confidence 越低（單調）——外推時 surface 低可信。"""
    hi, Xg = _golden()
    sds = Xg.std(axis=0)
    cs = [hi.confidence(Xg + k * sds) for k in (0.0, 2.0, 5.0)]
    assert cs[0] > cs[1] > cs[2]      # 嚴格單調下降
    assert cs[0] > 0.8 and cs[2] < 0.5


def test_confidence_recovers_without_baseline():
    """韌性（紅隊防呆）：舊 pickle 無 _t2_mu_ 基線時由 self._golden_ 重算，不 AttributeError。"""
    hi, Xg = _golden()
    del hi._t2_mu_  # 模擬舊版 bundle（fit 前未存 T² 基線）
    assert 0.0 < hi.confidence(Xg) <= 1.0


def test_confidence_distinct_from_health_not_redundant():
    """marquee（紅隊 RT1-a 修正）：confidence(T²) 與 health 須**低相關**（非 GSI 版 r≈0.998 冗餘）。
    掃窗算兩者相關係數，應明顯 < 0.9——證 confidence 量「操作域」、health 量「偏離程度」不同軸。"""
    hi, Xg = _golden()
    d, gt = syn.generate(seed=5, drift_strength=0.8)
    X = d.frame[list(gt.x_columns)].to_numpy()
    w = 60
    hs = [hi.health_index(X[s : s + w]) for s in range(0, len(X) - w + 1, w)]
    cs = [hi.confidence(X[s : s + w]) for s in range(0, len(X) - w + 1, w)]
    r = abs(float(np.corrcoef(hs, cs)[0, 1]))
    assert r < 0.9  # T² 版低相關（實證 ~0.39）；GSI 版會 ~1.0 → 本測試殺死「退回 GSI」mutant
