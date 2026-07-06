"""G1 ground-truth：合成儀器漂移 Y 序列（純 Y、無 X）。

為何合成（使用者 2026-07-02 定案）：TEP 的 Y=f(X)（產品成分由製程狀態生成），**結構上不存在**
「X 不動、Y 獨立漂移」的物理機制——G1（純 Y-vs-歷史、獨立於 X）在 TEP 上不可證。本 adapter
模擬**量測儀器**的緩慢漂移/再校正位移（真實場景：lab 儀器老化、標定漂移），提供有標記的
ground truth。誠實標（Rule 12）：此為合成刺激、非真實儀器資料；真實產線 Y 接入後應以
「儀器再校正事件」對照驗證。

輸出為純 y 序列（**刻意不走 ProcessDataset 契約**——G1 模組只吃 y，塞 dummy X 反而違反其
X-獨立語意）。
"""

from __future__ import annotations

import numpy as np


def generate(
    *,
    n_golden: int = 200,
    n_stable: int = 50,
    n_drift: int = 150,
    drift_total_sigma: float = 1.5,
    step_sigma: float | None = None,
    step_at: int | None = None,
    mu: float = 10.0,
    sigma: float = 1.0,
    seed: int = 0,
) -> tuple[np.ndarray, np.ndarray, dict]:
    """生成 (y_golden, y_online, truth)。

    y_online = 前 ``n_stable`` 筆平穩 + 後 ``n_drift`` 筆線性緩漂（總幅 ``drift_total_sigma``·σ，
    隱性：單點多半仍在 ±3σ 內）；可另疊 ``step_sigma``·σ 的階躍（``step_at`` 起，模擬再校正位移）。

    Returns:
        y_golden: (n_golden,) 歷史 Y（平穩 N(mu, sigma²)）。
        y_online: (n_stable+n_drift,) 線上 Y。
        truth: {drift_start, drift_total_sigma, step_at, step_sigma}（drift_start=n_stable；
            無漂移時語意為「無真漂移」供誤報測試）。

    Invariant: 同參數 → 逐位元相同輸出（固定 seed）。
    """
    rng = np.random.default_rng(seed)
    y_golden = mu + sigma * rng.normal(size=n_golden)
    stable = mu + sigma * rng.normal(size=n_stable)
    drift = mu + np.linspace(0.0, drift_total_sigma * sigma, n_drift) + sigma * rng.normal(size=n_drift)
    y_online = np.concatenate([stable, drift])
    if step_sigma is not None and step_at is not None:
        y_online[step_at:] += step_sigma * sigma
    truth = {
        "drift_start": int(n_stable),
        "drift_total_sigma": float(drift_total_sigma),
        "step_at": int(step_at) if step_at is not None else None,
        "step_sigma": float(step_sigma) if step_sigma is not None else None,
    }
    return y_golden, y_online, truth
