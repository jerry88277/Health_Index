"""殘差自相關 AR(p) 白化：把相依殘差轉成近 iid 的 innovations，讓 CUSUM/EWMA 管制界前提成立。

為何需要：CUSUM/EWMA 的界假設**獨立**觀測。殘差正自相關 → 等效樣本數縮水 → 誤報膨脹、偵測靈敏度
失真。``YHistoryMonitor`` 的經驗 h 校準只吸收**尺度**，吸收不了**相依結構**（校準在 golden 上做，
相依性使該校準本身變異更大、且線上段相依結構若異動即失準）→ 從根因解＝白化。

**AR(p) 而非完整 ARIMA（Rule 7 擇一說明）**：殘差序列本應平穩（差分 I 項不適用——且差分會抵消
漂移，正是本監控的反面，見 `residual.py`）；MA 項對批級殘差屬過度設計（Rule 2）；statsmodels 不在
本專案技術棧（numpy/scipy/sklearn/pandas/POT），以 numpy OLS + scipy chi2 實作可保**確定性**
（Rule 5，無 RNG）且零新依賴。故實作為 ARIMA 的 AR 子集，此偏離 backlog 用詞的理由明標於此。

**資料驅動、不強制**：先以 Ljung-Box 檢定 golden 殘差是否真有自相關；**不顯著則不白化**
（``order=0``、identity）——不對沒壞的東西做轉換，也不白白丟失前 p 點（Rule 2、向後相容）。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import stats

from ..config import DEFAULT, Config


@dataclass
class ARWhitener:
    """已凍結的 AR 白化器（``applied=False`` ⇒ identity，殘差本已近 iid）。"""

    order: int                    # AR 階數 p（0＝不白化）
    phi: np.ndarray               # AR 係數 [φ1..φp]
    lb_p_before: float            # 白化前 Ljung-Box p 值
    lb_p_after: float | None      # 白化後 Ljung-Box p 值（未套用則 None）
    applied: bool
    note: str = ""


def ljung_box(x, lags: int | None = None) -> tuple[float, float]:
    """Ljung-Box Q 檢定殘留自相關。回傳 (Q, p)；p 小＝仍有顯著自相關。

    Raises:
        ValueError: 有限樣本 < 8（樣本太少無法檢定，不假評）。
    """
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    n = len(x)
    if n < 8:
        raise ValueError(f"Ljung-Box 需有限樣本 ≥8（得 {n}）")
    m = int(lags) if lags is not None else max(1, min(10, n // 5))
    xc = x - x.mean()
    denom = float(np.dot(xc, xc))
    if denom <= 0:
        return 0.0, 1.0  # 全常數：無自相關可言
    q = 0.0
    for k in range(1, m + 1):
        r = float(np.dot(xc[k:], xc[:-k]) / denom)
        q += r * r / (n - k)
    Q = n * (n + 2) * q
    return float(Q), float(stats.chi2.sf(Q, m))


def _ar_design(e: np.ndarray, p: int, start: int):
    """AR(p) 的 (設計矩陣, 目標)；``start`` 對齊各階共同樣本（AIC 可比）。"""
    n = len(e)
    Y = e[start:]
    cols = [e[start - i:n - i] for i in range(1, p + 1)]  # lag1..lagp
    return np.column_stack(cols), Y


def fit_whitener(e_golden, *, max_order: int = 3, alpha: float = 0.05,
                 config: Config = DEFAULT) -> ARWhitener:
    """以 golden 殘差配適 AR 白化器（先檢定；不顯著則 identity）。

    Args:
        e_golden: golden 期殘差序列（**須依時間排序**；非有限值先剔除）。
        max_order: 候選最大 AR 階（AIC 於共同樣本上選階）。
        alpha: Ljung-Box 顯著水準。

    Raises:
        ValueError: 有限樣本不足以配適（< max_order+8）。
    """
    e = np.asarray(e_golden, dtype=float)
    e = e[np.isfinite(e)]
    n = len(e)
    if n < max_order + 8:
        raise ValueError(f"白化需有限殘差 ≥{max_order + 8}（得 {n}）")
    _q0, p_before = ljung_box(e)
    if p_before >= alpha:  # 已近 iid → 不轉換（Rule 2）
        return ARWhitener(order=0, phi=np.zeros(0), lb_p_before=p_before, lb_p_after=None,
                          applied=False, note="Ljung-Box 不顯著：殘差已近 iid，不套用白化")
    best = None
    for p in range(1, max_order + 1):  # 共同樣本 start=max_order → 各階 AIC 可比
        Xd, Y = _ar_design(e, p, max_order)
        phi, *_ = np.linalg.lstsq(Xd, Y, rcond=None)
        resid = Y - Xd @ phi
        s2 = float(np.mean(resid ** 2))
        aic = len(Y) * np.log(max(s2, 1e-300)) + 2 * p
        if best is None or aic < best[0]:
            best = (aic, p, phi)
    _aic, order, phi = best
    inn = _innovations(e, order, phi)
    fin = inn[np.isfinite(inn)]
    p_after = ljung_box(fin)[1] if len(fin) >= 8 else None
    return ARWhitener(order=int(order), phi=np.asarray(phi, dtype=float), lb_p_before=p_before,
                      lb_p_after=p_after, applied=True,
                      note=f"Ljung-Box 顯著（p={p_before:.4g}）→ 套用 AR({order}) 白化")


def _innovations(e: np.ndarray, order: int, phi: np.ndarray) -> np.ndarray:
    """e_t − Σφ_i·e_{t−i}；前 order 點與 lag 視窗含缺口者為 NaN（誠實不推補）。"""
    out = np.full(len(e), np.nan)
    for t in range(order, len(e)):
        lagw = e[t - order:t][::-1]  # lag1..lagp
        if np.isfinite(e[t]) and np.all(np.isfinite(lagw)):
            out[t] = e[t] - float(np.dot(phi, lagw))
    return out


def whiten(w: ARWhitener, e) -> np.ndarray:
    """套用白化；``applied=False`` 時為 identity（原樣回傳，不丟點）。"""
    e = np.asarray(e, dtype=float)
    if not w.applied or w.order == 0:
        return e.copy()
    return _innovations(e, w.order, w.phi)
