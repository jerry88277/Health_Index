"""G1/G2/G3 通知 payload 組裝 + G1×G3 同窗共發優先規則（確定性；SMTP 傳輸 deferred）。

鎖定決策（使用者 2026-07-02）：G1（實際量測 Y 偏離歷史，獨立於 X 與 Control-Limit spec）與
G3（虛擬量測 Ŷ 越出模型適用域）**同窗共發時發兩封獨立信、不合併成單一裁決**（Rule 7：兩者正交，
擇一/平均都失真）——
- **G1** 是已確認的**真實量測**偏離：獨立於 X、獨立於 Ŷ 是否可信 → 最高優先（actionable 品質事件）。
- **G3** 是 **Ŷ 預測**的可信度警訊：Ŷ 外推⇒任何 Ŷ-based 訊號不可信；本身**未確認**真實偏離 → 次優先。
- **G2** 是 G1 之 Y 漂移的 **X 歸因**（哪個參數推動 Y）→ 併入 G1 那封信的 cause（同一事件的偵測+肇因）。

兩封**互相交叉引用**（``co_fired``）讓收件人見全貌，但主旨/肇因/收件對象各異故分開發。
SMTP 模組為外部現成、待串接（本模組只產生確定性 payload，不做傳輸；避免昂貴 API 重複扣費之卡榫
留待串接時加）。本模組不 import 任何偵測器（純組裝），不影響 batch-AVM 隔離。
"""

from __future__ import annotations

from dataclasses import dataclass

# 優先規則（數字小＝優先高）：G1 已確認真實偏離 > G2 其 X 歸因 > G3 Ŷ 可信度警訊。
PRECEDENCE = {"G1": 1, "G2": 2, "G3": 3}


@dataclass(frozen=True)
class Notification:
    """單封通知 payload（確定性；SMTP 串接時據此填信）。"""

    goal: str                    # "G1" | "G3"（G2 併入 G1 的 cause）
    priority: int                # = PRECEDENCE[goal]（數字小＝優先高）
    subject: str
    cause: str                   # 指名肇因：G1＝實際 Y（+G2 的 X 歸因）；G3＝越域 X 參數
    summary: str
    co_fired: tuple              # 同批共發的其他 goal（交叉引用），如 ("G3",)
    batch_index: int | None = None


def compose_notifications(*, batch_index: int | None = None,
                          g1: dict | None = None, g2: dict | None = None,
                          g3: dict | None = None) -> list[Notification]:
    """依觸發的目標組裝**分開**的通知並按優先規則排序（G1×G3 → 兩封，不合併）。

    Args:
        g1: G1 結果，觸發條件 ``g1["drifted"]`` 為真（實際 Y 偏離歷史）。
        g2: G1 之 X 歸因（``g2["top_param"]``）；併入 G1 那封信的 cause，不單獨成信。
        g3: G3 結果，觸發條件 ``g3["alarm"]`` 為真；``top_param``／``reason`` 為越域肇因。

    Returns:
        Notification 串，按 ``priority`` 升冪（G1 先於 G3）；未觸發者不產生（無幻影信）。
    """
    fired: list[str] = []
    if g1 and g1.get("drifted"):
        fired.append("G1")
    if g3 and g3.get("alarm"):
        fired.append("G3")
    out: list[Notification] = []
    for goal in fired:
        co = tuple(x for x in fired if x != goal)  # 交叉引用同批其他共發目標
        cross = f"（同批另有 {'／'.join(co)} 共發，見另一封）" if co else ""
        if goal == "G1":
            xp = (g2 or {}).get("top_param")
            cause = f"實際量測 Y 偏離歷史，歸因參數 {xp}" if xp else "實際量測 Y 偏離歷史（未歸因 X）"
            out.append(Notification(
                goal="G1", priority=PRECEDENCE["G1"], subject="實際量測 Y 偏離歷史分佈（G1）",
                cause=cause, summary=f"批 {batch_index}：{cause}。已確認真實偏離，請確認製程。{cross}",
                co_fired=co, batch_index=batch_index))
        else:  # G3
            xp = g3.get("top_param")
            reason = g3.get("reason") or ""
            cause = f"越域參數 {xp}（{reason}）" if reason else f"越域參數 {xp}"
            out.append(Notification(
                goal="G3", priority=PRECEDENCE["G3"], subject="虛擬量測 Ŷ 越出模型適用域（G3）",
                cause=cause, summary=f"批 {batch_index}：Ŷ 越適用域，{cause}；Ŷ 預測不可信，請確認模型域。{cross}",
                co_fired=co, batch_index=batch_index))
    out.sort(key=lambda n: n.priority)
    return out
