"""X→Y 延遲對齊 WHY 測試（Rule 9）。

核心 WHY：延遲估計必須找回真實製程延遲。若估錯，L3 軟測量會以錯位的 (X,Y) 訓練，
X→Y 映射被污染——故「估計延遲 ≠ 注入延遲」的情況必須讓測試失敗。
"""

import numpy as np

from health_index import interface as I
from health_index.adapters import synthetic as syn
from health_index.preprocess import align


def _shift_sparse_y(y: np.ndarray, d: int) -> np.ndarray:
    """把稀疏 y 整體往後移 d 步（前 d 列補 NaN），模擬 Y 延遲 d 步。"""
    out = np.full(len(y), np.nan, dtype=float)
    if d == 0:
        return np.asarray(y, dtype=float).copy()
    out[d:] = y[:-d]
    return out


def test_estimate_delay_zero_on_aligned():
    ds, _ = syn.generate(seed=5)
    X = ds.frame[list(ds.x_columns)].to_numpy()
    y = ds.frame[I.Y_VALUE].to_numpy()
    assert align.estimate_delay(X, y, max_lag=8) == 0


def test_estimate_delay_recovers_injected_delay():
    ds, _ = syn.generate(seed=5)
    X = ds.frame[list(ds.x_columns)].to_numpy()
    y = ds.frame[I.Y_VALUE].to_numpy()
    for d_true in (1, 3, 5):
        yd = _shift_sparse_y(y, d_true)
        assert align.estimate_delay(X, yd, max_lag=8) == d_true, f"未復原延遲 {d_true}"


def test_add_y_delay_column():
    ds, _ = syn.generate(seed=5)
    fr = align.add_y_delay(ds)
    assert I.Y_DELAY in fr.columns
    assert (fr[I.Y_DELAY] == 0).all()  # 對齊資料延遲 0
    # 不改原 frame
    assert I.Y_DELAY not in ds.frame.columns


def test_estimate_delay_insufficient_obs_returns_zero():
    rng = np.random.default_rng(0)
    X = rng.standard_normal((20, 5))
    y = np.full(20, np.nan)
    y[0] = 1.0  # 僅 1 個觀測，不足擬合
    assert align.estimate_delay(X, y, max_lag=5) == 0


def test_estimate_delay_large_max_lag_no_spurious_delay():
    # WHY（紅隊 R1/R2）：真延遲 0、強信號；即使 max_lag 很大也不該因 overfit 偽 R²
    # 選到偽大延遲。舊版（raw R² + 鬆門檻）在 max_lag=1300 會回傳 ~1252，此測試擊殺之。
    ds, _ = syn.generate(seed=5)
    X = ds.frame[list(ds.x_columns)].to_numpy()
    y = ds.frame[I.Y_VALUE].to_numpy()
    assert align.estimate_delay(X, y, max_lag=1300) == 0


def test_add_y_delay_writes_estimated_delay_on_shifted():
    # WHY（紅隊 B）：守住「估計→寫欄」接縫，不只測 d=0
    ds, _ = syn.generate(seed=5)
    fr = ds.frame.copy()
    fr[I.Y_VALUE] = _shift_sparse_y(fr[I.Y_VALUE].to_numpy(), 3)
    ds2 = I.ProcessDataset(frame=fr, x_columns=ds.x_columns, name="shifted")
    out = align.add_y_delay(ds2)
    assert (out[I.Y_DELAY] == 3).all()
