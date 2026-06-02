"""確定性合成連續製程生成器（M1）。

為何用合成而非 pyTEP（Rule 1/2 判斷）：pyTEP 需 MATLAB engine、tep2py 需編譯 Fortran，
地端難即裝；而本鏈的 WHY 測試（Rule 9）需要**可控 ground-truth**——尤其「每變數在
單變數規格內、僅多變量關係偏移」的隱性飄移，純 numpy 生成器最簡且完全可控。真實
TEP/PRONTO/Gas adapter 日後映射下載檔，接同一 ``interface`` 契約。

生成的 campaign 結構：A_golden → B → A_clean(re-entry) → C → A_drift(re-entry)。
- 不同 grade（B/C）：對 X 加平均位移（操作點變動），代表換產品。
- A_drift 段注入**隱性多變量飄移**：擾動潛因子載荷 W 的方向但**逐列重正規化保持各變數
  變異**，因此每個 x_i 的單變數分佈（均值/變異）幾乎不變（單變數 SPC 抓不到），但變數間
  相關結構（off-diagonal）明顯改變（T²/SPE/MMD 才抓得到）。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..interface import (
    GRADE_LABEL,
    TIMESTAMP,
    Y_TIMESTAMP,
    Y_VALUE,
    ProcessDataset,
)


@dataclass(frozen=True)
class SyntheticGroundTruth:
    """合成資料的真值，供測試斷言（不進入 ProcessDataset 契約）。

    Attributes:
        campaign_bounds: 每個 campaign 的 (start, end, grade)，end 為 exclusive。
        golden_mask: 長度 n 的 bool 陣列，標記 golden-A（建基準用）列。
        drift_mask: 長度 n 的 bool 陣列，標記被注入隱性飄移的列。
        x_columns: X 欄名。
    """

    campaign_bounds: tuple[tuple[int, int, str], ...]
    golden_mask: np.ndarray
    drift_mask: np.ndarray
    x_columns: tuple[str, ...]


def _renorm_rows(mat: np.ndarray, target_norms: np.ndarray) -> np.ndarray:
    """把 mat 每列重新縮放到 target_norms（保持方向、改變長度）。

    不變式：因潛因子 z~N(0,I) 為白化，Var(x_i)=‖W_i‖²+σ_noise²，故**列範數守恆 ⇒ 各變數
    方差守恆**——這正是隱性飄移「單變數不可見」的數學保證（只改方向＝改相關，不改邊際變異）。
    """
    cur = np.linalg.norm(mat, axis=1, keepdims=True)
    cur = np.where(cur == 0.0, 1.0, cur)
    return mat / cur * target_norms[:, None]


def generate(
    *,
    n_per_campaign: int = 300,
    p: int = 10,
    r: int = 3,
    seed: int = 42,
    drift_strength: float = 0.8,
    grade_shift: float = 2.0,
    noise_sigma: float = 0.3,
    y_every: int = 20,
) -> tuple[ProcessDataset, SyntheticGroundTruth]:
    """生成合成連續製程資料。

    Args:
        n_per_campaign: 每個 campaign 的樣本數。
        p: X 製程參數維度。
        r: 潛因子維度（決定相關結構秩）。
        seed: 亂數種子（決定論可重現）。
        drift_strength: A_drift 段相關結構擾動強度（越大越易被多變量偵測）。
        grade_shift: B/C grade 的操作點位移幅度。
        noise_sigma: 觀測噪聲標準差。
        y_every: 每隔幾步取一個 lab Y（其餘為 NaN，模擬稀疏量測）。

    Returns:
        (ProcessDataset, SyntheticGroundTruth)

    Invariant: 同 seed → 逐位元相同輸出（決定論）。
    """
    rng = np.random.default_rng(seed)

    # 基準潛因子載荷與品質迴歸係數
    W = rng.standard_normal((p, r))
    row_norms = np.linalg.norm(W, axis=1)
    beta = rng.standard_normal(r)

    # 隱性飄移載荷：擾動方向後逐列重正規化（保持各變數變異 → 單變數不可見）
    W_drift = _renorm_rows(W + drift_strength * rng.standard_normal((p, r)), row_norms)

    # grade 操作點位移（A 不位移；B/C 位移代表換產品）
    shift_b = np.zeros(p)
    shift_b[: p // 2] = grade_shift
    shift_c = np.zeros(p)
    shift_c[p // 2 :] = -grade_shift
    plan = [
        ("A", W, np.zeros(p), "golden"),
        ("B", W, shift_b, "other"),
        ("A", W, np.zeros(p), "clean"),
        ("C", W, shift_c, "other"),
        ("A", W_drift, np.zeros(p), "drift"),
    ]

    x_columns = tuple(f"x{i:02d}" for i in range(p))
    blocks_x: list[np.ndarray] = []
    blocks_y: list[np.ndarray] = []
    grades: list[str] = []
    bounds: list[tuple[int, int, str]] = []
    golden_flags: list[np.ndarray] = []
    drift_flags: list[np.ndarray] = []

    cursor = 0
    for grade, load, shift, tag in plan:
        z = rng.standard_normal((n_per_campaign, r))
        x = z @ load.T + shift + noise_sigma * rng.standard_normal((n_per_campaign, p))
        y = z @ beta + noise_sigma * rng.standard_normal(n_per_campaign)
        blocks_x.append(x)
        blocks_y.append(y)
        grades.extend([grade] * n_per_campaign)
        bounds.append((cursor, cursor + n_per_campaign, grade))
        golden_flags.append(np.full(n_per_campaign, tag == "golden"))
        drift_flags.append(np.full(n_per_campaign, tag == "drift"))
        cursor += n_per_campaign

    X = np.vstack(blocks_x)
    y_full = np.concatenate(blocks_y)
    n = X.shape[0]

    # 稀疏 Y：僅每 y_every 步保留實際量測，其餘 NaN
    y_value = np.full(n, np.nan)
    sample_idx = np.arange(0, n, y_every)
    y_value[sample_idx] = y_full[sample_idx]

    ts = pd.date_range("2026-01-01", periods=n, freq="min")
    y_ts = pd.Series(pd.NaT, index=range(n), dtype="datetime64[ns]")
    y_ts.iloc[sample_idx] = ts[sample_idx]

    frame = pd.DataFrame({TIMESTAMP: ts, GRADE_LABEL: grades})
    for j, col in enumerate(x_columns):
        frame[col] = X[:, j]
    frame[Y_VALUE] = y_value
    frame[Y_TIMESTAMP] = y_ts.to_numpy()

    gt = SyntheticGroundTruth(
        campaign_bounds=tuple(bounds),
        golden_mask=np.concatenate(golden_flags),
        drift_mask=np.concatenate(drift_flags),
        x_columns=x_columns,
    )
    return ProcessDataset(frame=frame, x_columns=x_columns, name="synthetic"), gt
