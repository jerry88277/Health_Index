"""高維／規模穩健共用工具（桶3）：有效數值秩 + L1 MCD 前 PCA-score 預降維維度決策。

第一性原理（為何需要本模組）：FastMCD（``MinCovDet``）在 p≫n（樣本少於變數）時**不 raise**，
而是回傳**奇異**協方差（實證 n=60/p=128：cond≈1.2e18、rank 缺 69）→ DQI_x 的 PCA 載荷與距離被
零特徵值方向汙染、健康分數失效卻無任何警告（Rule 12 的靜默失敗紅線）。經典 MSPC 解法：先以普通
PCA（SVD，恆良定義）把 X 投影到前 r 個 score（r 選使 n>2r），在 score 空間才估 robust 協方差。

本模組只提供**確定性數學**（無 LLM，Rule 5）：``effective_rank`` 與 ``reduction_plan``。
"""

from __future__ import annotations

import numpy as np


def effective_rank(eigvals_desc: np.ndarray, *, rtol: float = 1e-9) -> int:
    """有效數值秩＝大於 ``rtol × 最大特徵值`` 的特徵值個數（至少 1）。

    用於 L4 截斷 PCA：p≫n 時協方差有 p−(n−1) 個近零特徵值，其特徵向量為任意 noise 方向；
    在這些方向上做 per-component KS 既無意義又把 Bonferroni 校正 ×p 過度膨脹。截到有效秩可
    只在真實變異子空間檢定。p≪n 且良定義時回傳 p（全保留）→ 行為不變（向後相容）。

    Args:
        eigvals_desc: 降序（或任意序）特徵值；負值（數值噪）視為 0。
        rtol: 相對容差；特徵值 > rtol×max 才算真實方向。

    Returns:
        有效秩 r∈[1, len]。空輸入回 0。
    """
    ev = np.clip(np.asarray(eigvals_desc, dtype=float), 0.0, None)
    if ev.size == 0:
        return 0
    mx = float(ev.max())
    if mx <= 0.0:
        return 1
    return int(max(1, (ev > rtol * mx).sum()))


def reduction_plan(
    n: int,
    p: int,
    *,
    rank: int,
    var_components: int,
    min_n_over_p: float,
    max_frac: float,
) -> tuple[bool, int, bool]:
    """決定 L1 在 MCD 前是否預降維、降到幾維 r、以及是否變異匱乏（degraded）。

    決策（確定性）：
        - ``need_reduce = n < min_n_over_p × p``：樣本不足以在原 p 維穩健估協方差（MCD 需 n>2p）。
        - 降維維度 ``r = min(rank, floor(max_frac × n))``（至少 1）：上限綁 n 確保降維後仍 n>2r，
          使 score 空間的 MCD 有效。
        - ``degraded = need_reduce and r < var_components``：連保留 ``pca_var_explained`` 目標變異所
          需的成分數都放不下（被樣本數卡住）→ 真實變異方向被丟棄，**須誠實 surface**（Rule 12），
          非靜默截斷。

    Args:
        n: 樣本數。
        p: 原始變數維度。
        rank: golden 標準化後的有效數值秩（``effective_rank``）。
        var_components: 在原空間累積達 ``pca_var_explained`` 所需的成分數。
        min_n_over_p: 觸發降維的 n/p 門檻（config.hd_min_n_over_p）。
        max_frac: r 上限佔 n 的比例（config.hd_reduce_max_frac）。

    Returns:
        (need_reduce, r, degraded)。need_reduce=False 時 r=min(rank,p)、degraded=False（向後相容）。
    """
    if n < min_n_over_p * p:
        r = int(max(1, min(rank, int(np.floor(max_frac * n)))))
        degraded = r < var_components
        return True, r, degraded
    return False, int(max(1, min(rank, p))), False
