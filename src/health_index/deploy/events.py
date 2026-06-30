"""P1/P2 告警事件閉環：偵測 → 認領(ack) → 關閉(處置) 的事件日誌 + MTTR/統計。

供**現場工程師**（告警清單 / ACK / 處置留痕）與**生產處長**（事件閉環 / MTTR / 稽核軌跡）。
檔案持久化（JSON），確定性、無 LLM（Rule 5）。事件時間 runtime 取真實時間；測試可注入 ``now`` 確定性驗證。

防重複卡榫（類比昂貴 API 防重）：同一 product 同時最多一個 **open/ack** 事件——偵測器持續告警時
``open_incident`` 回既有未結事件、不重複開案，直到關閉才會再開新案（一次告警事件＝一段 episode）。
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime

OPEN, ACK, CLOSED = "open", "ack", "closed"
_ACTIVE = (OPEN, ACK)


@dataclass
class Incident:
    """單一告警事件（偵測→處置 的生命週期）。"""

    id: str
    product: str
    detected_at: str          # 資料時間：最嚴重窗的資料時間戳（可能 naive，如真實 PIMS/歷史資料）
    window: list              # [start, end] 樣本索引
    health: float
    confidence: float
    top_cause: str            # RBC 首位肇因變數
    severity: str             # info / warning / critical
    kind: str = "process"     # 增量8：process（X 側製程異常）/ quality（Y 側品質飄移）——分流防重複、分開閉環
    status: str = OPEN
    opened_at: str | None = None  # 真實牆鐘：本案在系統開立的時刻（與 detected_at 的資料時間分離，MTTR 用此）
    ack_by: str | None = None
    ack_at: str | None = None
    closed_at: str | None = None
    close_note: str | None = None
    close_reason: str | None = None  # real（真實處置）/ false_alarm（誤報）/ ignore（已知狀況忽略）
    mttr_sec: float | None = None  # 關閉時 = closed_at − opened_at（真實處置歷時，秒）


def severity_of(health: float, confidence: float) -> str:
    """由健康度 + 可信度定嚴重度（確定性規則）：低健康+高可信＝critical；低可信＝warning（存疑）。"""
    if confidence < 0.6:
        return "warning"        # 存疑（外推）→ 不升到 critical，避免假警拉高層級
    if health < 0.45:
        return "critical"
    if health < 0.6:
        return "warning"
    return "info"


def _iso(now: str | None) -> str:
    return now if now is not None else datetime.now().astimezone().isoformat(timespec="seconds")


def _parse_aware(s: str) -> datetime:
    """解析 ISO 時間；**naive 視為本機時區**轉為 aware → 避免 aware−naive 相減 TypeError（紅隊 blocker）。

    真實資料集（CCPP/TEP/Steel、未來 PIMS）的資料時間戳常為 naive，而 closed_at 走 ``_iso`` 為 aware；
    兩者直接相減會炸並被前端 except 靜默吞掉，使事件永遠關不掉。此處統一轉 aware 再相減。
    """
    dt = datetime.fromisoformat(s)
    return dt if dt.tzinfo is not None else dt.astimezone()


class IncidentStore:
    """JSON 檔事件庫（append/更新）；重啟安全、可稽核。"""

    def __init__(self, path: str):
        self.path = path

    def _load(self) -> list[dict]:
        try:
            with open(self.path, encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return []

    def _save(self, items: list[dict]) -> None:
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=2)

    def _next_id(self, items: list[dict]) -> str:
        nums = [int(it["id"].split("-")[-1]) for it in items if str(it.get("id", "")).startswith("INC-")]
        return f"INC-{(max(nums) + 1) if nums else 1:04d}"

    def open_incident(
        self, *, product: str, window, health: float, confidence: float, top_cause: str,
        detected_at: str | None = None, opened_at: str | None = None, severity: str | None = None,
        kind: str = "process",
    ) -> Incident:
        """開案；同 (product, kind) 已有 active(open/ack) 事件則回該事件（防重複，不開新案）。

        detected_at＝資料時間（最嚴重窗時間戳）；opened_at＝真實開立牆鐘（None→當下），MTTR 用後者算處置歷時。
        kind 分流（增量8）：製程異常(process)與品質飄移(quality)各自一條 episode，不互相壓制——同一製程
        可同時有一個製程事件與一個品質事件。
        """
        items = self._load()
        for it in items:
            if it["product"] == product and it.get("kind", "process") == kind and it["status"] in _ACTIVE:
                return Incident(**{**{"kind": "process"}, **it})  # 既有未結 episode，沿用（舊檔無 kind→process）
        inc = Incident(
            id=self._next_id(items), product=str(product), detected_at=_iso(detected_at),
            window=[int(window[0]), int(window[1])], health=round(float(health), 4),
            confidence=round(float(confidence), 4), top_cause=str(top_cause),
            severity=severity or severity_of(health, confidence), kind=str(kind), opened_at=_iso(opened_at),
        )
        items.append(asdict(inc))
        self._save(items)
        return inc

    def _update(self, incident_id: str, **changes) -> Incident:
        items = self._load()
        for it in items:
            if it["id"] == incident_id:
                it.update(changes)
                self._save(items)
                return Incident(**it)
        raise KeyError(f"找不到事件 {incident_id}")

    def ack(self, incident_id: str, *, by: str, at: str | None = None) -> Incident:
        """現場工程師認領（接手處理中）。"""
        return self._update(incident_id, status=ACK, ack_by=str(by), ack_at=_iso(at))

    def close(self, incident_id: str, *, note: str, by: str, at: str | None = None, reason: str = "real") -> Incident:
        """關閉並留處置記錄；MTTR＝closed_at − opened_at（真實處置歷時）。reason∈{real,false_alarm,ignore}（誤報不計 MTTR/ROI）。

        以 ``_parse_aware`` 統一 naive/aware 再相減（修紅隊 blocker：真實資料 naive ts vs aware now 相減 TypeError）；
        opened_at 缺（舊檔）則退回 detected_at。
        """
        items = self._load()
        rec = next((it for it in items if it["id"] == incident_id), None)
        if rec is None:
            raise KeyError(f"找不到事件 {incident_id}")
        closed_at = _iso(at)
        base = rec.get("opened_at") or rec["detected_at"]  # 真實開立時刻；舊檔退回資料時間
        mttr = (_parse_aware(closed_at) - _parse_aware(base)).total_seconds()
        return self._update(incident_id, status=CLOSED, closed_at=closed_at, close_note=str(note),
                            close_reason=str(reason), ack_by=rec.get("ack_by") or str(by), mttr_sec=round(float(mttr), 1))

    def list(self, *, status: str | None = None, product: str | None = None) -> list[dict]:
        """列出事件（可依 status/product 過濾），偵測時間新→舊。"""
        items = self._load()
        if status:
            items = [it for it in items if it["status"] == status]
        if product:
            items = [it for it in items if it["product"] == product]
        return sorted(items, key=lambda it: it["detected_at"], reverse=True)

    def stats(self) -> dict:
        """處長 KPI：各狀態計數 + 平均 MTTR（秒/小時，僅 closed）。"""
        items = self._load()
        closed = [it for it in items if it["status"] == CLOSED and it.get("mttr_sec") is not None]
        # MTTR 只計真實處置（誤報是「快速駁回」，計入會低估真實修復時間 → 排除，紅隊現場工程師）
        mttrs = [it["mttr_sec"] for it in closed if it.get("close_reason") != "false_alarm"]
        mean_mttr = (sum(mttrs) / len(mttrs)) if mttrs else None
        return {
            "total": len(items),
            "open": sum(1 for it in items if it["status"] == OPEN),
            "ack": sum(1 for it in items if it["status"] == ACK),
            "closed": len(closed),
            "false_alarm": sum(1 for it in items if it.get("close_reason") == "false_alarm"),
            "active": sum(1 for it in items if it["status"] in _ACTIVE),
            "mean_mttr_sec": None if mean_mttr is None else round(mean_mttr, 1),
            "mean_mttr_hr": None if mean_mttr is None else round(mean_mttr / 3600.0, 2),
        }
