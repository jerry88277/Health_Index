"""統一資料集協定（桶1，泛化地基）。

加法層（Rule 3：**不動 ``interface.py`` 骨架**）：把現況各自為政的 adapter（``generate``/``load``
入口名不一 + 三個欄位重疊的 ``*GroundTruth``）收斂到單一 **builder 型別** + **共用 ``GroundTruth``**，
供 ``registry`` 與後續 benchmark harness 統一消費。既有 adapter **不必改**；``registry`` 以轉換器包裝
其 bespoke 真值即合規（方案 A 鴨子型別，見 ``docs/generalization_roadmap.md`` §3）。

不變式：``GroundTruth`` 的 mask 長度一致、``segments`` 不越界。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from ..interface import ProcessDataset


@dataclass(frozen=True)
class Segment:
    """一個 campaign/batch 區間（``end`` exclusive）。

    Attributes:
        id: 區間序號（synthetic/tep 用 0-based 順序；uci 用 batch 編號）。
        start: 起始列位（含）。
        end: 結束列位（不含）。
        label: 區間標籤（grade/產品/氣體類別/batch 名）。
    """

    id: int
    start: int
    end: int
    label: str


@dataclass(frozen=True)
class GroundTruth:
    """統一真值——任一 adapter 經 registry 轉換後回傳此，供評估/benchmark 統一消費。

    取代三個重疊的 ``SyntheticGroundTruth``/``TEPGroundTruth``/``GasDriftGroundTruth``（欄位
    golden_mask/x_columns/bounds 各自定義）。**不入 ``ProcessDataset`` 契約**（真值僅供驗證）。

    Attributes:
        x_columns: X 欄名。
        golden_mask: (n,) bool，標 golden 基準列（凍結建模用）。
        segments: campaign/batch 區間（依時間序、不重疊）。
        drift_mask: (n,) bool，標**已知**殘留漂移列；``None``＝無標註真值（如真實感測器老化集，
            漂移時間性而無逐列 ground-truth）。

    Raises:
        ValueError: mask 長度不一致、或 segment 越界（fail loud，Rule 12）。

    不變式：``len(golden_mask) == len(drift_mask)``（若有）；每個 segment 滿足 0≤start<end≤n。
    """

    x_columns: tuple[str, ...]
    golden_mask: np.ndarray
    segments: tuple[Segment, ...]
    drift_mask: np.ndarray | None = None

    def __post_init__(self) -> None:
        n = len(self.golden_mask)
        if self.drift_mask is not None and len(self.drift_mask) != n:
            raise ValueError(f"drift_mask 長度 {len(self.drift_mask)} != golden_mask 長度 {n}")
        for s in self.segments:
            if not (0 <= s.start < s.end <= n):
                raise ValueError(f"segment 越界（n={n}）: {s}")

    @property
    def n(self) -> int:
        """樣本數（由 golden_mask 長度推得）。"""
        return len(self.golden_mask)

    @property
    def has_labeled_drift(self) -> bool:
        """是否帶逐列漂移真值（真實老化集常為 False）。"""
        return self.drift_mask is not None and bool(np.asarray(self.drift_mask).any())


# Builder 型別（方案 A 鴨子型別）：任一 ``build(**kwargs) -> (ProcessDataset, GroundTruth)`` 的可呼叫
# 物件即合規。用 Callable 別名而非 runtime_checkable Protocol——對自由函式 isinstance 無實質保證，
# 別名足以做型別註記與文件約束（Rule 2 不過度設計）。
DatasetBuilder = Callable[..., "tuple[ProcessDataset, GroundTruth]"]
