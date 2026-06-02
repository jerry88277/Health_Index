"""前處理層：把連續流切成 campaign/穩態 pseudo-run、標記 transition/maintenance、
對齊 X→Y 延遲。輸出衍生欄供 detectors 使用（Rule 3：契約穩定，衍生欄由此填）。
"""
