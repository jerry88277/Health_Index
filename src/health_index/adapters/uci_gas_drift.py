"""真實集 adapter：UCI Gas Sensor Array Drift Dataset（B2）。

資料來源：UCI ML Repository #224（Vergara et al. 2012, *Sensors and Actuators B*）。16 個金屬氧化物
氣體感測器、每感測器 8 個特徵 → **128 維** X；6 種氣體；分 10 個 batch（橫跨 36 個月）。**感測器
隨時間老化 → 跨 batch 多變量漂移**，正對應本框架「同化學面板、不同時間、隱性多變量飄移」。

可轉移性假設（Rule 1，明列）：
- **X＝128 感測器特徵（製程參數）**；**grade_label＝氣體類別（gas1..gas6，對應產品 grade）**；
  **campaign＝batch（時間段）**；**golden＝batch1（最早/最新鮮的感測器期）**。
- drift 是**時間性**（跨 batch 感測器老化），非換產品；與合成資料的「換線後殘留飄移」結構不同，
  但數學形態一致（同參考分佈、後續期多變量偏移、單變數未必越界）。
- **golden 採 batch1 全 6 氣體（混合多模態）而非單一氣體**：任一單氣在 batch1 僅 ~30–98 樣本 < 2p
  （MSPC 跑不動）；混合後 n=445 > p=128，且實測 golden hold-out 不退化（PCA 殘差空間容得下多氣體
  cluster、未淹沒漂移訊號）——務實取捨，明列以免讀者誤判 golden 同質。
- 無 lab Y（本版僅氣體類別、無濃度欄）→ Y 全 NaN；L3 軟測量無標籤、交 GSI（紅隊 H1 雙路）。

格式：每 ``batchN.dat`` 為 libsvm 格式 ``<gas_class> <feat_idx>:<value> ...``（128 特徵）。

誠實標記（Rule 6 / Rule 12）：p=128 時 **L1 FastMCD（MinCovDet 需 n>2p；golden fit 子集 n≈222
< 2p=256 不滿足）與 L4 全 permutation（大 batch O(B·n²)）超出線上成本**——B2 以**可轉移的核心
L2 MSPC SPE**（marquee 隱性飄移偵測器，``is_anomaly`` 為 T²∨SPE 複合閘、SPE 為主訊號）展示 AC-4；
全鏈 L1/L4 的 PCA-score 降級列 backlog，不宣稱全 Health Index 已在 p=128 跑通。
"""

from __future__ import annotations

import os
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

DEFAULT_DATA_DIR = os.path.join("data", "uci_gas_drift", "Dataset")
N_BATCHES = 10
N_FEATURES = 128


@dataclass(frozen=True)
class GasDriftGroundTruth:
    """真實集的 batch/golden 標記，供驗證斷言（不進入 ProcessDataset 契約）。

    Attributes:
        batch_bounds: 每個 batch 的 (batch_id, start, end)，end 為 exclusive、依時間序拼接。
        golden_mask: 長度 n 的 bool 陣列，標記 golden（batch1）列。
        x_columns: X 欄名。
    """

    batch_bounds: tuple[tuple[int, int, int], ...]
    golden_mask: np.ndarray
    x_columns: tuple[str, ...]


def parse_batch(path: str) -> tuple[np.ndarray, np.ndarray]:
    """解析單一 ``batchN.dat``（libsvm 格式）。

    Returns:
        (X, gas)：X 為 (n, 128) float 特徵；gas 為 (n,) int 氣體類別。

    Raises:
        ValueError: 某列特徵數不為 128（格式異常，不靜默吞）。
    """
    rows: list[list[float]] = []
    gases: list[int] = []
    with open(path) as f:
        for line in f:
            parts = line.split()
            if not parts:
                continue
            gases.append(int(float(parts[0])))
            feats = [float(p.split(":")[1]) for p in parts[1:]]
            if len(feats) != N_FEATURES:
                raise ValueError(f"{path}: 期望 {N_FEATURES} 特徵，得到 {len(feats)}")
            rows.append(feats)
    return np.asarray(rows, dtype=float), np.asarray(gases, dtype=int)


def load(data_dir: str = DEFAULT_DATA_DIR) -> tuple[ProcessDataset, GasDriftGroundTruth]:
    """載入全部 10 個 batch → 統一契約 ProcessDataset + GasDriftGroundTruth。

    Args:
        data_dir: 含 ``batch1.dat``..``batch10.dat`` 的目錄（預設 ``data/uci_gas_drift/Dataset``）。

    Returns:
        (ProcessDataset, GasDriftGroundTruth)

    Raises:
        FileNotFoundError: 資料未下載/解壓（附下載指引，供測試 skip 判斷）。

    Invariant: batch 依 1..10 時間序拼接；golden_mask 標記 batch1。
    """
    paths = [os.path.join(data_dir, f"batch{b}.dat") for b in range(1, N_BATCHES + 1)]
    missing = [p for p in paths if not os.path.exists(p)]
    if missing:
        raise FileNotFoundError(
            f"UCI Gas Drift 資料未就緒（缺 {len(missing)} 檔，如 {missing[0]}）。"
            "請下載 https://archive.ics.uci.edu/static/public/224/ 的 zip 解壓到 "
            f"{data_dir}（含 batch1.dat..batch10.dat）。"
        )

    x_columns = tuple(f"s{i:03d}" for i in range(N_FEATURES))
    blocks_x: list[np.ndarray] = []
    grades: list[str] = []
    bounds: list[tuple[int, int, int]] = []
    golden_flags: list[np.ndarray] = []

    cursor = 0
    for b, path in enumerate(paths, start=1):
        X, gas = parse_batch(path)
        n = X.shape[0]
        blocks_x.append(X)
        grades.extend(f"gas{g}" for g in gas)
        bounds.append((b, cursor, cursor + n))
        golden_flags.append(np.full(n, b == 1))
        cursor += n

    X_all = np.vstack(blocks_x)
    n_total = X_all.shape[0]
    ts = pd.date_range("2008-01-01", periods=n_total, freq="h")

    # 一次建構全部欄（p=128，逐欄 assign 會碎片化觸發 PerformanceWarning）。
    data: dict = {TIMESTAMP: ts, GRADE_LABEL: grades}
    data.update({col: X_all[:, j] for j, col in enumerate(x_columns)})
    data[Y_VALUE] = np.full(n_total, np.nan)  # 本版無 lab Y（僅氣體類別）
    data[Y_TIMESTAMP] = pd.Series(pd.NaT, index=range(n_total), dtype="datetime64[ns]")
    frame = pd.DataFrame(data)

    gt = GasDriftGroundTruth(
        batch_bounds=tuple(bounds),
        golden_mask=np.concatenate(golden_flags),
        x_columns=x_columns,
    )
    return ProcessDataset(frame=frame, x_columns=x_columns, name="uci_gas_drift"), gt
