"""G2 資料源：``DataSource`` 協定 + 可測實作（FrameSource/ReplaySource）+ PISource stub。

D2 決策（docs/deployment_plan.md §4）：runner 只依賴 ``DataSource`` 協定，PI 被隔離在協定後 →
本機以公開資料集（FrameSource/ReplaySource）完整測試評分/告警邏輯，PI 那一哩（PISource）標
**NOT VERIFIED**、現場填實再實測（誠實邊界，Rule 12）。

瓶子優先：先用公開時序資料集做線上模擬（重放），之後把 PISource 換成真酒。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import numpy as np
import pandas as pd


@runtime_checkable
class DataSource(Protocol):
    """線上評分資料源的最小協定：依索引取時序窗（runner 唯一依賴此介面）。

    軟量測延遲到達（passive Y）由 ``y_arrivals_until`` 表達：只回傳 ``Y_TIMESTAMP`` ≤ 當前游標的 Y，
    模擬「收到軟量測後才被動分析」（PI backfill 也走同一語義——回看 lookback 窗重查）。
    """

    x_columns: tuple[str, ...]

    def __len__(self) -> int: ...

    def x_slice(self, start: int, end: int) -> np.ndarray:
        """回傳 [start,end) 列的 X 陣列（欄序＝x_columns）。"""
        ...


class FrameSource:
    """以任意 DataFrame（公開資料集）為時序源——重放/檔案投放的共用實作（完整可測）。

    Args:
        frame: 時序表（列＝時間序）。
        x_columns: X 欄名序（須存在於 frame）。
        y_value: 軟量測 Y 欄名（None＝無 Y）。
        y_timestamp: Y 量測時間欄名（用於延遲到達語義；None 則以列序近似）。
    """

    def __init__(self, frame: pd.DataFrame, x_columns, *, y_value: str | None = None, y_timestamp: str | None = None):
        self.frame = frame.reset_index(drop=True)
        self.x_columns = tuple(x_columns)
        missing = [c for c in self.x_columns if c not in self.frame.columns]
        if missing:
            raise ValueError(f"FrameSource: x_columns 不存在於 frame: {missing}")
        self._y_value = y_value
        self._y_timestamp = y_timestamp

    def __len__(self) -> int:
        return len(self.frame)

    def x_slice(self, start: int, end: int) -> np.ndarray:
        return self.frame.iloc[start:end][list(self.x_columns)].to_numpy(dtype=float)

    def y_arrivals_until(self, cursor: int) -> list[tuple[int, float]]:
        """回傳列索引 < cursor 且有觀測值的 (idx, y) ——模擬延遲 Y 在游標推進後才「到達」。"""
        if self._y_value is None or self._y_value not in self.frame.columns:
            return []
        yv = self.frame[self._y_value].to_numpy(dtype=float)
        out = []
        for i in range(min(cursor, len(yv))):
            if np.isfinite(yv[i]):
                out.append((i, float(yv[i])))
        return out


def replay_from_dataset(name: str, **build_kwargs) -> tuple[FrameSource, "GroundTruth"]:  # noqa: F821
    """便利：用 registry 建公開資料集 → FrameSource（線上模擬重放源）+ 其 GroundTruth（demo 標記用）。

    回傳 GroundTruth 供 UI 標示「哪段是 golden、哪段是已知 drift」以對照健康指標時間線。
    """
    from ..adapters import registry
    from ..interface import Y_VALUE, Y_TIMESTAMP

    ds, gt = registry.build(name, **build_kwargs)
    has_y = Y_VALUE in ds.frame.columns
    src = FrameSource(
        ds.frame,
        gt.x_columns,
        y_value=Y_VALUE if has_y else None,
        y_timestamp=Y_TIMESTAMP if Y_TIMESTAMP in ds.frame.columns else None,
    )
    return src, gt


class PISource:
    """PI Historian 資料源（**stub，NOT VERIFIED**）——現場填實並實測（docs/deployment_plan.md §4 D2）。

    本環境無 PI Server/SDK/憑證/真實 tag，無法執行或測試。協定隔離使未驗證表面僅限本類。
    現場整合 checklist（須逐項填實＋實測）：
      - SDK 選型：PI Web API（REST）vs AF SDK（.NET）。
      - X 取 **interpolated**（固定網格對齊偵測器等間隔假設）；Y 取 **recorded/actual**（真實 lab 值，不內插）。
      - 延遲 Y / backfill：被動 Y 鏈須回看 lookback 窗重查新落地的 Y，用 Y_TIMESTAMP 對齊對應 X 時刻。
      - 時區/UTC 一致；PI point quality/substituted 旗標 → 映射 L1 資料效度閘（非正常值不可餵入）。
      - tag→x_column 映射（per-product 設定檔）；認證（Kerberos/basic）；取樣率與 takt/10 節拍一致。
    """

    def __init__(self, *args, **kwargs):  # pragma: no cover - stub
        raise NotImplementedError(
            "PISource 為 stub（NOT VERIFIED）：請依 docstring checklist 在現場填實 PI 介接並實測；"
            "本機線上模擬請改用 FrameSource/replay_from_dataset（公開資料集）。"
        )
