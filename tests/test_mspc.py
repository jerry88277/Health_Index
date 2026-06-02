"""L2 MSPC WHY 測試（Rule 9）。

marquee WHY：純多變量隱性飄移（每變數在單變數規格內、僅相關結構偏移）必須被 SPE 抓到、
卻被逐變數 3σ 管制圖漏掉——這正是整個 Health_Index 存在的理由。當此性質消失（SPE 不再抓到、
或單變數圖開始抓到）時，以下測試必須失敗。
"""

import numpy as np
import pytest

from health_index import interface as I
from health_index.adapters import synthetic as syn
from health_index.detectors.mspc import MSPCModel


def _seg(ds, mask, cols):
    return ds.frame.loc[mask, list(cols)].to_numpy()


@pytest.mark.parametrize("seed", [5, 18, 29, 33, 34])
def test_spe_catches_hidden_drift_univariate_misses(seed):
    # marquee：跨 seed 容忍帶（非單一幸運點值，紅隊 D6）；drift_strength 調強留 margin。
    ds, gt = syn.generate(seed=seed, drift_strength=1.5)
    cols = ds.x_columns
    Xg = _seg(ds, gt.golden_mask, cols)
    Xd = _seg(ds, gt.drift_mask, cols)
    m = MSPCModel().fit(Xg)

    spe_detect = (m.spe(Xd) > m.spe_lim_).mean()
    t2_detect = (m.t2(Xd) > m.t2_lim_).mean()
    gmean, gstd = Xg.mean(0), Xg.std(0)
    uni_detect = (np.abs(Xd - gmean) > 3 * gstd).any(axis=1).mean()

    assert uni_detect < 0.1                      # 單變數 3σ 漏抓（合成 drift 列範數守恆的數學保證）
    assert spe_detect > 0.3                       # SPE 對隱性飄移穩健偵測（跨 seed 實證下限 0.45）
    assert spe_detect > 5 * (uni_detect + 1e-6)  # SPE 遠勝單變數
    assert t2_detect < spe_detect                 # 飄移落殘差空間：SPE 抓、T² 抓不到（SPE 專屬性）


def test_control_limits_nondegenerate_insample_fa_optimistic():
    # 誠實註（紅隊 N2/H7）：in-sample 經驗 (1−α) 分位 → FA ~2α，屬【樂觀低估】（同批建模又評分），
    # 非型一控制證明——hold-out 實測 ~4α。真型一控制（hold-out/block-bootstrap/conformal）為 TODO
    # （見 N2，已開 backlog task）。此處僅驗控制限非退化 + in-sample FA 在樂觀低位。
    ds, gt = syn.generate(seed=5)
    Xg = _seg(ds, gt.golden_mask, ds.x_columns)
    m = MSPCModel().fit(Xg)
    assert m.t2_lim_ > 0 and m.spe_lim_ > 0                    # 控制限非退化
    assert m.is_anomaly(Xg).mean() < 3 * m.config.mspc_alpha  # in-sample（樂觀）~2α


def test_rbc_localizes_single_sensor_fault():
    # WHY: RBC 把 SPE 異常反解到肇因感測器，對單故障正確定位（Alcala&Qin 保證）。
    # 誠實註（Rule 12）：本合成資料各感測器殘差比例相近，raw 殘差亦能定位；RBC 消 smearing
    # 的優勢在殘差比例異質/多故障時才顯著（待真實資料驗證）。此處驗證「定位正確 + RBC 公式」。
    ds, gt = syn.generate(seed=5)
    Xg = _seg(ds, gt.golden_mask, ds.x_columns)
    m = MSPCModel().fit(Xg)
    x = Xg[0].copy()
    x[3] += 12.0  # 注入 sensor 3 故障
    rbc = m.rbc_spe(x[None, :])[0]
    assert int(rbc.argmax()) == 3  # 定位正確

    # RBC 公式 = resid²/C̃_jj（≠ raw 殘差平方；鎖 Alcala&Qin 實作，殺「RBC→raw」mutation）
    resid = (m._std(x[None, :]) @ m.Ctilde_)[0]
    expected = resid**2 / np.diag(m.Ctilde_)
    assert np.allclose(rbc, expected)
    assert not np.allclose(rbc, resid**2)  # 與 raw 確實不同（/C̃_jj 生效）


def test_t2_or_spe_flags_grade_B():
    # grade B 操作點位移：T²/SPE 至少一者升高（多變量域偵測）
    ds, gt = syn.generate(seed=5)
    Xg = _seg(ds, gt.golden_mask, ds.x_columns)
    m = MSPCModel().fit(Xg)
    Xb = ds.frame.loc[ds.frame[I.GRADE_LABEL] == "B", list(ds.x_columns)].to_numpy()
    assert m.is_anomaly(Xb).mean() > 0.8


def test_gsi_positive_and_elevated_for_ood():
    ds, gt = syn.generate(seed=5)
    Xg = _seg(ds, gt.golden_mask, ds.x_columns)
    m = MSPCModel().fit(Xg)
    assert (m.gsi(Xg) >= 0).all()
    assert m.gsi(Xg + 10.0).mean() > m.gsi(Xg).mean()


def test_deterministic_fit():
    ds, gt = syn.generate(seed=5)
    Xg = _seg(ds, gt.golden_mask, ds.x_columns)
    m1, m2 = MSPCModel().fit(Xg), MSPCModel().fit(Xg)
    assert m1.spe_lim_ == m2.spe_lim_ and m1.t2_lim_ == m2.t2_lim_
    assert m1.k_ == m2.k_
