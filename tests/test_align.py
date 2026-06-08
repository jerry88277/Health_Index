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


def test_delay_align_train_pairs_xtminusd_with_yt():
    # WHY：對齊訓練對須真的把 X(t−d) 配 Y(t)，且丟掉 t−d<0 的列。接錯（配 X(t)）會被擊殺。
    X = np.arange(100).reshape(-1, 1).astype(float)  # X[t]=t，便於檢驗配對
    y = np.full(100, np.nan)
    obs_pos = [5, 25, 45]
    y[obs_pos] = [10.0, 20.0, 30.0]
    Xtr, ytr = align.delay_align_train(X, y, 3)
    assert list(ytr) == [10.0, 20.0, 30.0]
    assert list(Xtr.ravel()) == [2.0, 22.0, 42.0]  # X(t−3)
    # d=0 退化：取 obs 列本身
    X0, y0 = align.delay_align_train(X, y, 0)
    assert list(X0.ravel()) == [5.0, 25.0, 45.0]
    # t−d<0 的觀測被丟（首列 obs=2 < d=5）；邊界 t==d 須保留（紅隊 A#2：鎖 >= 不被改成 >）
    y2 = np.full(100, np.nan)
    y2[[2, 5, 40]] = [1.0, 9.0, 2.0]
    Xtr2, ytr2 = align.delay_align_train(X, y2, 5)
    assert list(ytr2) == [9.0, 2.0] and list(Xtr2.ravel()) == [0.0, 35.0]  # obs=5(==d)→X[0] 保留；obs=2 丟


def test_aligned_training_generalizes_better_on_delayed_y():
    # WHY（Rule 9）：Y 延遲 d 時，以 X(t−d)→Y(t) 對齊訓練的軟測量在**留出集**泛化誤差須 <
    # 不對齊(naive)。用留出集而非 in-sample——GPR 會把無關的 naive 對 overfit 到低 in-sample 殘差，
    # 唯留出集能揭穿錯位映射（naive 退化為預測均值，誤差≈std(y)）。鎖住「延遲對齊只是擺設」的假綠。
    from health_index.detectors.soft_sensor import SoftSensor

    ds, _ = syn.generate(seed=5)
    X = ds.frame[list(ds.x_columns)].to_numpy()
    yd = _shift_sparse_y(ds.frame[I.Y_VALUE].to_numpy(), 3)
    assert align.estimate_delay(X, yd, max_lag=8) == 3
    obs = np.flatnonzero(np.isfinite(yd))
    obs = obs[obs - 3 >= 0]
    tr, te = obs[: len(obs) // 2], obs[len(obs) // 2 :]          # 時序前半訓練、後半留出
    r_al = float(np.abs(SoftSensor().fit(X[tr - 3], yd[tr]).predict(X[te - 3]) - yd[te]).mean())
    r_nv = float(np.abs(SoftSensor().fit(X[tr], yd[tr]).predict(X[te]) - yd[te]).mean())
    assert r_al < r_nv


def test_add_y_delay_writes_estimated_delay_on_shifted():
    # WHY（紅隊 B）：守住「估計→寫欄」接縫，不只測 d=0
    ds, _ = syn.generate(seed=5)
    fr = ds.frame.copy()
    fr[I.Y_VALUE] = _shift_sparse_y(fr[I.Y_VALUE].to_numpy(), 3)
    ds2 = I.ProcessDataset(frame=fr, x_columns=ds.x_columns, name="shifted")
    out = align.add_y_delay(ds2)
    assert (out[I.Y_DELAY] == 3).all()
