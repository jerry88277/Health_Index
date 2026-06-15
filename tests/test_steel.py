"""D. Steel Industry Energy 真實非化工含 Y adapter WHY 測試（Rule 9）。

WHY：第四類泛化資料集，與 CCPP 互補——**真實非化工含 Y + 真實時序**（CCPP 為 shuffle 無時序）。
``steel_covert`` 在真實特徵基底注入隱性多變量漂移（hub 欄部分置換去相關）：每變數仍在規格內（單變數
SPC 盲）、僅多變量相關偏移 → SPE 升。退化成單變數可見時 marquee 測試失敗。

資料未下載則 skip（data/ gitignore；見 steel._ensure_csv 下載指引）。
"""

import numpy as np
import pytest

from health_index.adapters import registry, steel
from health_index.health import HealthIndex


@pytest.fixture(scope="module")
def real():
    try:
        return steel.load(covert=False)
    except FileNotFoundError:
        pytest.skip("Steel 資料未下載（data/steel 缺 csv）")


@pytest.fixture(scope="module")
def covert():
    try:
        return steel.load(covert=True)
    except FileNotFoundError:
        pytest.skip("Steel 資料未下載（data/steel 缺 csv）")


def test_real_shape_dense_y_real_time(real):
    """真實集：4 維電氣 X、35040 列、Y(Usage_kWh) dense、drift_mask=None、**真實 15 分鐘時序**（異於 CCPP）。"""
    ds, gt = real
    assert ds.name == "steel"
    assert gt.x_columns == ("lag_react", "lead_react", "lag_pf", "lead_pf")
    assert len(ds.frame) == 35040
    assert int(ds.frame["y_value"].notna().sum()) == 35040
    assert gt.drift_mask is None
    dt = ds.frame["timestamp"].diff().dropna().dt.total_seconds()
    assert (dt == 900).mean() > 0.95  # 95%+ 間隔為 900 秒（真實 15 分鐘鏈）


def test_registry_exposes_both_variants():
    assert "steel" in registry.available() and "steel_covert" in registry.available()
    with pytest.raises(ValueError):
        registry.build("steel_covert", covert=False)


def test_covert_marginals_preserved_others_untouched(covert):
    """covert 為 X-only 且 hub 欄邊際多重集精確保留（置換）、非 hub 欄不動 → 單變數 SPC 對 hub 結構性盲。"""
    dc, gtc = covert
    dr, _ = steel.load(covert=False)
    hub = gtc.covert_column
    dm = gtc.drift_mask
    assert np.allclose(np.sort(dr.frame.loc[dm, hub].to_numpy()), np.sort(dc.frame.loc[dm, hub].to_numpy()))
    for c in gtc.x_columns:
        if c != hub:
            assert np.allclose(dr.frame[c].to_numpy(), dc.frame[c].to_numpy())


def test_covert_is_spc_blind_but_spe_catches(covert):
    """marquee（Rule 9）：covert drift 段單變數 SPC 盲（每欄越限率≈golden）但 SPE 大幅升——多變量早於單變數。"""
    dc, gtc = covert
    cols = list(gtc.x_columns)
    Xg = dc.frame.loc[gtc.golden_mask, cols].to_numpy()
    Xd = dc.frame.loc[gtc.drift_mask, cols].to_numpy()
    hi = HealthIndex().fit(Xg)
    mu, sg = Xg.mean(0), Xg.std(0)
    uni = lambda X: (np.abs((X - mu) / sg) > 3).mean(0)  # noqa: E731
    spe_lim = hi.mspc_.spe_lim_
    assert float(uni(Xd).max()) < 0.05                                  # 單變數 SPC 盲
    assert float((hi.mspc_.spe(Xg) > spe_lim).mean()) < 0.05            # golden SPE 校準正常
    assert float((hi.mspc_.spe(Xd) > spe_lim).mean()) > 0.15            # drift SPE 大幅升（多變量抓到）
    assert float((hi.mspc_.spe(Xd) > spe_lim).mean()) > float(uni(Xd).max()) + 0.1


def test_covert_confidence_high_while_health_drops(covert):
    """C2 互補（confidence(T²)）：covert 隱性飄移＝相關斷但操作點在包絡內 → health 低（偵測到）、
    confidence 高（可信告警，非外推）。"""
    dc, gtc = covert
    cols = list(gtc.x_columns)
    Xg = dc.frame.loc[gtc.golden_mask, cols].to_numpy()
    Xd = dc.frame.loc[gtc.drift_mask, cols].to_numpy()
    hi = HealthIndex().fit(Xg)
    assert hi.health_index(Xd) < hi.config.hi_alarm_threshold   # 偵測到隱性飄移
    assert hi.confidence(Xd) > 0.8                              # 操作點在包絡內 → 高可信
    assert hi.confidence(Xg) > 0.8


def test_demo_soft_sensor_on_real_dense_y(real, tmp_path):
    """C2（真實連續 Y）：Steel dense Y → bundle 帶 YHealthIndex；window_detail golden 窗給 Ŷ + CP + map_health。"""
    from health_index.deploy import demo

    m = demo.build_and_save_model("steel", models_dir=str(tmp_path), created_at="t")
    assert m["has_y_health"] is True
    d = demo.window_detail(m["bundle_path"], "steel", 0, 60, compute_fwer=False)
    ss = d["soft_sensor"]
    assert ss["available"] and ss["cp_available"] is True   # golden 14016 > cp_min_calibration=200
    assert ss["n_y_obs"] == 60 and ss["map_health"] is not None
    assert 0.0 < d["confidence"] <= 1.0
