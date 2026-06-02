"""Health Index 融合 + campaign re-entry 觸發（判斷鏈收口）。

把 L1/L2/L4 偵測器在 golden-A 上 fit 並凍結，對 campaign 算各層 0–1 子分數（1=健康），加權成
0–1 Health Index。依紅隊：
- **方向統一**：所有子分數「越高越健康」。
- **決策＝融合趨勢分數 + 硬閘安全網（雙軌，紅隊 H8）**：is_alarm = HI<門檻 OR 任一單層硬閘。
  這**不是**嚴格「單一決策點」（紅隊 N2 的理想）——硬閘是 H8 的安全網，防致命破壞被融合平均稀釋。
  誠實標記（Rule 12）：嚴格 FWER 控制與持續性閾值（config.fwer_method/drift_persistence_k）**M6 未接線**，
  為 M9 待辦；硬閘的「自然必要性」（融合漏、硬閘獨抓）在合成資料無法產生（漂移使兩者同時觸發），
  此處僅機制性驗證硬閘路徑，自然場景待 TEP/真實單層致命故障驗證。
- **re-entry 觸發**：偵測「換產品（非 A grade）後第一段 A」。**維修型 re-entry**（同 grade A 中停機）
  需 mode=maintenance 資料支援，synthetic 無此事件，列 M-later TODO（不宣稱已實作）。

注：融合權重（config.fusion_weights）與門檻為 MVP 簡單加權（Rule 2）；紅隊 N6 要求「各分量→對 golden
null 尾機率」再加權，目前 s_l1/s_l2 為**比例近似**、s_l4 為 exp 衰減（非嚴格尾機率），屬已知設計債，
M9 校準。L3 軟測量可信度（CP/GSI）為獨立「Ŷ 可否信」旗標，不併入健康分數（語義不同）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .config import DEFAULT, Config
from .detectors.dqi_x import DQIxGate
from .detectors.drift import DriftDetector
from .detectors.mspc import MSPCModel
from .interface import CAMPAIGN_ID, GRADE_LABEL, ProcessDataset


@dataclass
class HealthIndex:
    """L1/L2/L4 融合健康度。fit(golden-A) → health_index / hard_gates / is_alarm。"""

    config: Config = field(default=DEFAULT)  # 融合權重在 config.fusion_weights（單一 config 治理，D1）

    def fit(self, X_golden: np.ndarray) -> "HealthIndex":
        self.dqi_ = DQIxGate(self.config).fit(X_golden)
        self.mspc_ = MSPCModel(self.config).fit(X_golden)
        self.drift_ = DriftDetector(self.config).fit(X_golden)
        return self

    def subscores(self, X: np.ndarray) -> dict[str, float]:
        """各層 0–1 健康子分數（1=健康；方向統一）。"""
        s_l1 = float(self.dqi_.is_inlier(X).mean())          # 域內樣本比例
        s_l2 = float(1.0 - self.mspc_.is_anomaly(X).mean())  # in-control 樣本比例
        z = float(self.drift_.wasserstein_magnitude(X))
        s_l4 = float(np.exp(-max(z, 0.0) / self.config.drift_scale))  # 漂移越大越低
        return {"L1": s_l1, "L2": s_l2, "L4": s_l4}

    def health_index(self, X: np.ndarray) -> float:
        """0–1 融合健康分數（1=健康）。"""
        s = self.subscores(X)
        return float(np.average([s["L1"], s["L2"], s["L4"]], weights=self.config.fusion_weights))

    def hard_gates(self, X: np.ndarray) -> dict[str, bool]:
        """單層硬閘（任一 True＝該層嚴重破限）；避免致命破壞被融合稀釋。"""
        return {
            "L1": bool(self.dqi_.is_inlier(X).mean() < 0.5),
            "L2": bool(self.mspc_.is_anomaly(X).mean() > 0.5),
            "L4": bool(self.drift_.is_drift(X)),
        }

    def is_alarm(self, X: np.ndarray) -> bool:
        """唯一告警決策點：融合分數低於門檻，或任一單層硬閘破限。"""
        return bool(self.health_index(X) < self.config.hi_alarm_threshold or any(self.hard_gates(X).values()))


def detect_reentry_campaigns(dataset: ProcessDataset, *, golden_grade: str = "A") -> list[int]:
    """偵測 re-entry campaign：grade==golden_grade 且其前一個 campaign 為**非** golden_grade。

    即「**換產品**後第一段 A」；第一個 golden campaign 不算 re-entry。需先經 preprocess.segment
    填入 campaign_id/grade_label。

    範圍誠實標記（Rule 12）：僅偵測 **grade 切換型** re-entry。**維修型**（同 grade A 中停機，
    mode=maintenance）不換 grade、campaign 不切分，本函式**抓不到**——待 maintenance 資料就緒
    時以 MODE 切分擴充（M-later TODO）。

    Returns: re-entry campaign_id 清單（依出現順序）。
    """
    fr = dataset.frame
    grades = fr.groupby(CAMPAIGN_ID)[GRADE_LABEL].first().sort_index()
    reentry: list[int] = []
    prev = None
    for cid, g in grades.items():
        if g == golden_grade and prev is not None and prev != golden_grade:
            reentry.append(int(cid))
        prev = g
    return reentry
