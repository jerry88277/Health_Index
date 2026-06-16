"""G2 線上評分 runner：``poll_once()`` 純函式 + 狀態持久化 + persistence_k 接線。

D2 決策（docs/deployment_plan.md §4）：純函式 + 外部排程器驅動（確定性可測；Windows 排程器/cron/服務皆可），
非常駐 daemon。狀態（游標、連續告警數）持久化 JSON → 重啟安全（resume-safe）。

線上語義：每次 poll 處理自上次游標以來「已到齊」的新完整窗（非重疊滑窗），更新連續告警計數；
連續 ``persistence_k`` 窗告警才升為 persisted_alarm（濾單窗毛刺，config.drift_persistence_k 接線）。
告警判決收口於 ``HealthIndex.alarm()``（is_alarm ∨ fwer_alarm 聯集；粗融合漏的由 AC-6 校準偵測器補）。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

import numpy as np

from .bundle import ModelBundle
from .sources import DataSource


@dataclass
class RunnerState:
    """跨 poll 持久化的最小狀態（重啟安全）。"""

    cursor: int = 0  # 下一個尚未處理的列索引
    consecutive_alarm: int = 0  # 連續告警窗數（persistence 用）

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @staticmethod
    def from_json(s: str) -> "RunnerState":
        d = json.loads(s)
        return RunnerState(cursor=int(d.get("cursor", 0)), consecutive_alarm=int(d.get("consecutive_alarm", 0)))


@dataclass
class WindowScore:
    """單一評分窗的結果（時間線一格）。"""

    start: int
    end: int
    health_index: float
    subscores: dict[str, float]
    hard_gates: dict[str, bool]
    raw_alarm: bool  # 單窗 HealthIndex.alarm()：is_alarm ∨ fwer_alarm
    persisted_alarm: bool  # 連續 persistence_k 窗皆 raw_alarm
    consecutive: int  # 截至本窗的連續告警數
    fwer: dict[str, float] | None = None  # 各層 p-value（compute_fwer 時）


def poll_once(
    bundle: ModelBundle,
    source: DataSource,
    state: RunnerState,
    *,
    window: int | None = None,
    step: int | None = None,
    persistence_k: int | None = None,
    compute_fwer: bool = True,
) -> tuple[list[WindowScore], RunnerState]:
    """處理自 ``state.cursor`` 起所有已到齊的完整窗，回傳 (新窗結果, 新狀態)。

    Args:
        bundle: 已載入並驗證的模型 bundle。
        source: 資料源（只需 DataSource 協定）。
        window: 評分窗長（None→config.drift_window）。
        step: 窗推進步長（None→window，即非重疊）。
        persistence_k: 連續幾窗告警才 persisted（None→config.drift_persistence_k）。
        compute_fwer: 是否算 AC-6 FWER（較貴；False 則只用 is_alarm 快路徑）。

    Returns:
        (該次新增的 WindowScore 串, 更新後 RunnerState)。冪等於游標：重入只處理新窗。
    """
    cfg = bundle.config
    w = int(window or cfg.drift_window)
    st = int(step or w)
    pk = int(persistence_k if persistence_k is not None else cfg.drift_persistence_k)
    hi = bundle.health
    n = len(source)
    cur = state.cursor
    cons = state.consecutive_alarm
    out: list[WindowScore] = []
    while cur + w <= n:
        X = source.x_slice(cur, cur + w)
        # 單次掃描評分（hi.score）：一次算齊 subscores/health/hard_gates/alarm(+fwer)，避免逐窗 3–4× 重算
        # 昂貴 L4（高維資料集逐窗評分的主瓶頸；alarm 收口於 hi.score 內，等價 is_alarm ∨ fwer_alarm）。
        r = hi.score(X, compute_fwer=compute_fwer)
        raw = bool(r["alarm"])
        cons = cons + 1 if raw else 0
        out.append(
            WindowScore(
                start=cur,
                end=cur + w,
                health_index=r["health_index"],
                subscores=r["subscores"],
                hard_gates=r["hard_gates"],
                raw_alarm=raw,
                persisted_alarm=cons >= pk,
                consecutive=cons,
                fwer=r["pvalues"],
            )
        )
        cur += st
    return out, RunnerState(cursor=cur, consecutive_alarm=cons)


def run_replay(
    bundle: ModelBundle,
    source: DataSource,
    *,
    window: int | None = None,
    step: int | None = None,
    persistence_k: int | None = None,
    compute_fwer: bool = True,
) -> list[WindowScore]:
    """便利：從頭重放整個 source 為一條健康指標時間線（demo「查看健康指標」用）。"""
    scores, _ = poll_once(
        bundle, source, RunnerState(),
        window=window, step=step, persistence_k=persistence_k, compute_fwer=compute_fwer,
    )
    return scores


def save_state(state: RunnerState, path: str) -> str:
    """狀態存檔（重啟安全）。"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(state.to_json())
    return path


def load_state(path: str) -> RunnerState:
    """狀態載入；檔不存在回初始狀態（首次啟動）。"""
    try:
        with open(path, encoding="utf-8") as f:
            return RunnerState.from_json(f.read())
    except FileNotFoundError:
        return RunnerState()
