"""真實**非化工**含 Y adapter：UCI Combined Cycle Power Plant（CCPP）。

資料來源：UCI ML Repository #294（Tüfekci 2014, *Int. J. Electrical Power & Energy Systems* 60:126-140；
Kaya & Tüfekci 2012）。一座聯合循環發電廠（2 氣渦輪 + 1 蒸汽渦輪）6 年逐時資料，**9568 列**。
這是泛化的關鍵第三類資料集：**真實、非化工、且有真實連續 Y 軟量測標的**（補足 synthetic/TEP/penicillin
皆化工或合成、uci_gas_drift 雖非化工但無 Y 之缺口；generalization_roadmap §4）。

可轉移性假設（Rule 1，明列）：
- **X＝環境操作條件（4 維）**：``AT`` 環境溫度(°C)、``V`` 排氣真空(cm Hg)、``AP`` 環境氣壓(mbar)、
  ``RH`` 相對濕度(%)。**Y＝``PE`` 淨逐時發電量(MW)**——真實量測的 soft-sensor 標的（非合成）。
- **grade＝"A"（單一電廠＝單一產品，單一模型）**；無換產品 campaign。
- **公開版為 Folds5x2 交叉驗證 shuffle，列序非真實時序**（誠實標，Rule 12）→ ``timestamp`` 為**重放索引**
  （線上模擬節拍用），非真實 chronology；故本資料集**無真實時間性漂移**。
- p=4 低維 → **L1 MinCovDet（需 n>2p=8）/ L2 PCA / L4 全鏈皆可跑**（與 uci p=128 降級路徑不同，CCPP
  端到端驗證低維全鏈於真實非化工資料）。

兩個註冊變體：
- ``ccpp``（real）：``drift_mask=None``（誠實——shuffle 後無標註漂移）。用途＝證「真實非化工 + 真實 Y」
  上 golden 健康、不誤報，並為 C2 軟量測 Ŷ/可信度提供真實 Y。
- ``ccpp_covert``：**明確標註半合成**——在 drift 段對 golden 最相關欄（hub，CCPP 為 AT）做**部分置換
  去相關**：被選列的 hub 欄值在段內互相重排 → **該欄邊際多重集精確保留**（單變數 SPC 結構性盲）、僅
  多變量相關結構偏移 → **SPE 升、早於單變數 SPC**。鏡像 ``synthetic.py`` 的「擾動載荷方向但逐列重正規化
  保各變數邊際」隱性飄移意旨，落在**真實特徵基底**上。Y(PE) 不動（covert 注入為 X-only）。
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..interface import GRADE_LABEL, TIMESTAMP, Y_TIMESTAMP, Y_VALUE, ProcessDataset

DEFAULT_DATA_DIR = os.path.join("data", "ccpp")
X_COLUMNS: tuple[str, ...] = ("AT", "V", "AP", "RH")
Y_COLUMN = "PE"
_DOWNLOAD_URL = "https://archive.ics.uci.edu/static/public/294/combined+cycle+power+plant.zip"


@dataclass(frozen=True)
class CCPPGroundTruth:
    """CCPP 的段/golden/drift 標記（供驗證斷言，不進入 ProcessDataset 契約）。

    Attributes:
        segment_bounds: 每段 (id, start, end, label)，end 為 exclusive。
        golden_mask: 長度 n 的 bool，標記 golden（建模基準）列。
        x_columns: X 欄名。
        drift_mask: 長度 n 的 bool（半合成 covert 注入列）；real 變體為 None（誠實，無標註漂移）。
        covert_column: covert 注入去相關的欄名；real 變體為 None。
    """

    segment_bounds: tuple[tuple[int, int, int, str], ...]
    golden_mask: np.ndarray
    x_columns: tuple[str, ...]
    drift_mask: np.ndarray | None
    covert_column: str | None


def _ensure_csv(data_dir: str) -> str:
    """確保 ``ccpp.csv`` 存在（首次由解壓出的 xlsx 讀一次並快取）；回傳 csv 路徑。

    Raises:
        FileNotFoundError: csv 與 xlsx 皆不存在（附下載指引，供測試 skip 判斷）。
    """
    csv = os.path.join(data_dir, "ccpp.csv")
    if os.path.exists(csv):
        return csv
    xlsx = os.path.join(data_dir, "CCPP", "Folds5x2_pp.xlsx")
    if os.path.exists(xlsx):
        pd.read_excel(xlsx, sheet_name="Sheet1").to_csv(csv, index=False)
        return csv
    raise FileNotFoundError(
        f"CCPP 資料未就緒（缺 {csv} 與 {xlsx}）。請下載 {_DOWNLOAD_URL} 解壓到 {data_dir}"
        "（含 CCPP/Folds5x2_pp.xlsx），或直接放置 ccpp.csv（欄：AT,V,AP,RH,PE）。"
    )


def _inject_covert(
    X: np.ndarray, gstart: int, gend: int, dstart: int, dend: int, strength: float, seed: int
) -> tuple[np.ndarray, int]:
    """在 drift 段 [dstart,dend) 對 golden 最相關欄（hub）做部分置換去相關（marginal 多重集不變）。

    去相關 hub 欄對多變量殘差（SPE）衝擊最大；置換保證該欄邊際分佈精確不變（單變數 SPC 盲）。

    Args:
        X: 全資料 (n,p)。
        gstart,gend: golden 段（用以決定 hub＝相關結構最中心的欄）。
        dstart,dend: drift 段（注入區間）。
        strength: 去相關強度 ∈[0,1]＝段內被重排列的比例（1＝全段重排，近零相關）。
        seed: 重抽種子（確定性）。

    Returns:
        (Xc, hub_index)：Xc 為注入後副本；hub_index 為被去相關的欄索引。
    """
    Xc = X.copy()
    Cg = np.corrcoef(X[gstart:gend], rowvar=False)
    hub = int(np.argmax(np.abs(Cg).sum(axis=1) - 1.0))  # 與其他欄總相關最高者
    rng = np.random.default_rng(seed)
    idx = np.arange(dstart, dend)
    k = int(round(float(np.clip(strength, 0.0, 1.0)) * len(idx)))
    if k >= 2:
        sel = rng.choice(idx, size=k, replace=False)
        Xc[sel, hub] = X[rng.permutation(sel), hub]  # 被選列 hub 欄值互相重排→邊際不變、相關被破壞
    return Xc, hub


def load(
    *,
    data_dir: str = DEFAULT_DATA_DIR,
    golden_frac: float = 0.4,
    covert: bool = False,
    covert_strength: float = 1.0,
    drift_frac: float = 0.3,
    seed: int = 0,
) -> tuple[ProcessDataset, CCPPGroundTruth]:
    """載入 CCPP → 統一契約 ProcessDataset + CCPPGroundTruth。

    Args:
        data_dir: 含 ``ccpp.csv`` 或 ``CCPP/Folds5x2_pp.xlsx`` 的目錄。
        golden_frac: golden（建模基準）佔前段比例。
        covert: True＝注入半合成隱性漂移（ccpp_covert 變體）；False＝純真實（drift_mask=None）。
        covert_strength: covert 去相關強度 ∈[0,1]（僅 covert=True 有效）。
        drift_frac: covert 時 drift 段佔尾段比例（僅 covert=True 有效）。
        seed: covert 注入種子（確定性）。

    Returns:
        (ProcessDataset, CCPPGroundTruth)。real 變體 drift_mask=None；covert 變體標記尾段 drift。

    Raises:
        FileNotFoundError: 資料未就緒（見 ``_ensure_csv``）。

    Invariant: golden 段 [0, golden_frac·n)；covert 時 drift 段 [(1−drift_frac)·n, n) 注入、其餘真實。
    """
    df = pd.read_csv(_ensure_csv(data_dir))
    X = df[list(X_COLUMNS)].to_numpy(dtype=float)
    y = df[Y_COLUMN].to_numpy(dtype=float)
    n = len(df)
    g = max(2, int(golden_frac * n))
    ts = pd.date_range("2010-01-01", periods=n, freq="h")  # 重放索引（非真實時序，見模組 docstring）
    golden_mask = np.zeros(n, dtype=bool)
    golden_mask[:g] = True

    if covert:
        d0 = int((1.0 - drift_frac) * n)
        d0 = max(d0, g)  # drift 段不與 golden 重疊
        Xc, hub = _inject_covert(X, 0, g, d0, n, covert_strength, seed)
        X = Xc
        drift_mask = np.zeros(n, dtype=bool)
        drift_mask[d0:n] = True
        segment_bounds = ((0, 0, g, "A"), (1, g, d0, "A"), (2, d0, n, "A"))
        covert_column: str | None = X_COLUMNS[hub]
        drift_out: np.ndarray | None = drift_mask
        name = "ccpp_covert"
    else:
        segment_bounds = ((0, 0, g, "A"), (1, g, n, "A"))
        covert_column = None
        drift_out = None
        name = "ccpp"

    data: dict = {TIMESTAMP: ts, GRADE_LABEL: ["A"] * n}
    data.update({col: X[:, j] for j, col in enumerate(X_COLUMNS)})
    data[Y_VALUE] = y                 # 真實量測淨發電量（dense，每步皆有）
    data[Y_TIMESTAMP] = ts            # Y 與 X 同步可得（CCPP 無延遲；延遲模擬交 FrameSource）
    frame = pd.DataFrame(data)

    gt = CCPPGroundTruth(
        segment_bounds=segment_bounds,
        golden_mask=golden_mask,
        x_columns=X_COLUMNS,
        drift_mask=drift_out,
        covert_column=covert_column,
    )
    return ProcessDataset(frame=frame, x_columns=X_COLUMNS, name=name), gt
