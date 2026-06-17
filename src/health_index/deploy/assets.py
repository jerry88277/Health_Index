"""增量7 模型 registry：製程(monitored asset) / 模型(fitted bundle 版本) / 資料集(replay 來源)解耦。

設計與不變式見 ``docs/model_registry_design.md``（已經 3 個獨立子代理紅隊複審）。核心：
- 製程可累積多模型版本（重建基準），其一為現役（``current_model_id``）。
- **模型「現役」為衍生**：model 現役 iff ``id == 其 process.current_model_id``；不存 active/superseded 欄位。
- version 用單調計數器 ``next_version``（永不回收）→ 刪最高版再建不碰撞。
- 軟刪除只翻 ``deleted`` 旗標、**絕不刪 .joblib**（歷史頁要重放）。
- 軟刪製程強制關閉其 active incidents（解孤兒事件）。
- 持久化 temp + ``os.replace``（原子）。

確定性、無 LLM（Rule 5）。命名刻意避開 ``ModelRegistry``（lifecycle.py）/ ``registry``（adapters.registry）。
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime

from ..adapters import registry as _ds_registry

_SCHEMA_VERSION = 1
_ANON = "未具名"


def _iso(at: str | None) -> str:
    """ISO-8601 帶 offset（與 events.py 對齊）；at 為 None 時取當下真實時間。"""
    return at if at is not None else datetime.now().astimezone().isoformat(timespec="seconds")


def _slug(name: str, fallback: str) -> str:
    """display_name → ascii-safe slug；落空（如純中文）退回 fallback（dataset 名）。不入中文於路徑（紅隊 RT-1#9）。"""
    s = re.sub(r"[^a-z0-9]+", "-", str(name).lower()).strip("-")
    return s if len(s) >= 2 else fallback


