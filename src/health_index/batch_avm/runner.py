"""batch-AVM headless runner：``poll_batches()`` 純函式 + cursor 狀態持久化（重啟安全）。

比照 ``deploy/runner.py`` 的 D2 決策（純函式 + 外部排程器驅動，非常駐 daemon；Windows 排程器/
cron 皆可，確定性可測）：每次 poll 增量處理「自上次 cursor 起、已到齊」的新批，**冪等於 cursor**
（重入不重處理已發批——避免重複告警、未來重複觸發 SMTP 扣費）。狀態持久化 JSON → resume-safe。

範圍（Rule 2/3）：本 runner 到 **X*→Ŷ + 正式 G3 適用域（AD）** 為止；Y 側 G1/G2（殘差、Y-vs-歷史）
與批內 4h 生命週期（10min 起監 X→Ŷ_middle→Ŷ_final→出 Y 查 G1）屬 backlog #9。隔離（Rule 3）：
本模組只依 ``batch_avm.mapping``，**不 import** 主 HealthIndex / deploy / 告警路徑（advisory）。
確定性（Rule 5）：無 RNG，score_batches 為確定性數學。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass

import numpy as np

from ..config import DEFAULT, Config
from .mapping import score_batches


@dataclass
class BatchRunnerState:
    """跨 poll 持久化的最小狀態（重啟安全）。"""

    cursor: int = 0      # 下一個尚未處理的 batch 索引
    n_alarms: int = 0    # 累計告警批數（監控用；域外 anomaly 或 G3 AD 觸發）

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @staticmethod
    def from_json(s: str) -> "BatchRunnerState":
        d = json.loads(s)
        return BatchRunnerState(cursor=int(d.get("cursor", 0)), n_alarms=int(d.get("n_alarms", 0)))


@dataclass
class BatchRunResult:
    """單一批的評分結果（batch-AVM 一格）。全域 ``index`` 供排程器對齊時間軸。"""

    index: int
    yhat: float
    band_lo: float | None
    band_hi: float | None
    t2: float
    spe: float
    gsi: float
    anomaly: bool             # T²/SPE 域外（X* 離建模域）
    yhat_reliable: bool
    g3_ad_alarm: bool | None  # 正式 G3 適用域告警（leverage 超限 或 Ŷ 出宣告範圍）
    g3_ad_top: str | None     # G3 肇因參數
    rbc_top: str | None       # 域外時 SPE-RBC 首要肇因參數


def poll_batches(model, Xstar_all, state: BatchRunnerState, *,
                 config: Config = DEFAULT) -> tuple[list[BatchRunResult], BatchRunnerState]:
    """處理自 ``state.cursor`` 起所有已到齊的新批，回傳 (新批結果, 新狀態)。

    Args:
        model: 已 fit 的 ``BatchAvmModel``。
        Xstar_all: 迄今**全部**已到齊批的 X*（[n_batch × p]）；cursor 之前的視為已處理。
        state: 上次持久化狀態。

    Returns:
        (該次新增的 BatchRunResult 串, 更新後 BatchRunnerState)。冪等於 cursor：重入只處理新批。
    """
    Xall = np.asarray(Xstar_all, dtype=float)
    n = len(Xall)
    cur = int(state.cursor)
    if cur >= n:  # 無新批 → 空結果、cursor/計數不動
        return [], BatchRunnerState(cursor=cur, n_alarms=state.n_alarms)
    scored = score_batches(model, Xall[cur:])
    out: list[BatchRunResult] = []
    n_alarm = int(state.n_alarms)
    for i, b in enumerate(scored["batches"]):
        alarmed = bool(b["anomaly"]) or bool(b.get("g3_ad_alarm"))
        if alarmed:
            n_alarm += 1
        out.append(BatchRunResult(
            index=cur + i, yhat=b["yhat"], band_lo=b["band_lo"], band_hi=b["band_hi"],
            t2=b["t2"], spe=b["spe"], gsi=b["gsi"], anomaly=bool(b["anomaly"]),
            yhat_reliable=bool(b["yhat_reliable"]), g3_ad_alarm=b.get("g3_ad_alarm"),
            g3_ad_top=b.get("g3_ad_top"), rbc_top=b.get("rbc_top"),
        ))
    return out, BatchRunnerState(cursor=n, n_alarms=n_alarm)


def run_all(model, Xstar_all, *, config: Config = DEFAULT) -> list[BatchRunResult]:
    """便利：從頭一次評分全部批（離線／demo 用）。"""
    res, _ = poll_batches(model, Xstar_all, BatchRunnerState(), config=config)
    return res


def save_state(state: BatchRunnerState, path: str) -> str:
    """狀態存檔（重啟安全）。"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(state.to_json())
    return path


def load_state(path: str) -> BatchRunnerState:
    """狀態載入；檔不存在回初始狀態（首次啟動）。"""
    try:
        with open(path, encoding="utf-8") as f:
            return BatchRunnerState.from_json(f.read())
    except FileNotFoundError:
        return BatchRunnerState()
