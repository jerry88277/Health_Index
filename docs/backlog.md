# Backlog — Health_Index MVP 後續開發

> 版本 v0.1 · 日期 2026-06-02 · 上游：`development_plan.md` v0.2、`requirements_spec.md` v0.2
> 由 2026-06-02 對話決策轉為 repo 版本化真相（對話 context 不算可靠來源）。
> 紀律承襲：綠燈才 commit（`[verified]`）、TDD 紅→綠、承載性結論派 ≥2 獨立紅隊、誠實 surface 不造假。

M0–M10（MVP 全棧）已收官。以下為已知缺口，皆**非 MVP 阻塞**，列為後續單元。
**開發順序＝推薦優先序**：B1 → B2 → B3 → B4。

---

## 優先序總覽

| ID | 項目 | 優先 | 為何此序 | 工作量 |
|---|---|:--:|---|:--:|
| **B1** | 時間軸端點 + RBC 上前端 | 1 | 最快讓「抓到偏移 + 知道是哪個參數」進畫面，價值立現；零新數學（偵測鏈已算好） | 中 |
| **B2** | 真實集 adapter | 2 | AC-4 正式採用門檻（真實集不退化），破除「合成自證」循環論證 | 中（UCI Gas）／高（TEP） |
| **B3** | AC-6 FWER 控制 | 3 | 嚴謹度：壓 golden-A 誤報率≤α，鞏固 DoD#1 | 中 |
| **B4** | L5 批次 DTW | 4 | 另一條產品線（批次製程），需批次資料，與連續型 MVP 正交 | 大 |

---

## B1 — 時間軸端點 + RBC 上前端

**是什麼**：後端新增逐樣本端點，前端畫時間序列與肇因。
- `GET /analyze/{job}/health`：逐樣本 T²/SPE/GSI 隨時間（campaign 內何時越限）。
- `GET /analyze/{job}/contribution`：逐樣本 RBC（`mspc.rbc_spe`），指出**哪個變數**帶飄移。
- 前端：per-sample 時間軸圖（T²/SPE + 控制限）＋ RBC 變數排序長條（告警樣本的肇因 top-k）。

**為何重要**：目前前端只到 campaign 級「一根長條」。本專案核心價值「每變數在規格內、多變量卻飄移」要看出**何時**起、**哪個變數**——RBC 已實證可點名（drift 段比乾淨段高 14–49×、而單變數 3σ 越界率 ~0），缺的只是接線上 UI。

**現況**：`mspc.py` 的 `t2/spe/gsi/rbc_spe` 全已實作並凍結於 golden-A fit；`server.py` docstring 已標這些端點為 M-later；前端 `build_*_figure` 為純函式好擴充。

**範圍 / 誠實標記**：job 模型需先決定（無狀態重算 vs job store）；MVP 採無狀態（請求帶 seed/drift 重算，不引入 job 持久層，Rule 2）。RBC 為「定位非因果」，多方向漂移有殘留 smearing（紅隊 H3），UI 須標示。

**DoD**：
1. 兩端點回傳逐樣本陣列，經 HTTP 端到端驗證（drift campaign T²/SPE 越限樣本比例高、RBC top-k 命中注入飄移的變數）。
2. 前端時間軸圖 + RBC 圖真接後端真資料；WHY 測試鎖「RBC 在 drift 段對的變數升、單變數 SPC 盲」。
3. 薄封裝（Rule 3，零判斷鏈重算）。

---

## B2 — 真實集 adapter

**是什麼**：把真實公開資料映射到統一 `interface.py` ProcessDataset 契約，沿用同一偵測鏈跑。
- 候選（成本遞增）：**UCI Gas Sensor Array Drift**（CSV 直載、無授權門檻、本就是 drift 資料）→ **PRONTO**（真實工廠，需下載/解析）→ **TEP via tep2py**（需編 Fortran）。