class AssetStore:
    """JSON 檔製程/模型/稽核 registry；原子寫入、可重啟、可稽核（log存取）。"""

    def __init__(self, path: str):
        self.path = path

    # ---------- 持久化（原子）----------
    def _load(self) -> dict:
        try:
            with open(self.path, encoding="utf-8") as f:
                d = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {"schema_version": _SCHEMA_VERSION, "processes": [], "models": [], "audit": []}
        d.setdefault("schema_version", _SCHEMA_VERSION)
        for k in ("processes", "models", "audit"):
            d.setdefault(k, [])
        return d

    def _save(self, d: dict) -> None:
        """寫 temp + os.replace（同卷原子）→ 寫一半不會損毀整個 registry（紅隊 RT-1#5）。"""
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        tmp = f"{self.path}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)

    @staticmethod
    def _proc(d: dict, pid: str) -> dict:
        for p in d["processes"]:
            if p["id"] == pid:
                return p
        raise KeyError(f"找不到製程 '{pid}'")

    @staticmethod
    def _audit(d: dict, *, actor, action, process_id, model_id=None, detail="", at=None) -> None:
        d["audit"].append({"at": _iso(at), "actor": str(actor or _ANON), "action": action,
                           "process_id": process_id, "model_id": model_id, "detail": detail})

    def _recompute_current(self, d: dict, pid: str) -> None:
        """current_model_id 指向同製程**最高版未刪** model，無則 None（不變式：永不指向已刪）。"""
        p = self._proc(d, pid)
        live = [m for m in d["models"] if m["process_id"] == pid and not m["deleted"]]
        p["current_model_id"] = max(live, key=lambda m: m["version"])["id"] if live else None

    # ---------- 製程 ----------
    def create_process(self, *, display_name: str, dataset: str, by: str = _ANON,
                       at: str | None = None, area: str | None = None) -> dict:
        """建立製程 placeholder（無現役模型）。dataset 必須已註冊（否則總覽會默默全紅；紅隊 RT-1#4）。"""
        if dataset not in _ds_registry.available():
            raise ValueError(f"未知資料集 '{dataset}'；可用: {_ds_registry.available()}")
        d = self._load()
        existing = {p["id"] for p in d["processes"]}
        base = _slug(display_name, dataset)
        pid, i = base, 2
        while pid in existing:  # 同名去重（紅隊 RT-1#9）
            pid, i = f"{base}-{i}", i + 1
        now = _iso(at)
        rec = {"id": pid, "display_name": str(display_name), "area": area, "dataset": dataset,
               "current_model_id": None, "next_version": 1, "deleted": False,
               "created_at": now, "created_by": str(by or _ANON)}
        d["processes"].append(rec)
        self._audit(d, actor=by, action="create_process", process_id=pid,
                    detail=f"placeholder dataset={dataset}", at=at)
        self._save(d)
        return rec

    def record_build(self, process_id: str, *, path: str, dataset: str, golden_range, fingerprint_hi: float,
                     has_y_health: bool = False, acceptance: dict | None = None,
                     by: str = _ANON, at: str | None = None, note: str = "") -> dict:
        """登錄一個新模型版本（version 由單調計數器給）→ 設為現役。v1=build_model、v>1=swap_model（重建基準）。"""
        d = self._load()
        p = self._proc(d, process_id)
        if p["deleted"]:
            raise ValueError(f"製程 '{process_id}' 已軟刪除，不可建模（請先還原）")
        version = int(p["next_version"])
        p["next_version"] = version + 1  # 單調，永不回收（紅隊 RT-1#2）
        mid = f"{process_id}__v{version}"
        had_prev = p["current_model_id"] is not None
        now = _iso(at)
        rec = {"id": mid, "process_id": process_id, "version": version, "path": path, "dataset": dataset,
               "golden_range": list(golden_range) if golden_range is not None else None,
               "fingerprint_hi": round(float(fingerprint_hi), 4), "has_y_health": bool(has_y_health),
               "acceptance": acceptance, "deleted": False, "created_at": now,
               "created_by": str(by or _ANON), "note": str(note)}
        d["models"].append(rec)
        p["current_model_id"] = mid
        p["updated_at"] = now
        self._audit(d, actor=by, action="swap_model" if had_prev else "build_model", process_id=process_id,
                    model_id=mid, detail=f"v{version} golden={rec['golden_range']}", at=at)
        self._save(d)
        return rec

    def soft_delete_model(self, model_id: str, *, reason: str = "", by: str = _ANON, at: str | None = None) -> dict:
        """軟刪除模型（只翻旗標、不刪檔）。若為現役 → current 退回最高版未刪 model 或 None。"""
        d = self._load()
        m = next((x for x in d["models"] if x["id"] == model_id), None)
        if m is None:
            raise KeyError(f"找不到模型 '{model_id}'")
        m["deleted"] = True
        self._recompute_current(d, m["process_id"])
        self._audit(d, actor=by, action="delete_model", process_id=m["process_id"], model_id=model_id,
                    detail=f"reason={reason}", at=at)
        self._save(d)
        return m

    def soft_delete_process(self, process_id: str, *, reason: str = "", by: str = _ANON,
                            at: str | None = None, incident_store=None) -> dict:
        """軟刪除製程（完全隱藏，只在歷史可見）。給 incident_store 則強制關閉其 active incidents（解孤兒）。"""
        d = self._load()
        p = self._proc(d, process_id)
        p["deleted"] = True
        self._save(d)
        closed = 0
        if incident_store is not None:  # 孤兒事件：刪製程前強制關閉，否則虛報 open/MTTR/ROI（紅隊一致）
            for it in incident_store.list(product=process_id):
                if it["status"] in ("open", "ack"):
                    incident_store.close(it["id"], note=f"製程已軟刪除（{reason}）", by=by,
                                         at=at, reason="process_deleted")
                    closed += 1
        d = self._load()
        self._audit(d, actor=by, action="delete_process", process_id=process_id,
                    detail=f"reason={reason}；關閉孤兒事件 {closed}", at=at)
        self._save(d)
        return p

    def restore_process(self, process_id: str, *, by: str = _ANON, at: str | None = None) -> dict:
        """還原製程（入口僅在歷史/稽核頁，呼應『完全隱藏只在歷史可見』）。"""
        d = self._load()
        p = self._proc(d, process_id)
        p["deleted"] = False
        self._recompute_current(d, process_id)  # current 若指向已獨立刪除的 model → 退回
        self._audit(d, actor=by, action="restore_process", process_id=process_id, at=at)
        self._save(d)
        return p

    def restore_model(self, model_id: str, *, by: str = _ANON, at: str | None = None) -> dict:
        """還原模型版本（不自動設為現役；要設現役另呼 record/指派）。"""
        d = self._load()
        m = next((x for x in d["models"] if x["id"] == model_id), None)
        if m is None:
            raise KeyError(f"找不到模型 '{model_id}'")
        m["deleted"] = False
        self._audit(d, actor=by, action="restore_model", process_id=m["process_id"], model_id=model_id, at=at)
        self._save(d)
        return m

    # ---------- 查詢 ----------
    def list_processes(self, *, include_deleted: bool = False) -> list[dict]:
        d = self._load()
        return [p for p in d["processes"] if include_deleted or not p["deleted"]]

    def get_process(self, process_id: str) -> dict:
        return self._proc(self._load(), process_id)

    def current_model(self, process_id: str) -> dict | None:
        d = self._load()
        cid = self._proc(d, process_id)["current_model_id"]
        return next((m for m in d["models"] if m["id"] == cid), None) if cid else None

    def list_models(self, process_id: str, *, include_deleted: bool = False) -> list[dict]:
        d = self._load()
        ms = [m for m in d["models"] if m["process_id"] == process_id and (include_deleted or not m["deleted"])]
        return sorted(ms, key=lambda m: m["version"])

    def audit_log(self, process_id: str | None = None) -> list[dict]:
        """稽核 log（log存取）；給 process_id 則只列該製程相關。新→舊。"""
        d = self._load()
        items = [a for a in d["audit"] if process_id is None or a["process_id"] == process_id]
        return list(reversed(items))

    def history(self, process_id: str) -> dict:
        """模型歷史監控紀錄：製程 + 所有版本（含已刪、含 acceptance 快照）+ 稽核 log（紅隊 RT-3）。"""
        d = self._load()
        p = self._proc(d, process_id)
        return {
            "process": p,
            "models": self.list_models(process_id, include_deleted=True),
            "audit": [a for a in d["audit"] if a["process_id"] == process_id],
        }
