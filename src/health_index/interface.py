"""統一資料契約（Health_Index 骨架，Rule 3：保持穩定）。

五維度判斷鏈共用此契約。欄位分三層：
  - 原始欄 (raw)    : adapter 必須提供。
  - 衍生欄 (derived): pipeline（preprocess）計算後填入。
  - 設定 (config)   : 不入資料列，見 ``config.py``。

雙軌樣本（見 docs/continuous_process_segmentation.md）：
  - 穩態 pseudo-run：以 ``run_id`` 標記 SSD/ruptures 切出的穩態段（campaign/MSPC 比較）。
  - 逐時刻 lagged 樣本：動態建模/軟測量用（lag 階數見 config.x_lag_order）。

不變式 (invariants)：
  - 每列 = 一個 ``timestamp`` 樣本。
  - X 製程參數欄為數值，且**不得**使用任何保留欄名。
  - ``is_golden_a=True`` 的列構成凍結基準，不參與線上自適應更新（紅隊 H1）。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import pandas as pd


class Mode(str, Enum):
    """製程段別；transition/maintenance 預設排除於 golden-A baseline。"""

    STEADY = "steady"
    TRANSITION = "transition"
    MAINTENANCE = "maintenance"


# --- 保留欄名（reserved）：adapter 的 X 感測器欄不得使用以下名稱 ---
# 原始欄（adapter 提供）
TIMESTAMP = "timestamp"
GRADE_LABEL = "grade_label"
Y_VALUE = "y_value"
Y_TIMESTAMP = "y_timestamp"
# 衍生欄（pipeline 計算）
CAMPAIGN_ID = "campaign_id"
MODE = "mode"
RUN_ID = "run_id"
IS_GOLDEN_A = "is_golden_a"
Y_DELAY = "y_delay"

RAW_REQUIRED: tuple[str, ...] = (TIMESTAMP, GRADE_LABEL, Y_VALUE, Y_TIMESTAMP)
DERIVED: tuple[str, ...] = (CAMPAIGN_ID, MODE, RUN_ID, IS_GOLDEN_A, Y_DELAY)
RESERVED: tuple[str, ...] = RAW_REQUIRED + DERIVED


class ContractError(ValueError):
    """資料不符合統一契約時拋出。"""


def validate_raw(frame: pd.DataFrame, x_columns: tuple[str, ...]) -> None:
    """驗證 raw 契約。

    Args:
        frame: 候選長表，須含 RAW_REQUIRED 欄與所有 x_columns。
        x_columns: 宣告的 X 製程參數欄名。

    Raises:
        ContractError: 缺 RAW_REQUIRED 欄、x_columns 為空、與保留欄名重疊、或不存在於 frame。

    Invariant: 通過後保證 frame 具備建立 ProcessDataset 的最小欄位。
    """
    missing = [c for c in RAW_REQUIRED if c not in frame.columns]
    if missing:
        raise ContractError(f"缺少必要原始欄: {missing}")
    if not tuple(x_columns):
        raise ContractError("至少需一個 X 製程參數欄")
    overlap = sorted(set(x_columns) & set(RESERVED))
    if overlap:
        raise ContractError(f"X 欄不得使用保留欄名: {overlap}")
    absent = [c for c in x_columns if c not in frame.columns]
    if absent:
        raise ContractError(f"宣告的 X 欄不存在於 frame: {absent}")


@dataclass(frozen=True)
class ProcessDataset:
    """承載一條產線的連續製程資料。

    Attributes:
        frame: 長表 DataFrame，含 reserved 欄 + X 感測器欄。
        x_columns: X 製程參數欄名（不含任何 reserved 欄）。
        name: 資料集識別（如 'tep'、'pronto'）。

    Raises:
        ContractError: 建構時若 frame/x_columns 不符 raw 契約。
    """

    frame: pd.DataFrame
    x_columns: tuple[str, ...]
    name: str

    def __post_init__(self) -> None:
        validate_raw(self.frame, self.x_columns)
