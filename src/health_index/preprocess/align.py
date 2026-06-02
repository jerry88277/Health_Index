"""X→Y 延遲對齊（M1 preprocess）。

連續製程的 lab 量測 Y 相對製程參數 X 有動態/輸送/分析延遲：Y(t) 實際對應過去某段
X(t−d)（紅隊 H1：稀疏延遲 Y）。本模組估計延遲 d，使後續軟測量（L3）以對齊的
(X(t−d), Y(t)) 訓練——**若延遲估錯，X→Y 映射會被錯位污染**，這正是本單元的存在理由。

可轉移性假設（Rule 1）：以「線性 R²」為對齊準則，隱含 X→Y 線性可預測；真實化工製程
X→Y 常非線性，屆時準則須改（如互資訊/非線性 surrogate）。MVP 估計單一全域延遲（Rule 2），
per-campaign 延遲列為後續。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import DEFAULT, Config
from ..interface import Y_DELAY, Y_VALUE, ProcessDataset


def _r2_linear(x: np.ndarray, y: np.ndarray) -> float:
    """以含截距的最小平方擬合 y~x，回傳 R²（ss_tot=0 時回 0）。"""
    a = np.column_stack([x, np.ones(len(y))])
    coef, *_ = np.linalg.lstsq(a, y, rcond=None)
    resid = y - a @ coef
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    return 1.0 - float(np.sum(resid**2)) / ss_tot if ss_tot > 0 else 0.0


def estimate_delay(X: np.ndarray, y: np.ndarray, *, max_lag: int = 10) -> int:
    """估計使 X(t−d)→Y(t) 線性可預測性（R²）最高的延遲 d∈[0, max_lag]。

    Args:
        X: (n, p) 製程參數。
        y: (n,) lab 量測，未觀測處為 NaN（稀疏）。
        max_lag: 搜尋上限（步）。

    Returns:
        估計延遲 d（整數）。觀測點不足以可靠估計時回 0（退回「無延遲」保守假設）。

    Note:
        - 紅隊 R1：所有 lag 使用**相同觀測子集**（i−max_lag≥0）比較 R²，消除各 lag 因有效
          樣本數不同造成的 selection bias（raw R² 隨樣本數變少而虛高）。
        - 紅隊 R2：要求 ≥2p+1 個共同觀測（殘差自由度 ≥ p），避免臨界擬合的 overfit 偽 R²。
        - 回傳 0 同時表示「真延遲 0」與「資料不足放棄」；MVP 下游以無延遲處理，屬已知限制。
    """
    y = np.asarray(y, dtype=float)
    p = X.shape[1]
    obs = np.flatnonzero(np.isfinite(y))
    common = obs[obs - max_lag >= 0]  # 對所有 lag 皆有效的共同觀測子集 → 等樣本數比較
    if common.size < 2 * p + 1:
        return 0
    best_d, best_score = 0, -np.inf
    for d in range(max_lag + 1):
        score = _r2_linear(X[common - d], y[common])
        if score > best_score:
            best_score, best_d = score, d
    return best_d


def add_y_delay(dataset: ProcessDataset, *, config: Config = DEFAULT) -> pd.DataFrame:
    """估計全域 X→Y 延遲並加入 Y_DELAY 衍生欄（常數），回傳**新** frame（不改原 frame）。"""
    fr = dataset.frame.copy()
    X = fr[list(dataset.x_columns)].to_numpy()
    d = estimate_delay(X, fr[Y_VALUE].to_numpy(), max_lag=config.y_max_lag)
    fr[Y_DELAY] = d
    return fr