**為何重要**：目前全為合成 `synthetic.generate`。dev_plan §2 明示 pyTEP/合成是 oracle，正式採用須綁「真實集不退化」以破除循環論證。這是 **AC-4 的正式門檻**，也是真實工廠導入的信心來源。

**現況**：`interface.py` 契約與 adapter 插槽已就緒（M1 設計）；尚無任何真實 adapter。

**範圍 / 誠實標記**：真實資料無精準 ground-truth（不像合成可注入已知飄移），驗證改為「golden 段不誤報 + 已知工況切換被偵測」。語意映射（哪些欄是 X/Y、grade/campaign 定義）須對照各資料集官方文件，**不臆測欄位語意**（Rule 8）。需下載＝需使用者確認網路/授權。

**DoD**：
1. 至少 1 個真實集（建議 UCI Gas Drift）接入同一契約，同一偵測邏輯**零 per-dataset 調參**跑通。
2. 「真實集 golden 段不退化（不誤報）」斷言通過；納入 `crossval` 網格外的真實 case。
3. 需大幅 per-dataset 調參才過＝過擬合 → surface，不硬調。

---

## B3 — AC-6 FWER 控制

**是什麼**：融合多層決策時控制族系錯誤率（family-wise error rate），把 golden-A 誤報率壓在 ≤ α。
- 各分量 → 對 golden null 的尾機率 → 單一決策點 + FWER 校正（如 Holm/Bonferroni 或校準後的單點門檻）取代現行多訊號 OR。

**為何重要**：成功判準 **AC-6＝golden-A 誤報率≤α**。現行 M6 是 L1/L2/L4 訊號 + 硬閘 OR 起來——測得越多、誤報越多，威脅「golden 維持健康」的 DoD#1 與「單一決策點」理想（紅隊 N2）。

**現況**：M6 用雙軌融合 + 硬閘安全網（H8），**未做嚴格 FWER**；`config.fwer_method` 已預留未接線；`health.py` docstring 誠實標此為待辦。子分數 s_l1/s_l2 為比例近似、s_l4 為 exp 衰減，**非嚴格尾機率**（N6 設計債）。

**範圍 / 誠實標記**：須先把各層轉為「對 golden null 的尾機率」（N6），再套 FWER。自相關資料的 null 須 block-permutation（synthetic 為 iid，真實集才顯）。

**DoD**：
1. 各層輸出校準為對 golden null 的尾機率。
2. 單一決策點 + FWER 校正取代裸 OR；**AC-6 測試**：golden-A 多 seed/hold-out 誤報率 ≤ α（容忍帶）。
3. 不破壞既有判準 1/2/3（drift 仍被抓、乾淨回歸仍健康）。

---

## B4 — L5 批次 DTW

**是什麼**：第 5 層偵測器，用 DTW（動態時間規整）對齊**批次製程軌跡**，偵測批間軌跡形變。
- 資料：penicillin / IndPenSim 批次。線上成本須 Sakoe-Chiba band／降採樣／FastDTW 限縮（Rule 6）。

**為何重要**：專案涵蓋連續＋批次兩型。連續＝穩態（L1–L4 已做，T²/SPE/MMD）；批次＝每 run 是長度不一的時間軌跡，須先 DTW 對齊才能比形狀。L5 是批次分支。

**現況**：未實作；dev_plan v0.2 明示「連續型聚焦，L5 延後出 MVP，待批次資料就緒」。

**範圍 / 誠實標記**：DTW 用在連續穩態無意義（Rule 12，不在連續資料硬套）；須有真正批次軌跡資料才開工。與 B1–B3（連續型）正交，可獨立排程。

**DoD**：
1. 批次資料 adapter（penicillin/IndPenSim）接 `interface` 契約（批次模式）。
2. DTW 對齊 + 批間軌跡偏移偵測；WHY 測試鎖「軌跡形變被抓、正常批不誤報」。
3. 線上路徑用 band/降採樣限成本，超節拍 surface。

---

## 變更紀錄
- v0.1：由 2026-06-02 對話將 4 項已知缺口文件化，定優先序 B1→B4 與各項 DoD。
