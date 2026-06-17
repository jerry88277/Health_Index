"""增量7-D demo 資料集說明 + 推薦預設（版本化真相，不散在 UI）。

每個資料集一句人話「這是什麼製程、看點在哪」+ 推薦評分窗長，讓使用者選完資料源「點下一關就看到對應結果」
（item3 導引）。偵測器為確定性數學，本檔僅供 UI 導引文案，**不影響演算法**（Rule 5）。
"""

from __future__ import annotations

_CATALOG: dict[str, dict] = {
    "synthetic": {
        "title": "合成連續製程 A（X→Y 已知）",
        "blurb": "受控合成製程，X 製程參數映射到 Y 品質。看點：換產品後回歸 A 時，"
                 "每變數都還在規格內、但多變量關係已偏移的隱性飄移——單變數 SPC 抓不到、本系統抓得到。",
        "default_window": 60, "y_label": "品質量測 Ŷ", "covert": False,
    },
    "synthetic_pgn": {
        "title": "高維合成製程（p≫n，128 維）",
        "blurb": "刻意設計的高維製程（變數遠多於黃金樣本）。看點：高維下隱性飄移仍能被偵測（PCA 預降維路徑）。",
        "default_window": 60, "y_label": "品質量測 Ŷ", "covert": False,
    },
    "tep": {
        "title": "Tennessee Eastman 連續化工製程",
        "blurb": "化工界標準連續製程基準。看點：跑完非 A campaign 或維修後，第一段回歸 A 是否殘留飄移（re-entry 期）。",
        "default_window": 60, "y_label": "產品品質 Ŷ", "covert": False,
    },
    "tep_tp": {
        "title": "Tennessee Eastman（保時序）",
        "blurb": "TEP 保留時間順序版本（不重抽樣）。看點同 TEP，更貼近真實時序的 re-entry 飄移。",
        "default_window": 60, "y_label": "產品品質 Ŷ", "covert": False,
    },
    "uci_gas_drift": {
        "title": "UCI 氣體感測器陣列漂移（真實）",
        "blurb": "真實感測器老化資料（16 感測器×8 特徵＝128 維）。看點：感測器隨時間自然老化造成的漂移。"
                 "高維逐窗評分昂貴，總覽會自動降採樣顯示。",
        "default_window": 60, "y_label": None, "covert": False,
    },
    "ccpp": {
        "title": "聯合循環發電廠 CCPP（真實，含 Y）",
        "blurb": "真實電廠資料，X＝環境與運轉條件 → Y＝淨發電量。看點：真實非化工製程的軟量測（Ŷ vs 實際 Y）。",
        "default_window": 48, "y_label": "淨發電量（MW）", "covert": False,
    },
    "ccpp_covert": {
        "title": "CCPP + 隱性飄移（半合成）",
        "blurb": "在真實 CCPP 上注入隱性飄移：保留每變數的單變數分佈、只打亂變數間相關結構 → "
                 "單變數 SPC 完全看不到、多變量 SPE 抓得到。這正是本系統存在的理由。",
        "default_window": 48, "y_label": "淨發電量（MW）", "covert": True,
    },
    "steel": {
        "title": "鋼廠用電（真實，含 15 分鐘時序）",
        "blurb": "真實鋼廠能耗資料，X＝功率因數等運轉量 → Y＝用電量。看點：有真實 wall-clock 時序的軟量測。",
        "default_window": 96, "y_label": "用電量（kWh）", "covert": False,
    },
    "steel_covert": {
        "title": "鋼廠用電 + 隱性飄移（半合成）",
        "blurb": "在真實鋼廠用電上注入隱性相關結構偏移：單變數正常、多變量關係已變 → 早於單變數 SPC 預警。",
        "default_window": 96, "y_label": "用電量（kWh）", "covert": True,
    },
}

_DEFAULT = {"title": "", "blurb": "（此資料集無導引說明）", "default_window": 60, "y_label": None, "covert": False}


def describe(name: str) -> dict:
    """回傳 {title, blurb, default_window, y_label, covert}；未收錄→中性預設（title 退回名稱）。"""
    d = dict(_DEFAULT)
    d.update(_CATALOG.get(name, {}))
    if not d["title"]:
        d["title"] = name
    return d


def default_window(name: str) -> int:
    """該資料集的推薦評分窗長（item3：讓使用者不必想就能看到結果）。"""
    return int(describe(name)["default_window"])
