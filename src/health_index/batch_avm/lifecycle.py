"""批次生命週期 runtime：4h CSTR 批的相位狀態機（10min 起監 X → Ŷ_middle → Ŷ_final → 出 Y 查 G1）。

時序（使用者 2026-07-02 定）：
- ``x_monitor``（t≈10min）：開始監控製程參數 X（T²/SPE 域內否），**不發信**（僅狀態）。
- ``yhat_middle``（t≈2h，產品半成形）：由當下 X* 算 Ŷ_middle；越出適用域（正式 G3 AD）→ 通知。
- ``yhat_final``（t=4h，批結束）：算 Ŷ_final；越域→通知。
- ``y_measured``（真實 Y 出爐後，事件驅動非時間驅動）：Y vs 歷史（G1）→ 觸發則歸因 X（G2）→ 通知。

**誠實標記（Rule 12）**：``x_monitor``/``yhat_middle`` 的 X* 來自**部分批**資料，與 golden 的
**全批** X* 在分佈上**不可交換** → T²/SPE 與 AD 門檻對其**並未嚴格校準**，故標 ``partial_basis=True``
且 detail 帶 caveat；此為早期預警，不得當已校準告警讀。要嚴格校準需另以「部分批 X*」建對應相位模型
（Rule 2：目前不做，明標侷限）。

防重複（成本卡榫）：同批 G3 **只通知一次**（``g3_notified``）——後續相位仍誠實回報越域狀態但不重送；
相位冪等（已完成者重入為 no-op），狀態可 JSON 存載 → resume-safe。G1×G3 同批＝**兩封獨立信**
（#8 鎖定決策）：G3 於 middle/final 發、G1 於 y_measured 發，總計兩封且互知（``co_g3``），不合併不重送。
隔離（Rule 3）：只依 batch_avm 內部 + notify（純組裝），不 import 主 HealthIndex/deploy 告警路徑。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

import numpy as np

from ..config import DEFAULT, Config
from ..notify import compose_notifications
from .attribution import y_event_attribution
from .mapping import score_batches

PHASES = ("x_monitor", "yhat_middle", "yhat_final", "y_measured")
_PARTIAL_CAVEAT = ("此相位 X* 由部分批資料算得，與 golden 全批 X* 不可交換；T²/SPE 與 AD 門檻"
                   "未對其嚴格校準，屬早期預警，勿當已校準告警讀（Rule 12）。")


@dataclass(frozen=True)
class BatchSchedule:
    """批相位時刻表（預設 4h CSTR）。"""

    total_hours: float = 4.0
    x_monitor_hours: float = 1.0 / 6.0   # ≈10 分鐘
    middle_frac: float = 0.5             # 半程 ≈2h


DEFAULT_SCHEDULE = BatchSchedule()


@dataclass
class LifecycleState:
    """單批跨相位持久化狀態（resume-safe；冪等與防重送依據）。"""

    batch_index: int = 0
    completed: tuple = ()          # 已完成相位
    g3_notified: bool = False      # 本批 G3 是否已發過信（防重送）
    g3_top: str | None = None
    g3_reason: str | None = None

    def to_json(self) -> str:
        d = asdict(self)
        d["completed"] = list(self.completed)
        return json.dumps(d)

    @staticmethod
    def from_json(s: str) -> "LifecycleState":
        d = json.loads(s)
        return LifecycleState(batch_index=int(d.get("batch_index", 0)),
                              completed=tuple(d.get("completed", [])),
                              g3_notified=bool(d.get("g3_notified", False)),
                              g3_top=d.get("g3_top"), g3_reason=d.get("g3_reason"))


@dataclass
class PhaseEvent:
    """單一相位的判讀結果 + 該相位要發的通知。"""

    phase: str
    t_hours: float
    yhat: float | None
    g3_alarm: bool
    g1_alarm: bool
    partial_basis: bool            # X* 來自部分批（門檻未嚴格校準）→ 誠實標
    notifications: list = field(default_factory=list)
    detail: dict = field(default_factory=dict)


def due_phases(t_hours: float, *, schedule: BatchSchedule = DEFAULT_SCHEDULE,
               completed: tuple = ()) -> list[str]:
    """回傳此刻**時間已到且尚未完成**的相位（依序）。``y_measured`` 為事件驅動，不在此列。"""
    order = [("x_monitor", schedule.x_monitor_hours),
             ("yhat_middle", schedule.total_hours * schedule.middle_frac),
             ("yhat_final", schedule.total_hours)]
    return [p for p, t in order if t_hours >= t and p not in completed]


def _score_one(model, xstar_row) -> dict:
    """對單批 X* 評分（沿用已測 score_batches：Ŷ/帶/T²/SPE/正式 G3 AD）。"""
    row = np.asarray(xstar_row, dtype=float).reshape(1, -1)
    return score_batches(model, row)["batches"][0]


def run_phase(model, state: LifecycleState, *, phase: str, t_hours: float,
              xstar_row=None, y_online=None, y_monitor=None,
              schedule: BatchSchedule = DEFAULT_SCHEDULE,
              config: Config = DEFAULT) -> tuple[PhaseEvent, LifecycleState]:
    """執行單一相位，回傳 (事件, 新狀態)。冪等：已完成相位重入為 no-op（不重發通知）。

    Args:
        phase: ``x_monitor`` / ``yhat_middle`` / ``yhat_final`` / ``y_measured``。
        xstar_row: 該相位可得的 X*（部分或全批）；Ŷ 相位與 G2 歸因需要。
        y_online: ``y_measured`` 相位用——**累計**已量測 Y 序列（含本批），供 G1 比歷史。
        y_monitor: 已 fit 的 ``YHistoryMonitor``（G1）；缺則不判 G1（誠實不假評）。

    Raises:
        ValueError: 未知相位，或 Ŷ 相位缺 ``xstar_row``。
    """
    if phase not in PHASES:
        raise ValueError(f"未知相位 {phase}（可用：{PHASES}）")
    if phase in state.completed:  # 冪等：不重跑、不重發
        return PhaseEvent(phase=phase, t_hours=t_hours, yhat=None, g3_alarm=False, g1_alarm=False,
                          partial_basis=phase in ("x_monitor", "yhat_middle"),
                          notifications=[], detail={"skipped": True, "note": "相位已完成（冪等）"}), state

    partial = phase in ("x_monitor", "yhat_middle")
    notes: list = []
    detail: dict = {}
    yhat = None
    g3 = False
    g1 = False
    st = LifecycleState(batch_index=state.batch_index, completed=tuple(state.completed) + (phase,),
                        g3_notified=state.g3_notified, g3_top=state.g3_top, g3_reason=state.g3_reason)

    if phase in ("x_monitor", "yhat_middle", "yhat_final"):
        if xstar_row is None:
            raise ValueError(f"相位 {phase} 需要 xstar_row")
        b = _score_one(model, xstar_row)
        yhat = b["yhat"]
        detail = {"t2": b["t2"], "spe": b["spe"], "gsi": b["gsi"], "anomaly": b["anomaly"],
                  "yhat_reliable": b["yhat_reliable"], "leverage": b.get("leverage"),
                  "g3_reason": b.get("g3_ad_reason"), "rbc_top": b.get("rbc_top")}
        if partial:
            detail["caveat"] = _PARTIAL_CAVEAT
        if phase == "x_monitor":
            detail["x_domain_ok"] = not bool(b["anomaly"])  # 僅監看 X 域，依規格不發信
        else:
            g3 = bool(b.get("g3_ad_alarm"))
            if g3 and not st.g3_notified:  # 同批只發一次（防重複告警/重複扣費）
                notes = compose_notifications(batch_index=st.batch_index,
                                              g3={"alarm": True, "top_param": b.get("g3_ad_top"),
                                                  "reason": b.get("g3_ad_reason")})
                st.g3_notified = True
                st.g3_top, st.g3_reason = b.get("g3_ad_top"), b.get("g3_ad_reason")
            elif g3:
                detail["g3_already_notified"] = True  # 誠實回報仍越域，但不重送

    else:  # y_measured：真實 Y 出爐才判 G1（結構上不可提前）
        if y_monitor is None or y_online is None:
            detail = {"g1_unavailable": "缺 y_monitor 或 y_online，G1 不評（誠實不假評）"}
        else:
            res = y_monitor.score(np.asarray(y_online, dtype=float))
            s = res["summary"]
            g1 = bool(s["alarm"])
            detail = {"g1_summary": s}
            g2_payload = None
            if g1 and xstar_row is not None:
                attr = y_event_attribution(model, np.asarray(xstar_row, dtype=float))
                g2_payload = {"top_param": attr["top_param"], "reliable": attr["reliable"]}
                detail["g2"] = g2_payload
            # 同批先前已發 G3 → 只交叉引用、不重送（總計仍是兩封獨立信，#8）
            detail["co_g3"] = bool(st.g3_notified)
            g3_payload = None
            if xstar_row is not None and not st.g3_notified:
                b = _score_one(model, xstar_row)
                if b.get("g3_ad_alarm"):  # 尚未通知過的 G3 → 此刻與 G1 同點共發＝兩封
                    g3 = True
                    g3_payload = {"alarm": True, "top_param": b.get("g3_ad_top"),
                                  "reason": b.get("g3_ad_reason")}
                    st.g3_notified = True
            notes = compose_notifications(batch_index=st.batch_index,
                                          g1={"drifted": g1}, g2=g2_payload, g3=g3_payload)

    return PhaseEvent(phase=phase, t_hours=t_hours, yhat=yhat, g3_alarm=g3, g1_alarm=g1,
                      partial_basis=partial, notifications=notes, detail=detail), st
