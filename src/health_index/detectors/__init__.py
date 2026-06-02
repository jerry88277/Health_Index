"""偵測器層（L1–L4）：確定性數學，runtime 不呼叫 LLM（Rule 5）。

各層在 golden-A 上 fit 並凍結（紅隊 N3），對新樣本輸出指標與旗標。
"""
