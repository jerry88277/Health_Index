"""通用 DataFrame adapter（桶1）：任意表 + 欄位角色映射 → ``(ProcessDataset, GroundTruth)``。

讓非化工/任意連續製程資料**免寫 adapter 模組**即接入框架：宣告哪些欄是 X、哪欄是
timestamp/grade/Y，未提供的角色自動補（grade=常數、Y=NaN、timestamp=順序時間）。golden 基準以
bool mask / 區間 / 前段比例啟發式指定（無逐列漂移真值，故 ``drift_mask=None``）。

可轉移性假設（Rule 1）：自動 golden 啟發式「取前比例為基準」假設**序列前段為健康平穩段**；若資料
前段即含暫態/故障則不成立——屆時須以 mask 明確指定 golden（桶4 的 golden 自動挑選為後續強化）。
"""

from __future__ import annotations

import warnings

import numpy as np
import pandas as pd

from ..interface import GRADE_LABEL, TIMESTAMP, Y_TIMESTAMP, Y_VALUE, ContractError, ProcessDataset
from .base import GroundTruth, Segment


def _resolve_golden(golden, n: int) -> np.ndarray:
    """把 golden 規格解析為 (n,) bool mask。

    支援：bool 陣列(n,) | (start, end) 區間 | float∈(0,1] 取前比例。

    Raises:
        ValueError: 規格非法（長度/型別/範圍）。
    """
    if isinstance(golden, np.ndarray):
        if golden.dtype != bool or len(golden) != n:
            raise ValueError(f"golden mask 須為長度 {n} 的 bool 陣列")
        return golden
    if isinstance(golden, tuple) and len(golden) == 2:
        s, e = int(golden[0]), int(golden[1])
        if not (0 <= s < e <= n):
            raise ValueError(f"golden 區間越界 (n={n}): {golden}")
        m = np.zeros(n, dtype=bool)
        m[s:e] = True
        return m
    if isinstance(golden, (int, float, np.floating, np.integer)) and not isinstance(golden, bool):
        frac = float(golden)
        if not (0.0 < frac <= 1.0):
            raise ValueError(f"golden 比例須 ∈(0,1]，得 {frac}")
        k = max(1, int(round(frac * n)))
        m = np.zeros(n, dtype=bool)
        m[:k] = True
        return m
    raise ValueError(f"非法 golden 規格: {golden!r}（須 bool 陣列 / (start,end) / float∈(0,1]）")


def _segments_from_grade(grades: np.ndarray) -> tuple[Segment, ...]:
    """依 grade **連續同值** 切段（無 grade→單一段）。end exclusive。"""
    n = len(grades)
    segs: list[Segment] = []
    i = sid = 0
    while i < n:
        j = i
        while j < n and grades[j] == grades[i]:
            j += 1
        segs.append(Segment(id=sid, start=i, end=j, label=str(grades[i])))
        sid += 1
        i = j
    return tuple(segs)


def _impute_x(x_block: pd.DataFrame, method: str) -> np.ndarray:
    """填補 X 缺值（不改原）。

    - ``"median"``：逐欄中位數（隱含 MCAR；穩健於離群）。
    - ``"ffill"``：前向填 + 後向補首段（時序自然，假設缺值期間值維持）。

    Raises:
        ValueError: 未知策略；或某欄**全為 NaN**（無可填基礎，fail loud）。
    """
    if x_block.isna().all(axis=0).any():
        allnan = x_block.columns[x_block.isna().all(axis=0)].tolist()
        raise ValueError(f"X 欄全為 NaN，無法填補: {allnan}")
    if method == "median":
        return x_block.fillna(x_block.median(numeric_only=True)).to_numpy()
    if method == "ffill":
        return x_block.ffill().bfill().to_numpy()
    raise ValueError(f"未知 impute 策略 '{method}'（須 'median' 或 'ffill'）")


