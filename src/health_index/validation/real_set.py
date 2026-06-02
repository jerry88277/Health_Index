"""真實集 AC-4 驗證：UCI Gas Drift 上「同邏輯零調參、golden 不退化 + 真實漂移被抓」（B2）。

紅隊 D2 / dev_plan §2：合成 oracle 不能自證，正式採用門檻＝**真實集不退化**。本模組在 UCI Gas Drift
（真實感測器跨 batch 老化）上跑**核心 L2 MSPC SPE**（marquee 隱性飄移偵測器），檢核：
- **AC-4a（不退化）**：golden（batch1）hold-out 的 SPE 異常率 ≈ α 地板（不誤報）。
- **AC-4b（真實漂移被抓）**：後續至少某些 batch（感測器老化）SPE 異常率明顯高於 golden。
**零 per-dataset 調參**（預設 config）。

範圍誠實（Rule 6/12）：p=128 時 L1 FastMCD（MinCovDet 需 n>2p；golden fit 子集 n≈222 < 2p=256
不滿足）與 L4 全 permutation（大 batch O(B·n²)）超出線上成本，本驗證以可轉移的 L2 MSPC 為證；
全鏈 PCA-score 降級列 backlog——不宣稱全 Health Index 已在 p=128 跑通。真實漂移**非單調**（資料集
有已知重校事件），故只斷言「存在被抓的漂移 batch」，不斷言逐 batch 單調升（那會是對真實資料造假，
Rule 12）。注：golden hold-out 異常率隨 split seed 有變異（單 seed 報點值非統計確定性，多 seed 帶列
backlog）。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..adapters import uci_gas_drift as gas
from ..detectors.mspc import MSPCModel


@dataclass
class RealSetResult:
    """UCI Gas Drift 上的 AC-4 檢核結果。"""

    golden_holdout_anom: float
    batch_anom: dict
    ac4a_golden_not_degrade: bool
    ac4b_drift_detected: bool

    @property
    def all_pass(self) -> bool:
        return self.ac4a_golden_not_degrade and self.ac4b_drift_detected


def evaluate_gas_drift(data_dir: str = gas.DEFAULT_DATA_DIR, *, seed: int = 0) -> RealSetResult:
    """在 UCI Gas Drift 上以 L2 MSPC 檢核 AC-4（golden 不退化 + 真實漂移被抓）。

    Raises:
        FileNotFoundError: 資料未下載（由 ``gas.load`` 拋出，附下載指引）。
    """
    ds, gt = gas.load(data_dir)
    cols = list(ds.x_columns)
    X = ds.frame[cols].to_numpy()

    Xg_all = X[gt.golden_mask]
    rng = np.random.default_rng(seed)
    idx = rng.permutation(len(Xg_all))
    h = len(Xg_all) // 2
    Xfit, Xhold = Xg_all[idx[:h]], Xg_all[idx[h:]]

    m = MSPCModel().fit(Xfit)  # 預設 config，零 per-dataset 調參
    hold_anom = float(m.is_anomaly(Xhold).mean())
    batch_anom = {bid: float(m.is_anomaly(X[s:e]).mean()) for bid, s, e in gt.batch_bounds if bid != 1}
    max_later = max(batch_anom.values())

    return RealSetResult(
        golden_holdout_anom=round(hold_anom, 4),
        batch_anom={k: round(v, 4) for k, v in batch_anom.items()},
        ac4a_golden_not_degrade=hold_anom < 0.10,           # ≈ α 地板的 ~10× 容忍帶
        ac4b_drift_detected=max_later > hold_anom + 0.2,    # 至少某 batch 明顯高於 golden
    )
