"""G2b 告警雙視圖：單一 AlarmEvent → 操作員 / 工程師兩渲染層 + AlarmSink 輸出協定。

使用者答覆 3：告警同步**現場操作員 + 工程師**（操作員再人工通報工程師＝第二層防護）。設計 D3：
單一事件兩渲染——操作員＝紅綠燈 + 去查哪裡（top RBC 變數）+ 持續窗數，**零統計術語**；工程師＝分層
語義（L1 資料效度 / L2 關係偏移 / L4 操作點移動）+ p-value + RBC 全排行 + 模型版本。

傳輸走 ``AlarmSink`` 協定（console/file 可測；webhook stub）。本層只組裝/渲染，偵測在 runner/health。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Protocol, runtime_checkable

import numpy as np

from .bundle import ModelBundle
from .runner import WindowScore

# 分層語義（工程師看層、操作員看白話「去查哪裡」）
_LAYER_SEMANTICS = {
    "L1": ("資料效度", "感測器凍結/斷訊/超界——先確認量測本身是否正常"),
    "L2": ("製程關係偏移", "多變量關係改變（每變數可能仍在規格內）——檢查下列關鍵參數"),
    "L4": ("操作點移動", "整體分布位移——檢查 setpoint / 進料 / 換批"),
}


@dataclass
class AlarmEvent:
    """單一評分窗的告警事件（雙視圖共用的事實基礎）。"""

    product: str
    window_start: int
    window_end: int
    triggered: bool  # 單窗 raw_alarm
    persisted: bool  # 連續 persistence_k 窗
    consecutive: int
    health_index: float
    layer_unhealthy: dict[str, bool]  # 各層是否異常（L1/L2/L4）
    top_contributors: list[tuple[str, float]]  # [(變數名, RBC 分數)] 降序
    p_values: dict[str, float] | None
    model_version: str

    def operator_view(self) -> str:
        """操作員視圖：紅綠燈 + 去查哪裡 + 持續窗數，零術語。"""
        if not self.persisted:
            return f"✅ 正常（健康度 {self.health_index:.2f}）"
        where = "、".join(v for v, _ in self.top_contributors[:3]) or "（待查）"
        layers = [_LAYER_SEMANTICS[k][0] for k, bad in self.layer_unhealthy.items() if bad]
        what = "、".join(layers) or "製程異常"
        return (
            f"⚠ 異常：{what}（連續 {self.consecutive} 窗）。優先檢查：{where}。健康度 {self.health_index:.2f}。"
            "請同步通知工程師。"
        )

    def engineer_view(self) -> dict:
        """工程師視圖：分層語義 + p-value + RBC 全排行 + 模型版本。"""
        return {
            "product": self.product,
            "window": [self.window_start, self.window_end],
            "triggered": self.triggered,
            "persisted": self.persisted,
            "consecutive": self.consecutive,
            "health_index": self.health_index,
            "layers": {
                k: {
                    "unhealthy": bad,
                    "name": _LAYER_SEMANTICS[k][0],
                    "action": _LAYER_SEMANTICS[k][1],
                    "p_value": (self.p_values or {}).get(k),
                }
                for k, bad in self.layer_unhealthy.items()
            },
            "rbc_ranking": self.top_contributors,
            "model_version": self.model_version,
        }


def build_alarm_event(bundle: ModelBundle, score: WindowScore, x_window: np.ndarray) -> AlarmEvent:
    """從 runner 的 WindowScore + 原始窗資料組裝 AlarmEvent（含 RBC 肇因排行）。

    層異常判定：沿用 health.hard_gates 同門檻語義（L1 inlier<0.5 / L2 SPE-anomaly>0.5 / L4 is_drift），
    但這裡用 score 已算好的 subscores/p-value 摘要 + 重算 RBC 排行（定位非因果，紅隊 H3）。
    """
    hi = bundle.health
    Xw = np.asarray(x_window, dtype=float)
    # RBC（reconstruction-based contribution）SPE 肇因：窗平均後降序取變數名
    rbc = hi.mspc_.rbc_spe(Xw).mean(axis=0)
    order = np.argsort(rbc)[::-1]
    cols = bundle.x_columns
    top = [(cols[j], round(float(rbc[j]), 4)) for j in order]
    # 層異常：用 subscores 低 + hard_gates（score.hard_gates 已含）
    layer_bad = {
        "L1": bool(score.hard_gates.get("L1", False) or score.subscores.get("L1", 1.0) < 0.6),
        "L2": bool(score.hard_gates.get("L2", False) or score.subscores.get("L2", 1.0) < 0.6),
        "L4": bool(score.hard_gates.get("L4", False) or score.subscores.get("L4", 1.0) < 0.6),
    }
    return AlarmEvent(
        product=bundle.product,
        window_start=score.start,
        window_end=score.end,
        triggered=score.raw_alarm,
        persisted=score.persisted_alarm,
        consecutive=score.consecutive,
        health_index=round(score.health_index, 4),
        layer_unhealthy=layer_bad,
        top_contributors=top,
        p_values=score.fwer,
        model_version=bundle.created_at,
    )


@runtime_checkable
class AlarmSink(Protocol):
    """告警輸出協定（現場接 mail/LINE 自行實作 emit）。"""

    def emit(self, event: AlarmEvent) -> None: ...


class ConsoleSink:
    """印操作員視圖到 stdout（可測：收集到 list）。"""

    def __init__(self):
        self.log: list[str] = []

    def emit(self, event: AlarmEvent) -> None:
        line = event.operator_view()
        self.log.append(line)
        print(line)


class FileSink:
    """append 工程師視圖（JSON lines）到檔。"""

    def __init__(self, path: str):
        self.path = path

    def emit(self, event: AlarmEvent) -> None:
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event.engineer_view(), ensure_ascii=False) + "\n")


def dispatch(event: AlarmEvent, sinks, *, only_persisted: bool = True) -> bool:
    """把事件送到各 sink；``only_persisted=True``（預設）僅送持續告警（濾單窗毛刺）。回傳是否送出。"""
    if only_persisted and not event.persisted:
        return False
    for s in sinks:
        s.emit(event)
    return True
