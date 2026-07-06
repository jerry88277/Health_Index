"""L2 MSPC 數值護欄 WHY 測試（Rule 9，風險稽核 rank-9）。

marquee WHY：確定性數學（Rule 5）是本系統賣點——但 T² 求逆/RBC 除殘差變異在小 n/共線下若
產生 inf/nan 又被靜默傳下去，會給出「自信的錯誤」健康分數/歸因（比 crash 更糟）。護欄：
(a) 非有限**輸出** fail-loud（不靜默把 nan 當健康）；(b) 病態 golden 於 fit 時 surface 條件數
（誠實揭露可信度下降）；(c) 鎖住「RBC 退化自消」的數學事實——Ctilde 為投影，Ctilde_jj→0
⟺ 該欄整列→0 ⟺ resid_j→0，故 RBC_j→0（非 inf）；這保證退化欄**不會**被 argsort 排到首位
（風險稽核擔心的 garbage-first 對正確投影不成立，但仍以 fail-loud 防數值雜訊放大）。
"""

import warnings

import numpy as np
import pytest

from health_index.detectors.mspc import MSPCModel


def _rank_deficient_golden(n=200, seed=0):
    """x0,x1 獨立 + x2=x0（精確共線）→ 保留 {x0+x2, x1}、殘差方向 {x0−x2}；
    x1 落在保留 PC、Ctilde_11≈0（退化、無殘差容量）；x0/x2 各 0.5 殘差容量。"""
    rng = np.random.default_rng(seed)
    x0 = rng.normal(size=n)
    x1 = rng.normal(size=n)
    return np.column_stack([x0, x1, x0])


def test_rbc_finite_and_degenerate_column_self_neutralizes():
    X = _rank_deficient_golden()
    m = MSPCModel().fit(X)
    diag = np.diag(m.Ctilde_)
    assert diag[1] < 1e-6                            # x1 退化（Ctilde_11≈0）
    q = X.mean(axis=0).copy()
    q[0] += 5.0                                      # 只動 x0 → 破壞 x0=x2 → 殘差落在 (x0−x2)
    rbc = m.rbc_spe(q.reshape(1, -1))
    assert np.isfinite(rbc).all()                   # 無 inf/nan
    assert rbc[0, 1] == pytest.approx(0.0, abs=1e-6)  # 退化欄自消為 0（非 garbage-first）
    assert int(np.argmax(rbc[0])) in (0, 2)         # 歸因到破壞關係的 x0/x2，非退化 x1


def test_nonfinite_output_fails_loud():
    X = _rank_deficient_golden(seed=1)
    m = MSPCModel().fit(X)
    bad = X[:1].copy()
    bad[0, 0] = np.inf                              # 非有限輸入 → 不得靜默回 nan
    with pytest.raises((ValueError, FloatingPointError)):
        m.rbc_spe(bad)
    with pytest.raises((ValueError, FloatingPointError)):
        m.t2(bad)


def test_illconditioned_golden_surfaces_warning():
    # 近奇異 golden（一欄近乎另一欄）→ fit 應 surface 條件數（誠實，非靜默）
    rng = np.random.default_rng(2)
    a = rng.normal(size=300)
    X = np.column_stack([a, a + 1e-7 * rng.normal(size=300), rng.normal(size=300)])
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        MSPCModel().fit(X)
    assert any("條件數" in str(x.message) or "cond" in str(x.message).lower() for x in w)


def test_wellconditioned_no_warning_and_finite():
    # 良態資料：不誤發病態警告、且 T²/SPE/RBC 皆有限（護欄零行為改變、向後相容）
    rng = np.random.default_rng(3)
    X = rng.normal(size=(200, 5))
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        m = MSPCModel().fit(X)
    assert not any("條件數" in str(x.message) for x in w)
    q = rng.normal(size=(10, 5))
    assert np.isfinite(m.t2(q)).all() and np.isfinite(m.spe(q)).all() and np.isfinite(m.rbc_spe(q)).all()
