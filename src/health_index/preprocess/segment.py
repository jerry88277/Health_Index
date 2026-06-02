"""連續製程分段（M1 preprocess）。

把連續流切成 campaign 與穩態 pseudo-run，並標記 transition（換線 settling）以**排除於
golden-A baseline**——紅隊 H1：偵測基準必須凍結且乾淨；若 golden 混入 transition 或
re-entry/drift 段，整個偵測基準被毒化，後續所有層失效。

- ``add_campaign_ids``：由 grade_label 連續段導出 campaign_id（標籤可靠）。
- ``detect_change_points``：ruptures PELT(rbf) 的 label-agnostic 變點偵測，供真實無標籤
  資料與驗證使用（紅隊 D8：ruptures 給邊界，穩態判定仍需準則 → 本檔以 transition_width 補）。
- ``segment``：填入衍生欄 campaign_id/mode/run_id/is_golden_a。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import ruptures as rpt

from ..config import DEFAULT, Config
from ..interface import (
    CAMPAIGN_ID,
    GRADE_LABEL,
    IS_GOLDEN_A,
    MODE,
    RUN_ID,
    Mode,
    ProcessDataset,
)


def add_campaign_ids(grade: pd.Series) -> np.ndarray:
    """由 grade_label 連續段給 campaign_id（每次切換產品 +1，從 0 起）。"""
    g = grade.to_numpy()
    change = np.empty(len(g), dtype=bool)
    change[0] = True
    change[1:] = g[1:] != g[:-1]
    return np.cumsum(change) - 1


def detect_change_points(
    X: np.ndarray,
    *,
    penalty: float | None = None,
    n_bkps: int | None = None,
    config: Config = DEFAULT,
) -> list[int]:
    """偵測多變量分佈變點（label-agnostic）。

    Args:
        X: (n, p) 製程參數。
        penalty: PELT 懲罰；None 時取 ``config.ssd_penalty``（單一 config 治理，紅隊 D1）。
        n_bkps: 給定則改用 Dynp 精確求 n 個變點（驗證/測試用，決定性較高）。
        config: 提供 ssd_penalty 與 cpd_min_size。

    Returns:
        變點索引（不含結尾 n），遞增。

    Note: rbf kernel 對均值與相關結構變化皆敏感（捕捉關係型漂移）；min_size 來自 config，非硬編。
    """
    xs = (X - X.mean(0)) / (X.std(0) + 1e-9)
    min_size = max(2, config.cpd_min_size)
    if n_bkps is not None:
        bkps = rpt.Dynp(model="rbf", min_size=min_size).fit(xs).predict(n_bkps=n_bkps)
    else:
        pen = config.ssd_penalty if penalty is None else penalty
        bkps = rpt.Pelt(model="rbf", min_size=min_size).fit(xs).predict(pen=pen)
    return [int(b) for b in bkps if b < len(X)]


def segment(
    dataset: ProcessDataset,
    *,
    config: Config = DEFAULT,
    golden_grade: str = "A",
) -> pd.DataFrame:
    """加入衍生欄 campaign_id/mode/run_id/is_golden_a，回傳**新** frame（不改原 frame）。

    規則：
        - mode：每個 campaign 起始後 ``config.transition_width`` 個樣本為 transition（settling），其餘 steady。
        - run_id：穩態段＝campaign_id；transition＝-1（非 pseudo-run）。
        - is_golden_a：**僅** 第一個 golden_grade campaign 的穩態段。

    Invariant: is_golden_a 絕不含任何 re-entry/drift campaign，亦不含 transition settling。

    Note: ``y_delay`` 與逐時刻 lagged 樣本（雙軌的動態軌）由 M1 後續單元（X→Y 對齊／DPCA）
    填入，非本分段單元職責（Rule 2）。
    """
    fr = dataset.frame.copy()
    n = len(fr)
    cid = add_campaign_ids(fr[GRADE_LABEL])
    fr[CAMPAIGN_ID] = cid

    mode = np.full(n, Mode.STEADY.value, dtype=object)
    starts = np.flatnonzero(np.concatenate(([True], cid[1:] != cid[:-1])))
    ends = np.append(starts[1:], n)  # 每個 campaign 的 exclusive 結尾
    w = config.transition_width
    for s, e in zip(starts, ends):
        mode[s : min(s + w, e)] = Mode.TRANSITION.value  # settling 夾到 campaign 邊界、不溢出
    fr[MODE] = mode

    steady = mode == Mode.STEADY.value
    fr[RUN_ID] = np.where(steady, cid, -1)

    is_grade = fr[GRADE_LABEL].to_numpy() == golden_grade
    golden_cids = np.unique(cid[is_grade])
    first_golden = int(golden_cids.min()) if golden_cids.size else -1
    fr[IS_GOLDEN_A] = (cid == first_golden) & steady
    return fr
