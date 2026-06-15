"""B. CCPP 真實非化工含 Y adapter WHY 測試（Rule 9）。

WHY（泛化證據 + 本 index 存在理由於真實資料）：
- CCPP＝**真實、非化工、含真實連續 Y（PE 淨發電量）**——補足 synthetic/TEP 皆化工或合成、uci 無 Y 之缺口。
- ``ccpp_covert`` 在**真實特徵基底**注入隱性多變量漂移（hub 欄部分置換去相關）：**每變數仍在規格內
  （單變數 SPC 盲）、僅多變量相關結構偏移 → SPE 升**。這正是本 index 存在的理由（DoD #2）。
  **當 covert 注入退化成單變數可見（marginal 被破壞）時，下列 marquee 測試失敗。**

資料未下載則 skip（data/ 為 gitignore；見 ccpp._ensure_csv 下載指引）。
"""

import numpy as np
import pytest

from health_index.adapters import ccpp, registry
from health_index.health import HealthIndex


@pytest.fixture(scope="module")
def real():
    try:
        return ccpp.load(covert=False)
    except FileNotFoundError:
        pytest.skip("CCPP 資料未下載（data/ccpp 缺 csv/xlsx）")


@pytest.fixture(scope="module")
def covert():
    try:
        return ccpp.load(covert=True)
    except FileNotFoundError:
        pytest.skip("CCPP 資料未下載（data/ccpp 缺 csv/xlsx）")


def test_real_shape_and_dense_y(real):
    """真實集：4 維 X、9568 列、Y(PE) 真實且 dense（每列皆有，非 NaN）、drift_mask=None（誠實無標註）。"""
    ds, gt = real
    assert ds.name == "ccpp"
    assert gt.x_columns == ("AT", "V", "AP", "RH")
    assert len(ds.frame) == 9568
    assert int(ds.frame["y_value"].notna().sum()) == 9568  # 真實連續 Y，無缺
    assert gt.drift_mask is None                            # 誠實：shuffle 後無標註漂移
    assert 0 < int(gt.golden_mask.sum()) < len(ds.frame)


def test_registry_exposes_both_variants():
    """registry 註冊 ccpp / ccpp_covert，且 ccpp_covert 拒絕 covert=False（fail-loud 防語意矛盾）。"""
    assert "ccpp" in registry.available() and "ccpp_covert" in registry.available()
    with pytest.raises(ValueError):
        registry.build("ccpp_covert", covert=False)


def test_covert_marginals_preserved_others_untouched(covert):
    """covert 注入為 X-only 且 hub 欄**邊際多重集精確保留**（置換）、非 hub 欄完全不動 → 結構性
    保證單變數 SPC 對 hub 盲。對照純真實集逐欄比對。"""
    dc, gtc = covert
    dr, _ = ccpp.load(covert=False)
    hub = gtc.covert_column
    assert hub in gtc.x_columns
    dm = gtc.drift_mask
    # hub 欄 drift 段排序後完全相同（精確置換 → 邊際不變）
    assert np.allclose(np.sort(dr.frame.loc[dm, hub].to_numpy()), np.sort(dc.frame.loc[dm, hub].to_numpy()))
    # 非 hub 欄完全未動
    for c in gtc.x_columns:
        if c != hub:
            assert np.allclose(dr.frame[c].to_numpy(), dc.frame[c].to_numpy())


def test_covert_is_spc_blind_but_spe_catches(covert):
    """marquee（Rule 9）：covert drift 段 **單變數 SPC 盲（每欄越限率≈golden）但 SPE 大幅升**——
    多變量殘差早於單變數抓到。若 covert 退化成 marginal 可見 → univ 越限率升 → 本測試失敗。"""
    dc, gtc = covert
    cols = list(gtc.x_columns)
    Xg = dc.frame.loc[gtc.golden_mask, cols].to_numpy()
    Xd = dc.frame.loc[gtc.drift_mask, cols].to_numpy()
    hi = HealthIndex().fit(Xg)
    mu, sg = Xg.mean(0), Xg.std(0)
    uni = lambda X: (np.abs((X - mu) / sg) > 3).mean(0)  # noqa: E731 逐欄 3σ 越限率
    uni_drift_max = float(uni(Xd).max())
    spe_lim = hi.mspc_.spe_lim_
    spe_exc_golden = float((hi.mspc_.spe(Xg) > spe_lim).mean())
    spe_exc_drift = float((hi.mspc_.spe(Xd) > spe_lim).mean())
    assert uni_drift_max < 0.05                       # 單變數 SPC 盲（每欄仍在規格內）
    assert spe_exc_golden < 0.05                      # SPE 在 golden 校準正常（不誤報）
    assert spe_exc_drift > 0.3                         # SPE 在 drift 大幅升（多變量抓到）
    assert spe_exc_drift > uni_drift_max + 0.2         # 多變量 ≫ 單變數（早於 SPC 的量化）


def test_covert_golden_healthy_drift_alarms(covert):
    """DoD：covert 集上 golden 健康（HI 高、不告警），drift 段告警（HI 低）。"""
    dc, gtc = covert
    cols = list(gtc.x_columns)
    Xg = dc.frame.loc[gtc.golden_mask, cols].to_numpy()
    Xd = dc.frame.loc[gtc.drift_mask, cols].to_numpy()
    hi = HealthIndex().fit(Xg)
    assert hi.health_index(Xg) > hi.config.hi_alarm_threshold and not hi.is_alarm(Xg)
    assert hi.health_index(Xd) < hi.config.hi_alarm_threshold and hi.alarm(Xd, compute_fwer=False)
