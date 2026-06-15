"""真實**非化工**含 Y adapter：UCI Steel Industry Energy Consumption（鋼廠用電）。

資料來源：UCI ML Repository #851（Sathishkumar et al. 2020, DAEWOO Steel Co. 韓國）。一座鋼廠 2018 全年
**逐 15 分鐘** 35040 列。第四類泛化資料集，與 CCPP 互補：CCPP 為 Folds5x2 shuffle（無時序），**Steel 有
真實時序**（連續監測，結構不同）→ benchmark 涵蓋「真實非化工含 Y」兩種結構。

可轉移性假設（Rule 1，明列）：
- **X＝4 電氣特徵**：``lag_react``（落後無功電量 kVarh）、``lead_react``（超前無功電量 kVarh）、
  ``lag_pf``（落後功率因數）、``lead_pf``（超前功率因數）。**Y＝``Usage_kWh`` 有效電能（連續軟量測標的）**。
- **刻意排除**：``CO2(tCO2)``（與 Usage 相關 0.988＝Y 代理，當 X 會洩漏）、``NSM``（午夜起秒數＝時間索引、
  非製程感測器）、``Load_Type``/``WeekStatus``（類別 regime/日曆，非連續感測器）。誠實標：避免循環/時間洩漏。
- **grade＝"A"（單一鋼廠＝單一產品）**；Load_Type（輕/中/最大負載）為日內操作循環，含於 golden 代表性段
  （非換產品 campaign）。**timestamp 為真實 15 分鐘鏈**（異於 CCPP 的合成索引）。
- p=4 低維 → L1 MinCovDet/L2 PCA/L4 全鏈皆可跑。

兩個註冊變體（鏡像 ccpp）：
- ``steel``（real）：``drift_mask=None``（誠實——無標註漂移）。證真實非化工 + 真實連續 Y 軟量測。
- ``steel_covert``：**明確標註半合成**——drift 段對 golden 最相關欄（hub＝lead_react）做**部分置換去相關**
  （邊際多重集精確保留→單變數 SPC 盲、僅多變量相關偏移→SPE 升）。Y 不動（covert 為 X-only）。
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..interface import GRADE_LABEL, TIMESTAMP, Y_TIMESTAMP, Y_VALUE, ProcessDataset

DEFAULT_DATA_DIR = os.path.join("data", "steel")
X_COLUMNS: tuple[str, ...] = ("lag_react", "lead_react", "lag_pf", "lead_pf")
Y_COLUMN = "Usage_kWh"
_RAW_COLS = {
    "Lagging_Current_Reactive.Power_kVarh": "lag_react",
    "Leading_Current_Reactive_Power_kVarh": "lead_react",
    "Lagging_Current_Power_Factor": "lag_pf",
    "Leading_Current_Power_Factor": "lead_pf",
}
_DOWNLOAD_URL = "https://archive.ics.uci.edu/static/public/851/steel+industry+energy+consumption.zip"


@dataclass(frozen=True)
class SteelGroundTruth:
    """Steel 的段/golden/drift 標記（供驗證斷言，不進入 ProcessDataset 契約）。"""

    segment_bounds: tuple[tuple[int, int, int, str], ...]
    golden_mask: np.ndarray
    x_columns: tuple[str, ...]
    drift_mask: np.ndarray | None
    covert_column: str | None


def _ensure_csv(data_dir: str) -> str:
    """確保乾淨 ``steel.csv`` 存在（首次由原始 csv 取所需欄 + 改簡名並快取）；回傳路徑。

    Raises:
        FileNotFoundError: steel.csv 與原始 Steel_industry_data.csv 皆不存在（附下載指引，供測試 skip）。
    """
    csv = os.path.join(data_dir, "steel.csv")
    if os.path.exists(csv):
        return csv
    raw = os.path.join(data_dir, "Steel_industry_data.csv")
    if os.path.exists(raw):
        df = pd.read_csv(raw).rename(columns=_RAW_COLS)
        df[list(X_COLUMNS) + [Y_COLUMN, "date"]].to_csv(csv, index=False)
        return csv
    raise FileNotFoundError(
        f"Steel 資料未就緒（缺 {csv} 與 {raw}）。請下載 {_DOWNLOAD_URL} 解壓到 {data_dir}"
        "（含 Steel_industry_data.csv），或直接放置 steel.csv（欄：lag_react,lead_react,lag_pf,lead_pf,Usage_kWh,date）。"
    )


def _inject_covert(
    X: np.ndarray, gstart: int, gend: int, dstart: int, dend: int, strength: float, seed: int
) -> tuple[np.ndarray, int]:
    """在 drift 段對 golden 最相關欄（hub）部分置換去相關（marginal 多重集不變）。同 ccpp 機制。

    Args:
        X: 全資料 (n,p)。 gstart,gend: golden 段（決定 hub）。 dstart,dend: drift 段。
        strength: 去相關強度 ∈[0,1]＝段內被重排列比例。 seed: 確定性種子。
    Returns:
        (Xc, hub_index)。
    """
    Xc = X.copy()
    Cg = np.corrcoef(X[gstart:gend], rowvar=False)
    hub = int(np.argmax(np.abs(Cg).sum(axis=1) - 1.0))
    rng = np.random.default_rng(seed)
    idx = np.arange(dstart, dend)
    k = int(round(float(np.clip(strength, 0.0, 1.0)) * len(idx)))
    if k >= 2:
        sel = rng.choice(idx, size=k, replace=False)
        Xc[sel, hub] = X[rng.permutation(sel), hub]
    return Xc, hub


def load(
    *,
    data_dir: str = DEFAULT_DATA_DIR,
    golden_frac: float = 0.4,
    covert: bool = False,
    covert_strength: float = 1.0,
    drift_frac: float = 0.3,
    seed: int = 0,
) -> tuple[ProcessDataset, SteelGroundTruth]:
    """載入 Steel → 統一契約 ProcessDataset + SteelGroundTruth（介面同 ccpp.load）。

    Args:
        data_dir: 含 ``steel.csv`` 或 ``Steel_industry_data.csv`` 的目錄。
        golden_frac: golden 佔前段比例。
        covert: True＝注入半合成隱性漂移（steel_covert）；False＝純真實（drift_mask=None）。
        covert_strength: covert 去相關強度 ∈[0,1]。
        drift_frac: covert 時 drift 段佔尾段比例。
        seed: covert 注入種子。

    Returns:
        (ProcessDataset, SteelGroundTruth)。

    Raises:
        FileNotFoundError: 資料未就緒（見 ``_ensure_csv``）。
    """
    df = pd.read_csv(_ensure_csv(data_dir))
    X = df[list(X_COLUMNS)].to_numpy(dtype=float)
    y = df[Y_COLUMN].to_numpy(dtype=float)
    n = len(df)
    g = max(2, int(golden_frac * n))
    ts = pd.to_datetime(df["date"], dayfirst=True, errors="coerce")  # 真實 15 分鐘時序
    if ts.isna().any():  # 格式異常 → 退回規則網格（誠實：仍為等距重放索引）
        ts = pd.date_range("2018-01-01", periods=n, freq="15min")
    golden_mask = np.zeros(n, dtype=bool)
    golden_mask[:g] = True

    if covert:
        d0 = max(int((1.0 - drift_frac) * n), g)
        Xc, hub = _inject_covert(X, 0, g, d0, n, covert_strength, seed)
        X = Xc
        drift_mask: np.ndarray | None = np.zeros(n, dtype=bool)
        drift_mask[d0:n] = True
        segment_bounds = ((0, 0, g, "A"), (1, g, d0, "A"), (2, d0, n, "A"))
        covert_column: str | None = X_COLUMNS[hub]
        name = "steel_covert"
    else:
        segment_bounds = ((0, 0, g, "A"), (1, g, n, "A"))
        drift_mask = None
        covert_column = None
        name = "steel"

    data: dict = {TIMESTAMP: ts, GRADE_LABEL: ["A"] * n}
    data.update({col: X[:, j] for j, col in enumerate(X_COLUMNS)})
    data[Y_VALUE] = y          # 真實有效電能（dense，每 15 分鐘皆有）
    data[Y_TIMESTAMP] = ts     # Y 與 X 同步可得（延遲模擬交 FrameSource）
    frame = pd.DataFrame(data)

    gt = SteelGroundTruth(
        segment_bounds=segment_bounds,
        golden_mask=golden_mask,
        x_columns=X_COLUMNS,
        drift_mask=drift_mask,
        covert_column=covert_column,
    )
    return ProcessDataset(frame=frame, x_columns=X_COLUMNS, name=name), gt
