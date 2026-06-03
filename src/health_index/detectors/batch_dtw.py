"""L5 批次軌跡偏移偵測：DTW 對齊 + 對正常參考批的形變距離（B4）。

批次製程每批長度不一（IndPenSim 835–1450 點）。本偵測器先 **降採樣到固定點數**（``_prep``）對齊長度，
再用 **DTW**（動態時間規整）量形變：對正常參考批集合的平均 DTW 距離，超過參考批內部距離校準的門檻
即判偏移。

**DTW 的角色誠實標記（紅隊 Rule 9/12）**：長度不一已由 resample 解決；DTW 在等長後**額外**買到「相位內
±band 步 warping 容忍」——當批次相位漂移（某發酵階段進展快慢不一）時，DTW 嚴格優於 resample-Euclidean
（見 ``test_dtw_beats_euclidean_on_phase_shift`` 之合成證明）。**但在當前 IndPenSim 上，resample-Euclidean
亦能分離 normal/faulty，DTW 的邊際增益未在此資料上證實**——DTW 為對相位漂移的防禦性/原則性選擇，非此資料的必要條件。

成本控制（Rule 6，dev_plan §6）：DTW 為 O(n²)→以 **降採樣固定點數（dtw_resample_len）+ Sakoe-Chiba
band（dtw_band）** 限縮（FastDTW 精神），封頂原始批長（835–1450）成本。

範圍誠實（Rule 12）：偵測「整段軌跡形狀偏移」；非所有 IndPenSim fault 都顯現為**全域軌跡形變**（部分
為局部/瞬時擾動），故 faulty 偵測率非 100%——只宣稱「faulty 批被旗標率明顯高於正常 hold-out」，不誇大。
**門檻校準前提**：``threshold_ = LOO mean + k·std`` 的「k=2 ≈ 5% 正常 FPR」**僅在參考批同質時成立**；
若參考批跨模態（如 IndPenSim 31–60 操作員、61–90 APC）內部變異膨脹會抬高門檻、降低靈敏度——故參考批
宜取純 recipe 同質段（如 batch 1–20）。偵測器確定性（Rule 5）：DTW 為純數學，無 RNG。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.spatial.distance import cdist

from ..config import DEFAULT, Config


@dataclass
class BatchDTW:
    """正常參考批上 fit（標準化 + 降採樣 + 門檻校準）並凍結，對新批算 DTW 形變分數。"""

    config: Config = field(default=DEFAULT)

    def _prep(self, batch: np.ndarray) -> np.ndarray:
        """標準化（用參考批 mean/std）+ 降採樣到固定點數。"""
        b = (np.asarray(batch, dtype=float) - self.mean_) / self.std_
        m = self.config.dtw_resample_len
        idx = np.linspace(0, len(b) - 1, m)
        lo = np.floor(idx).astype(int)
        hi = np.minimum(lo + 1, len(b) - 1)
        fr = (idx - lo)[:, None]
        return b[lo] * (1 - fr) + b[hi] * fr

    def _dtw(self, a: np.ndarray, b: np.ndarray) -> float:
        """Sakoe-Chiba banded DTW，回傳對 (len(a)+len(b)) 正規化的對齊距離。"""
        na, nb = len(a), len(b)
        w = max(int(self.config.dtw_band * max(na, nb)), abs(na - nb) + 1)
        cost = cdist(a, b)
        D = np.full((na + 1, nb + 1), np.inf)
        D[0, 0] = 0.0
        for i in range(1, na + 1):
            for j in range(max(1, i - w), min(nb, i + w) + 1):
                D[i, j] = cost[i - 1, j - 1] + min(D[i - 1, j], D[i, j - 1], D[i - 1, j - 1])
        return float(D[na, nb] / (na + nb))

    def fit(self, reference_batches: list) -> "BatchDTW":
        """以正常參考批 fit：標準化參數 + 降採樣參考集 + LOO 內部距離校準門檻。"""
        allX = np.vstack([np.asarray(b, dtype=float) for b in reference_batches])
        self.mean_ = allX.mean(axis=0)
        self.std_ = allX.std(axis=0) + 1e-9
        self.ref_ = [self._prep(b) for b in reference_batches]
        # leave-one-out：每個參考批對其餘參考批的平均 DTW → 正常內部變異的 null
        loo = []
        for i, bi in enumerate(self.ref_):
            loo.append(np.mean([self._dtw(bi, self.ref_[j]) for j in range(len(self.ref_)) if j != i]))
        d = np.asarray(loo)
        self.threshold_ = float(d.mean() + self.config.dtw_threshold_k * d.std())
        return self

    def score(self, batch: np.ndarray) -> float:
        """新批對正常參考集的平均 DTW 形變距離（越大越偏離正常軌跡）。"""
        b = self._prep(batch)
        return float(np.mean([self._dtw(b, r) for r in self.ref_]))

    def is_deviation(self, batch: np.ndarray) -> bool:
        """軌跡形變超過正常參考校準門檻即判偏移。"""
        return bool(self.score(batch) > self.threshold_)