def from_frame(
    df: pd.DataFrame,
    *,
    x_columns,
    timestamp: str | None = None,
    grade: str | None = None,
    y_value: str | None = None,
    y_timestamp: str | None = None,
    golden=None,
    impute: str | None = None,
    name: str = "custom",
) -> tuple[ProcessDataset, GroundTruth]:
    """從任意 DataFrame 建統一契約 + GroundTruth（不修改原表）。

    Args:
        df: 來源表。
        x_columns: X 製程參數欄名（須存在於 df、不得用保留欄名，否則 ContractError）。
        timestamp: 時間欄名；None → 順序整數時間（freq=min）。
        grade: grade/產品/類別欄名；None → 常數 "A"（單模態）。
        y_value: 軟量測 Y 欄名；None → 全 NaN（無 lab Y，L3 走 GSI 無標籤可信度）。
        y_timestamp: Y 量測時間欄名；None → 有 y_value 觀測處取 timestamp、否則 NaT。
        golden: golden 基準——bool(n,) | (start,end) | float∈(0,1] 取前比例。``None``（預設）→ 取前 30%
            並發 ``RuntimeWarning``（提醒「前段為健康」是未經確認的啟發式假設，見模組免責，紅隊 B#3）。
        impute: X 缺值處理。``None``（預設）＝**有 NaN 即 fail loud**（不靜默補值，避免延後到 fit 才晦澀崩）；
            ``"median"``/``"ffill"`` ＝填補並發 ``RuntimeWarning``。**嚴正警告（紅隊實證，Rule 12）**：填補
            **製造假陰性**——median 把缺值塞到邊際中心（正是 golden 相關結構認為「合規」之處）→ **系統性
            拉高飄移段健康度、遮蔽飄移**（實測 drift health 可 +0.20）。此遮蔽是任何填補的**本質風險**、
            非可調；缺值率高時偵測力嚴重受損。另：median 取自**全序列**（含 drift 列）→ golden↔drift 統計
            滲漏。故僅在缺值少且知情下使用，重缺值請改清理或丟棄該段。Y/yq_ 的 NaN 是**稀疏量測語義**、不處理。
        name: 資料集識別。

    Returns:
        (ProcessDataset, GroundTruth)；``drift_mask=None``（通用資料無逐列漂移真值），
        ``segments`` 依 grade 連續同值切段。

    Raises:
        ContractError: 缺/保留欄衝突、**X 欄不存在**（紅隊 A4）、**X 欄非數值**（紅隊 B#1）、
            **X 含 inf 非有限值**（紅隊 A3，同 NaN 是延後崩來源，邊界即擋）、或 NaN 且未指定 impute。
            皆在邊界 fail loud，不延後到 fit 才拋晦澀錯。
        ValueError: df 為空、golden 規格非法、impute 策略未知或整欄全 NaN。
    """
    n = len(df)
    if n == 0:
        raise ValueError("from_frame: df 為空（n=0），無法建立資料集")  # 紅隊 B#2 fail loud
    x_columns = tuple(x_columns)
    # --- X 欄驗證（全在邊界、且先於任何警告/建構）---
    absent = [c for c in x_columns if c not in df.columns]
    if absent:
        raise ContractError(f"宣告的 X 欄不存在於 df: {absent}")  # 紅隊 A4：清楚錯誤，非 raw KeyError
    nonnum = [c for c in x_columns if not pd.api.types.is_numeric_dtype(df[c])]
    if nonnum:
        raise ContractError(f"X 欄須為數值，非數值欄: {nonnum}")  # 紅隊 B#1
    x_block = df[list(x_columns)].astype(float)
    x_arr = x_block.to_numpy()
    if np.isinf(x_arr).any():  # 紅隊 A3：inf 非正常斷點（除零/飽和），即使 impute 也拒、邊界擋
        raise ContractError(f"X 含 {int(np.isinf(x_arr).sum())} 個 inf（非有限值）；請先清理，impute 不處理 inf")
    n_nan = int(np.isnan(x_arr).sum())
    if n_nan:  # X 缺值：預設 fail loud，impute 才填
        if impute is None:
            raise ContractError(
                f"X 含 {n_nan} 個缺值（NaN）；指定 impute='median'/'ffill' 或先清理（不靜默補值）。"
            )
        x_arr = _impute_x(x_block, impute)  # 先驗策略/全 NaN（raises），成功才警告（錯誤路徑不漏警告）
        warnings.warn(
            f"from_frame: X 缺值以 impute='{impute}' 填補（{n_nan} 個）；**填補製造假陰性**——imputed 樣本落在 "
            "golden 認為合規處 → 系統性拉高飄移段健康度、遮蔽飄移（缺值率越高越嚴重）。重缺值請改清理（Rule 12）。",
            RuntimeWarning,
            stacklevel=2,
        )
    # --- golden 解析（警告在所有 X 驗證之後，紅隊 A5：錯誤路徑不漏 golden 警告）---
    if golden is None:
        warnings.warn(
            "from_frame: 未指定 golden，預設取前 30% 為健康基準（假設序列前段平穩健康）。"
            "若前段含暫態/故障，請以 mask 或 (start,end) 明確指定 golden。",
            RuntimeWarning,
            stacklevel=2,
        )
        golden = 0.3
    out = pd.DataFrame(index=range(n))
    ts = (
        pd.to_datetime(df[timestamp].to_numpy())
        if timestamp is not None
        else pd.date_range("2026-01-01", periods=n, freq="min")
    )
    out[TIMESTAMP] = np.asarray(ts, dtype="datetime64[ns]")
    out[GRADE_LABEL] = df[grade].astype(str).to_numpy() if grade is not None else "A"
    for j, c in enumerate(x_columns):
        out[c] = x_arr[:, j]

    yv = df[y_value].to_numpy(dtype=float) if y_value is not None else np.full(n, np.nan)
    out[Y_VALUE] = yv
    if y_timestamp is not None:
        out[Y_TIMESTAMP] = np.asarray(pd.to_datetime(df[y_timestamp].to_numpy()), dtype="datetime64[ns]")
    else:  # 有 Y 觀測處取對應 timestamp、否則 NaT
        yts = np.full(n, np.datetime64("NaT"), dtype="datetime64[ns]")
        obs = np.isfinite(yv)
        yts[obs] = np.asarray(out[TIMESTAMP].to_numpy())[obs]
        out[Y_TIMESTAMP] = yts

    ds = ProcessDataset(frame=out, x_columns=x_columns, name=name)  # __post_init__ 驗 raw 契約
    gt = GroundTruth(
        x_columns=x_columns,
        golden_mask=_resolve_golden(golden, n),
        segments=_segments_from_grade(out[GRADE_LABEL].to_numpy()),
        drift_mask=None,
    )
    return ds, gt
