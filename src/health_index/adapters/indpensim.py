"""批次製程 adapter：IndPenSim — Industrial-scale Penicillin Fermentation（B4 / L5）。

資料來源：Goldrick et al.（Mendeley npt257bjxn）。100 批 fed-batch 發酵；每批為**長度不一**的製程
時序軌跡（835–1450 取樣點，Time 0→~230h）。已知結構（見 ``continuous_datasets_survey.md``）：
batch 1–30 recipe 驅動、31–60 操作員、61–90 APC+Raman、**91–100 含 fault**。

可轉移性假設（Rule 1，明列）：
- **批次模式 ≠ 連續模式**：連續型（L1–L4）監看穩態多變量域；批次型監看**整段軌跡形狀**。每批長度不一
  →以 **DTW 對齊**比軌跡。故 batch adapter **不套連續 ``interface.ProcessDataset`` 契約**（那是逐樣本
  穩態用），改回傳 ``BatchDataset``（一批一條軌跡），交 L5 ``BatchDTW``（Rule 3：不破壞連續骨架）。
- **標籤＝資料驅動**：用 CSV 的 **``Fault reference``（Fault_ref）欄**（乾淨 0/1，實測恰好 batch 91–100
  為 1、1–90 為 0，與 survey 文件結構雙重佐證）逐批導出 normal/faulty。**注意**：另一欄「Fault flag」
  （末欄）值異常（非 0/1、每批數千 unique），不可信、不使用（Rule 8 不臆測）。
- **normal 內部仍含三模態**（survey）：1–30 recipe 驅動、31–60 操作員、61–90 APC+Raman。L5 參考批宜取
  **純 recipe 同質段（如 1–20）**以免模態混入膨脹門檻校準（見 ``batch_dtw`` 門檻前提）。

效能（Rule 6）：原始 ``100_Batches_IndPenSim_V3.csv`` 2.57GB（含 ~2200 欄 Raman）。本 adapter 僅取前
39 欄（製程變數 + 旗標/參考欄，``N_PROCESS_COLS``），首次抽出快取為 ``process_only.csv``（~21MB）；
之後直接讀快取。
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import numpy as np
import pandas as pd

DEFAULT_DIR = os.path.join("data", "indpensim")
RAW_CSV = "100_Batches_IndPenSim_V3.csv"
CACHE_CSV = "process_only.csv"
N_BATCHES = 100
N_PROCESS_COLS = 39  # 前 39 欄＝製程變數 + batch/fault 旗標（其餘為 Raman）
TIME_COL = "Time (h)"
FAULT_REF_COL = "Fault reference(Fault_ref:Fault ref)"  # 乾淨 0/1 fault 旗標（標籤來源）
# 線上連續製程變數（排除 Time、offline 稀疏欄、旗標/參考欄）——軌跡比對用。
_EXCLUDE_TOKENS = ("offline", "Time", "Fault", "ref", "Raman", "PAT", "Batch", "flag", "Control")


@dataclass(frozen=True)
class BatchDataset:
    """批次製程資料：每批一條（長度不一）多變量軌跡（不入連續 ProcessDataset 契約）。

    Attributes:
        batches: 長度 N 的 list，每元素 (T_i, p) float 軌跡（T_i 不一）。
        batch_ids: 批次編號（1..N）。
        labels: 每批 'normal' / 'faulty'（IndPenSim 文件結構 1–90 / 91–100）。
        x_columns: 製程變數欄名。
        name: 資料集識別。
    """

    batches: list
    batch_ids: list
    labels: list
    x_columns: tuple
    name: str


def _ensure_cache(data_dir: str) -> str:
    """確保 process_only.csv 存在：缺則自 2.57GB 原檔抽前 39 欄快取。回傳快取路徑。"""
    cache = os.path.join(data_dir, CACHE_CSV)
    if os.path.exists(cache):
        return cache
    raw = os.path.join(data_dir, RAW_CSV)
    if not os.path.exists(raw):
        raise FileNotFoundError(
            f"IndPenSim 資料未就緒（缺 {cache} 與 {raw}）。請下載 Mendeley npt257bjxn 的 "
            f"{RAW_CSV}（2.57GB）至 {data_dir}/。"
        )
    df = pd.read_csv(raw, usecols=list(range(N_PROCESS_COLS)))  # 只取製程欄，避開 Raman（Rule 6）
    df.to_csv(cache, index=False)
    return cache


def load(data_dir: str = DEFAULT_DIR) -> BatchDataset:
    """載入 IndPenSim → BatchDataset（依 Time 重置切 100 批）。

    Raises:
        FileNotFoundError: 原檔與快取皆不存在（附下載指引）。

    Invariant: 批次依 Time(h) 由大轉小（下一批重置）切分；batch_ids 為 1..100、labels 91–100=faulty。
    """
    cache = _ensure_cache(data_dir)
    df = pd.read_csv(cache)
    x_columns = tuple(
        c for c in df.columns if not any(tok.lower() in c.lower() for tok in _EXCLUDE_TOKENS)
    )
    X = df[list(x_columns)].to_numpy(dtype=float)
    t = df[TIME_COL].to_numpy()
    fref = df[FAULT_REF_COL].to_numpy()
    starts = np.concatenate([[0], np.where(np.diff(t) < 0)[0] + 1])
    ends = np.concatenate([starts[1:], [len(t)]])

    batches = [X[s:e] for s, e in zip(starts, ends)]
    batch_ids = list(range(1, len(batches) + 1))
    # 資料驅動標籤：批內 Fault_ref 出現 >0 即 faulty（實測恰標 91–100，與 survey 雙重佐證）
    labels = ["faulty" if fref[s:e].max() > 0 else "normal" for s, e in zip(starts, ends)]
    return BatchDataset(
        batches=batches, batch_ids=batch_ids, labels=labels, x_columns=x_columns, name="indpensim"
    )
