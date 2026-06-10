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
            ``"median"``/``"ffill"`` ＝填補並發 ``RuntimeWarning``——填補**扭曲多變量關係**（本 index 監看的
            對象），重缺值會稀釋飄移訊號，屬可轉移性風險（Rule 1），故須使用者明確選擇。Y/yq_ 的 NaN 是
            **稀疏量測語義**、不在此處理。
        name: 資料集識別。

    Returns:
        (ProcessDataset, GroundTruth)；``drift_mask=None``（通用資料無逐列漂移真值），
        ``segments`` 依 grade 連續同值切段。

    Raises:
        ContractError: ProcessDataset 驗證失敗（缺 X 欄/保留欄衝突）、或 **X 欄非數值**（紅隊 B#1，
            在邊界 fail loud 而非延後到 fit 才拋晦澀錯）。
        ValueError: df 為空、或 golden 規格非法。
    """
    n = len(df)
    if n == 0:
        raise ValueError("from_frame: df 為空（n=0），無法建立資料集")  # 紅隊 B#2 fail loud
    x_columns = tuple(x_columns)
    nonnum = [c for c in x_columns if c in df.columns and not pd.api.types.is_numeric_dtype(df[c])]
    if nonnum:
        raise ContractError(f"X 欄須為數值，非數值欄: {nonnum}")  # 紅隊 B#1：邊界即擋
    if golden is None:  # 紅隊 B#3：預設啟發式須出聲，不靜默
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
    x_block = df[list(x_columns)].astype(float)
    n_nan = int(x_block.isna().to_numpy().sum())
    if n_nan:  # X 缺值：預設 fail loud（邊界即擋），impute 才填（並警告扭曲，紅隊桶4）
        if impute is None:
            raise ContractError(
                f"X 含 {n_nan} 個缺值（NaN）；指定 impute='median'/'ffill' 或先清理。"
                "不靜默補值——填補會扭曲多變量關係（本 index 監看的對象）。"
            )
        x_arr = _impute_x(x_block, impute)  # 先驗策略/全 NaN（raises），成功才警告（避免錯誤路徑漏警告）
        warnings.warn(
            f"from_frame: X 缺值以 impute='{impute}' 填補（{n_nan} 個）；填補扭曲多變量關係、稀釋飄移訊號，"
            "重缺值請審慎（Rule 1）。",
            RuntimeWarning,
            stacklevel=2,
        )
    else:
        x_arr = x_block.to_numpy()
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
