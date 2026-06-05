"""連續製程 adapter：Tennessee Eastman Process（TEP）真實資料 + 隱性飄移情境。

資料來源：MMFDD-TEP（GitHub Lichen0102，多模態 TEP）。每個 ``.mat`` 為 (7201, 81)：cols 0-40＝
XMEAS1-41、cols 41-52＝XMV1-12、cols 53-80＝IDV1-28 故障旗標。72h、~36s 取樣。

**驗證發現（紅隊 Rule 12，務必誠實）**：在 9 個真實 TEP 故障（IDV 3/5/8/9/10/11/12/13/15）上實測，
**沒有一個重現「單變數盲、多變量抓」的隱性飄移**——真實故障要嘛單變數也抓得到（IDV8/13，univ=1.0）、
要嘛兩者都抓不到（IDV3/9/15，≈baseline）。原因：合成資料是**刻意**只擾動相關結構保邊際；真實 TEP
故障是操作點位移，位移夠大單變數就見、夠小則兩者皆盲。X→Y 映射飄移（軟測量）亦然：會斷裂映射的
IDV13/8，X-MSPC 也都觸發。

（其餘 IDV 5/10/11/12 歸「兩者皆抓得到或皆盲」類，無一例外。）

**故本情境的隱性飄移＝注入（明確標記，非真實故障）**：取**真實 TEP 正常運轉資料**（Mode1 m1d00），
在「drift 回歸段」對相關性最高的若干 XMEAS 變數**獨立打亂時間順序**——每個變數的邊際分佈**完全不變**
（同批值重排）故單變數 3σ 盲，但變數間相關結構被破壞。

**抓手歸因（紅隊實證，誠實標記）**：drift 的告警**主要由 L4 觸發**——相關被破壞使資料在 golden PCA
**分數空間**的分佈位移（注意：邊際保留**僅限原始變數空間**，投影到 PCA 分數後邊際會位移，這正是 L4
抓得到的原因），L4 子分數崩到 ~0.01、硬閘恆 True。**L2/SPE 為輔助訊號**（anomaly≈0.41–0.51，徘徊在
0.5 硬閘門檻下緣，單獨不穩定觸發）。X 與 Y 的配對被打亂 → 軟測量 Ŷ 偏離實際 Y（Y 健康抓到）。
實測：單變數 univ≈0.04（盲）、HI drift 0.55 vs 乾淨 0.95。

**這是真實 TEP 結構 + 受控注入飄移的半合成情境**，非宣稱真實故障隱性。可轉移性免責（Rule 1）：注入
（打亂時序）為**人造刺激**，用以演示偵測器對「邊際不變、相關破壞」型飄移的敏感度，**不對應特定真實
失效物理**；且 pool iid 重抽消除時間結構，本情境**僅證受控注入飄移可被抓，不證真實 TEP 時序漂移可被抓**。

模態切換＝換產品（操作點變動，正常會被偵測，等同 synthetic 的 B/C）：
golden A（Mode1）→ B（Mode3，G/H≈90/10）→ 乾淨回歸 A（Mode1）→ C（Mode2，10/90）→ drift 回歸 A
（Mode1 + 注入關係飄移）。

X/Y：X＝XMEAS1-22（製程感測器）；Y＝產品成分 G/H（XMEAS40/41＝cols 39/40，稀疏抽樣模擬實驗室
量測，X→Y 延遲 2h 交 ``preprocess.align`` 估計）。輸出與 ``synthetic.generate`` 同契約，既有端點可直接吃。
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import numpy as np
import pandas as pd
import scipy.io

from ..interface import GRADE_LABEL, TIMESTAMP, Y_TIMESTAMP, Y_VALUE, ProcessDataset

DEFAULT_DIR = os.path.join("data", "tep")
XMEAS_COLS = list(range(0, 22))   # XMEAS1-22 製程感測器 = X
G_COL, H_COL = 39, 40             # XMEAS40=產品 G、XMEAS41=產品 H = Y（品質）
_STATIONARY = slice(500, 3500)    # Mode1/2/3 平穩區（去啟動暫態；TEP 閉迴路 72h 內慢非平穩）
# 模態檔 → grade/角色。各 campaign 自所屬模態的平穩 pool **iid 重抽**（同分佈→乾淨回歸健康；
# 真實 TEP 在 72h 內非平穩，逐窗切會誤判 clean，故以 pool 重抽消除非平穩混淆，誠實標記）。
_PLAN = [
    ("m1d00", "A", "golden"),   # Mode1 正常：健康基準
    ("m3d00", "B", "other"),    # Mode3：換產品 B
    ("m1d00", "A", "clean"),    # Mode1 正常：乾淨換線回歸
    ("m2d00", "C", "other"),    # Mode2：換產品 C
    ("m1d00", "A", "drift"),    # Mode1 正常 + 注入關係飄移：殘留隱性飄移回歸
]


@dataclass(frozen=True)
class TEPGroundTruth:
    """TEP 情境真值（供測試/前端斷言，不入 ProcessDataset 契約）。

    Attributes:
        campaign_bounds: 每 campaign 的 (start, end, grade)，end exclusive。
        golden_mask: 標記 golden-A（建基準）列。
        drift_mask: 標記注入隱性飄移的列。
        x_columns: X 欄名。
    """

    campaign_bounds: tuple
    golden_mask: np.ndarray
    drift_mask: np.ndarray
    x_columns: tuple


def _load_mat(name: str, data_dir: str) -> np.ndarray:
    path = os.path.join(data_dir, name + ".mat")
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"TEP 資料未就緒（缺 {path}）。請自 MMFDD-TEP（GitHub Lichen0102）下載 M1/M2/M3 的 "
            f"{name}.mat 至 {data_dir}/。"
        )
    return scipy.io.loadmat(path)[name].astype(float)


def _inject_relationship_drift(X: np.ndarray, golden: np.ndarray, *, strength: float, seed: int) -> np.ndarray:
    """對相關性最高的若干變數獨立打亂時間順序，破壞相關結構但**完全保留各變數邊際**。

    strength∈(0,1]：打亂的變數比例（依 golden 相關強度排序取前 round(strength·p) 個）。
    不變式：每欄值為原值之重排 → 邊際分佈逐位元不變（單變數 SPC 必盲）；相關被破壞 → 多變量 SPE 升。
    """
    rng = np.random.default_rng(seed)
    Xd = X.copy()
    n, p = X.shape
    corr = np.abs(np.corrcoef(golden.T)).sum(axis=0)
    order = np.argsort(corr)[::-1]
    k = max(1, int(round(strength * p)))
    for c in order[:k]:
        Xd[:, c] = X[rng.permutation(n), c]
    return Xd


def generate(
    *,
    n_per_campaign: int = 300,
    drift_strength: float = 0.7,
    y_every: int = 20,
    seed: int = 0,
    data_dir: str = DEFAULT_DIR,
) -> tuple[ProcessDataset, TEPGroundTruth]:
    """組 TEP 隱性飄移情境 → (ProcessDataset, TEPGroundTruth)，契約同 ``synthetic.generate``。

    Args:
        n_per_campaign: 每 campaign 取樣數（各模態檔截前段、對齊長度）。
        drift_strength: 注入關係飄移強度（打亂變數比例 0–1；越大越易被多變量偵測）。
        y_every: 每隔幾步保留一個 Y 量測（其餘 NaN，模擬稀疏實驗室抽樣）。
        seed: 注入 RNG 種子（決定論）。
        data_dir: TEP .mat 目錄。

    Raises:
        FileNotFoundError: 缺所需 .mat（附下載指引）。

    Invariant: 同參數 → 逐位元相同輸出；drift 段邊際與 golden 同（單變數盲），相關被注入破壞。
    """
    x_columns = tuple(f"xmeas{i + 1:02d}" for i in XMEAS_COLS)
    rng = np.random.default_rng(seed)
    pools = {f: _load_mat(f, data_dir)[_STATIONARY] for f in {p[0] for p in _PLAN}}
    golden_x = pools["m1d00"][:, XMEAS_COLS]  # 注入相關排序用

    blocks_x: list[np.ndarray] = []
    blocks_y: list[np.ndarray] = []
    grades: list[str] = []
    bounds: list[tuple[int, int, str]] = []
    golden_flags: list[np.ndarray] = []
    drift_flags: list[np.ndarray] = []

    cursor = 0
    for fname, grade, tag in _PLAN:
        pool = pools[fname]
        npc = n_per_campaign * 2 if tag == "golden" else n_per_campaign  # golden 大窗→穩定基準
        seg = pool[rng.choice(len(pool), size=npc, replace=True)]        # iid 重抽（同分佈）
        X = seg[:, XMEAS_COLS]
        y = 0.5 * (seg[:, G_COL] + seg[:, H_COL])  # 品質代理：G/H 平均（單一 Y 示範；可擴 2 維）
        if tag == "drift":  # 打亂 X 部分欄→破壞相關(X 健康)且斷 X→Y 配對(Y 健康)；保各欄邊際(單變數盲)
            X = _inject_relationship_drift(X, golden_x, strength=drift_strength, seed=seed)
        blocks_x.append(X)
        blocks_y.append(y)
        grades.extend([grade] * len(X))
        bounds.append((cursor, cursor + len(X), grade))
        golden_flags.append(np.full(len(X), tag == "golden"))
        drift_flags.append(np.full(len(X), tag == "drift"))
        cursor += len(X)

    X_all = np.vstack(blocks_x)
    y_full = np.concatenate(blocks_y)
    n = X_all.shape[0]

    y_value = np.full(n, np.nan)
    sample_idx = np.arange(0, n, y_every)
    y_value[sample_idx] = y_full[sample_idx]

    ts = pd.date_range("2026-01-01", periods=n, freq="min")
    y_ts = pd.Series(pd.NaT, index=range(n), dtype="datetime64[ns]")
    y_ts.iloc[sample_idx] = ts[sample_idx]

    frame = pd.DataFrame({TIMESTAMP: ts, GRADE_LABEL: grades})
    for j, col in enumerate(x_columns):
        frame[col] = X_all[:, j]
    frame[Y_VALUE] = y_value
    frame[Y_TIMESTAMP] = y_ts.to_numpy()

    gt = TEPGroundTruth(
        campaign_bounds=tuple(bounds),
        golden_mask=np.concatenate(golden_flags),
        drift_mask=np.concatenate(drift_flags),
        x_columns=x_columns,
    )
    return ProcessDataset(frame=frame, x_columns=x_columns, name="tep"), gt
