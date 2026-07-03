"""batch-AVM 平行管線（advisory）：每批 X*=[param×stat] → 品質視圖 → 映射模型 → X* MSPC。

隔離不變式（TDD-3 結構測試鎖定）：主告警路徑（HealthIndex/score_timeline/window_detail）
**不得 import 本套件**；本套件可以 **fresh 實例**重用骨架偵測器（DQIxGate 等）與純函數
（batch_features），但不觸碰 live L1/L2 物件、不回流 Health Index 融合（隔離裁決 A：
隔離融合層、放行呈現/下鑽）。
"""
