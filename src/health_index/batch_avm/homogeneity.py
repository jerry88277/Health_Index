"""池化 Golden 同質性閘（設計 §8，advisory / WARN-only）。

多機台/時段 union 進單一 Golden 會撐寬基準協方差 → T²/SPE 控制限變寬 → **降低隱性飄移靈敏度**。
本閘於 **build 時**對組成 Golden 的各 cell（如機台）做 **between-cell 置換檢定**：

- 統計量＝標準化 X* 空間的組間離差 Σ_c n_c·‖mean_c − mean_pooled‖²（MANOVA 型 pseudo-F 分子）；
  **非** in-sample 自我參照 T²/SPE（pooled 上 fit 再打 pooled 分必過＝假閘，紅隊 must-fix #10）。
- 置換 null：cell 標籤重排 B=config.perm_B 次（固定 config.random_state，Rule 5 確定性）；
  p=(1+#{perm≥obs})/(B+1)。
- **WARN 非硬擋**（使用者定案：保留自由度）；異質時指名**差異最大的特徵**（σ 單位，可行動）。
- **1-cell＝trivial pass**（無群可比，不偽造警告）；小 cell（<5 批）誠實標 low_power——
  **非拒絕不得讀成「同質」**。
"""

from __future__ import annotations

import numpy as np

from ..config import DEFAULT, Config

_MIN_CELL_POWER = 5  # 小於此批數的 cell → 檢定力低（誠實標，非拒絕≠同質）


def _between_stat(Xs: np.ndarray, labels: np.ndarray, uniq: np.ndarray) -> float:
    mu = Xs.mean(axis=0)
    stat = 0.0
    for u in uniq:
        sub = Xs[labels == u]
        d = sub.mean(axis=0) - mu
        stat += len(sub) * float(d @ d)
    return stat


def golden_homogeneity_gate(Xstar, cells, *, columns=None, config: Config = DEFAULT, alpha=None) -> dict:
    """對組成 Golden 的 cells（機台/時段）做 between-cell 同質性置換檢定（WARN-only）。

    Args:
        Xstar: (n_batches, p) golden 批的 X* 特徵。
        cells: (n_batches,) 每批的 cell 標籤（如 machine_id）。
        columns: 特徵欄名（指名差異最大特徵用）；None → f0..f{p-1}。
        config: 用 perm_B / random_state / fwer_alpha。
        alpha: 顯著水準；None → config.fwer_alpha。

    Returns:
        dict：applicable / warn / p_value / stat / max_shift_sigma / worst_feature /
        per_cell([{cell,n}]) / low_power / note / is_advisory=True。全純 Python 純量。
    """
    X = np.asarray(Xstar, dtype=float)
    labels = np.asarray([str(c) for c in cells])
    if len(labels) != len(X):
        raise ValueError(f"cells 長度 {len(labels)} 須等於批數 {len(X)}")
    alpha = float(alpha if alpha is not None else config.fwer_alpha)
    uniq = np.unique(labels)
    per_cell = [{"cell": str(u), "n": int((labels == u).sum())} for u in uniq]
    base = {"per_cell": per_cell, "is_advisory": True}
    if len(uniq) < 2:
        return {**base, "applicable": False, "warn": False, "p_value": None, "stat": None,
                "max_shift_sigma": None, "worst_feature": None, "low_power": False,
                "note": "單一機台/cell 組成 Golden——無異質性可檢（trivial pass）"}

    mean = X.mean(axis=0)
    std = X.std(axis=0) + 1e-9
    Xs = (X - mean) / std
    obs = _between_stat(Xs, labels, uniq)
    rng = np.random.default_rng(config.random_state)
    hits = 0
    for _ in range(int(config.perm_B)):
        perm = labels[rng.permutation(len(labels))]
        if _between_stat(Xs, perm, uniq) >= obs:
            hits += 1
    p = (1 + hits) / (config.perm_B + 1)

    # 差異最大的特徵（σ 單位，pairwise cell means 最大差）——可行動的歸因
    cols = list(columns) if columns is not None else [f"f{i}" for i in range(X.shape[1])]
    means = {u: Xs[labels == u].mean(axis=0) for u in uniq}
    max_shift, worst = 0.0, cols[0]
    for i, a in enumerate(uniq):
        for b in uniq[i + 1:]:
            d = np.abs(means[a] - means[b])
            j = int(np.argmax(d))
            if float(d[j]) > max_shift:
                max_shift, worst = float(d[j]), cols[j]

    low_power = min(c["n"] for c in per_cell) < _MIN_CELL_POWER
    warn = bool(p < alpha)
    note = (f"⚠ Golden 混入異質 cell（p={p:.3f}<α={alpha}）：基準將被撐寬、隱性飄移靈敏度下降。"
            f"差異最大特徵：{worst}（{max_shift:.2f}σ）。建議改用分層模型（每機台各建）或剔除異質 cell。"
            if warn else
            f"未偵測到 cell 間異質（p={p:.3f}）" + ("；⚠ 小 cell 檢定力低，非拒絕≠同質" if low_power else ""))
    return {**base, "applicable": True, "warn": warn, "p_value": float(p), "stat": float(obs),
            "max_shift_sigma": float(max_shift), "worst_feature": worst, "low_power": bool(low_power),
            "note": note}
