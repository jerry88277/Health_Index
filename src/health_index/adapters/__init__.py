"""資料 adapter 層：各資料源 → 統一 interface 契約。

各 adapter 只負責把原始資料映射成 ProcessDataset（raw 欄）；
分段/對齊/衍生欄由 preprocess 層負責（Rule 3：契約穩定）。
"""
