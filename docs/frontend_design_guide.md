# 前端設計指南（design-advisor + taste-skill 落地）

> 用途：交付前端（監控產品 UI + 銷售 pitch 頁）的設計依據。
> 依全域規範：外部 skill 知識先落地為 repo 版本化真相，再進入實作（對話 context 不算可靠來源）。
> 來源（2026-06-16 擷取理解，**非逐字複製**——上游 `SKILL.md` 為權威，細節以上游為準）：
> - design-advisor：<https://github.com/YuriCrystal/design-advisor>（`skills/design-advisor/SKILL.md`，MIT）
> - taste-skill：<https://github.com/leonxlnx/taste-skill>（`skills/taste-skill/SKILL.md`，MIT）

---

## 1. 關鍵：兩個 skill 的適用範圍不同（別用錯）

| skill | 管的範圍 | 對本專案 |
|---|---|---|
| **design-advisor** | 通用設計批評：平面 + **UI/UX/產品**（介面、流程、可用性、IA、表單、無障礙、設計系統）| **監控產品 UI**（總覽 / 新建精靈 / 結果下鑽）的設計與審查依據 |
| **taste-skill** | **反-slop 行銷前端**：landing page / portfolio / about / redesign。**明確排除 dashboard、data table、multi-step form、code editor、native mobile、realtime UI** | **不直接管監控產品 UI**（正是它 scope 排除的型態）；管的是**銷售 landing / pitch 頁**。其「通用反-slop 規則」仍可借用到產品 UI |

> ⚠️ 用錯範圍提醒：把 taste-skill 套到 dashboard / 多步精靈是誤用（它自己排除）。產品 UI 走 design-advisor；taste-skill 留給「吸引購買」的行銷頁。

---

## 2. design-advisor 工作流（產品 UI 審查用）

1. **判斷設計類型**（介面 / 流程 / 平面…）。
2. **釐清 brief**：使用者 / 任務 / 情境（裝置·通路）/ 限制。
3. **視覺解讀四測**：**盤點 → 瞇眼**（模糊後層級還在嗎）**→ 3 秒**（主訊息一眼懂嗎）**→ 動線**（視線流是否順）。
4. **給具體改法**：**先肯定做對的 → 判斷 → 執行方向**，格式「改成什麼＋為什麼」+ checklist。禁空話、不提品牌/設計師名、中性語氣。

核心精神（9 原則摘要）：先有 idea 才動手、層級優先、降低摩擦、系統性一致、顧倫理與可用性、「爛就別上」（可上線/不可上線裁決）。

---

## 3. taste-skill 規則（銷售 landing / pitch 頁用）

- **動手前宣告**：Design Read（一句：頁型 / 受眾 / vibe / 系統）+ 三個 dial 值（附理由）+ 選定設計系統（Material / Fluent / Carbon / Radix / shadcn… 或誠實標自訂美學）。
- **三個 dial（1-10）**：`DESIGN_VARIANCE`（對稱乾淨 ↔ 不對稱現代）、`MOTION_INTENSITY`（hover ↔ scroll/GSAP 編排）、`VISUAL_DENSITY`（留白藝廊 ↔ 密集儀表）。
- **硬規則（反 AI-tell）**：`em-dash「—」全頁禁用`（標題/eyebrow/pill/內文/引言/署名皆禁）；**單一 accent 色**（不可第 7 段突然冒出別色 CTA）；CTA 文字桌機**不換行**；**禁預設 beige+brass+espresso 高級感配色**（除非 brand 指名）；**serif 紀律**（非 editorial/luxury 不預設 serif）。
- **交付前 87 項 pre-flight，一項未過即整份 fail**（最終過濾）。

---

## 4. 本專案前端的設計決策（落地）

- **監控產品 UI**（已出可點擊互動原型）：採 design-advisor。三屏＝總覽 → 新建精靈 → 結果下鑽，對應 Shneiderman 真言（overview → zoom → details-on-demand）+ Hick（首頁 2 主決策）+ 漸進揭露（細節指標藏下鑽）。
- **通用反-slop（產品 UI 也採用 taste-skill 的可移植硬規則）**：em-dash 禁用（改用 `·`／`、`／`→`）；**語義色 vs accent 分離**——綠=健康、紅=告警為**固定語義狀態色**（不可亂改），藍=可信度與測試段，附 legend；字體紀律、單一品牌強調色。
- **銷售 pitch / landing 頁**：**不做**（使用者 2026-06-16 決定，直接展示系統前端）。taste-skill 規則（§3）保留為**參考知識**，日後若需行銷頁再啟用；曾建之 `frontend/landing.html` 已移除。

### design-advisor 對產品 UI 的自審（affirm → 問題 → 改法）
- **肯定**：狀態優先（紅綠燈）、漸進揭露、克制配色、敘事清楚（黃金健康 → 後段隱性飄移告警）。
- ~~問題 1（混用賣點頁/產品頁、缺 hero）~~：**作廢**——使用者決定不做銷售頁，直接展示產品 UI，入口即監控總覽。
- **問題 2（已修）**：色彩語義已宣告——綠/紅為固定語義狀態色、藍=可信度，單一品牌 accent 靛藍，附 legend。
- **問題 3（已修）**：結果頁第一眼先給健康時間線 + 紅窗，RBC/Ŷ 保持點擊揭露。
- **裁決**：產品 UI 三屏「方向可上線」；視覺/點擊待本機渲染驗證（NOT VERIFIED-visual）。

> 後端 `deploy/demo.py`（`score_timeline`/`window_detail`）已能真算原型所有數字（health/confidence/RBC/Ŷ-vs-Y），接上即真。

---

## 5. 多角色子代理 UX 檢視（2026-06-16）

派 4 個子代理扮演石化產線職務檢視三屏 UI。一致肯定：偵測內核是真本事，缺口幾乎全在呈現層、非演算法。

| 角色 | 裁決 | 第一痛點 |
|---|---|---|
| 現場作業員 | 不能用 | 首頁是建模工作台非監控盤；滿屏術語；告警無聲音/ACK/白話 SOP；樣本索引非時鐘 |
| 現場工程師 | 勉強 | 樣本索引對不上 DCS/historian；無告警清單；可信度是數字非「可信/存疑」；無位號趨勢 |
| 生產製程工程師 | 勉強 | 驗收「可上線」寫死（acceptance 沒接）；門檻不可調；測試段不能自選；生命週期 UI 不存在 |
| 生產處長 | 需補強 | 單一模型 demo 非全廠視圖；無 KPI/MTTR/事件閉環/ROI/權限/手機 |

3 核心問題（design-advisor 收斂）：① 首頁定位錯（要現況非模型數）② 不對齊現場語言與時間（樣本索引/術語/數字）
③ 後端已有能力沒接 UI（acceptance/persistence/lifecycle）。

### 分級與進度
- **P0（已實作 74bd6bf）**：wall-clock 時間軸、驗收真接上（FAIL 擋上線）、告警可信/存疑判定橫幅、總覽各模型當前健康燈。
- **P1（roadmap）**：告警清單表（點 row 進下鑽）、門檻/persistence_k slider、生命週期面板（currency/重建）、匯出 CSV/PDF、ACK/消音/處置留痕、聲音告警、位號(tag)對照 + DCS/historian 趨勢連結。
- **P2（需使用者拍板的產品層，新後端基礎建設）**：全廠 廠→區→裝置→產品 階層視圖、事件閉環+MTTR、ROI 效益看板、權限分層+稽核 log、手機 responsive。
> Rule 7 範圍誠實標：P2 是新產品層級（數週工程），非一次 UI 優化能補；建議單一裝置付費試點先行（處長語）。

---

## 6. 增量 5 多角色複審（2026-06-16）

4 角色子代理複審增量 5（事件閉環/ACK/MTTR/ROI/全廠總燈/可點卡/wall-clock/可信判定）。

一致肯定：事件閉環+MTTR+防重複、「可信/存疑」判定橫幅、驗收真接上、ROI 誠實標、CSV 匯出。

### 3 核心問題（design-advisor 收斂）
1. **治理層 correctness（P0）**：驗收 FAIL 未物理擋存檔（demo.py 先 save 後 acceptance）；事件署名寫死 `by="工程師"` 無問責（處長合規 gating）；同名模型靜默覆蓋。
2. **監控盤不主動告警（P0，作業員）**：無 dcc.Interval 自動刷新 + 無聲音 → 不戳不亮，三班現場不可用。
3. **最後一哩定位斷裂（P1，現場工程師）**：RBC 顯示內部欄名（xmeas07）非 DCS 位號；無 historian 趨勢連結。

### 真 bug（優先修）
- 驗收 FAIL 未擋存檔（先 save 後驗收）；共用 close-note 多案可能貼錯案；署名寫死無問責。

### 角色裁決
作業員 不能用(當班)｜現場工程師 勉強｜製程工程師 勉強｜處長 需補強(接近試點)。
綜合：POC 紮實，尚未可現場部署；到「試點」缺口集中＝治理(auth/問責/FAIL-block) + 作業員告警(Interval+聲音) + 最後一哩(位號對照)。

### 增量 6 roadmap（依阻擋程度）
- P0 治理：acceptance 移到 save 前（FAIL 不落地）；事件動作帶真實 actor/角色 + 稽核 log；建模 product 命名 + 覆蓋確認。
- P0 作業員：dcc.Interval 自動刷新 + 聲音告警 + 告警卡一行白話 SOP 動作 + 交接班摘要。
- P1 現場工程師：位號(tag)對照 config 層（RBC/下鑽顯位號）+ historian deep-link；close-note 綁每卡 + close-reason(誤報，排除 MTTR/ROI)；告警清單篩選/排序；事件→該窗下鑽。
- P1 製程工程師：門檻/persistence slider；測試段圈選 + 選定區間密集評分；golden 多段；生命週期面板(lifecycle 後端已備)。
- P2 處長：廠→區→裝置階層(config)；手機 responsive；PDF 月報；ROI 損失可輸入 + 試點實測回填。

---

## 7. 增量 6 最終多角色複審 + loop 終止（2026-06-17）

經 7 輪自動優化（P0-a 治理/告警/問責、P0-b 誤報/ROI/手機、位號、門檻 slider、role-view、閃示/交接班/篩選、廠區階層）+ 複審揪出的 3 真 bug 修正，4 角色最終裁決：

| 角色 | 最終裁決 | 剩餘 blocker（性質）|
|---|---|---|
| 現場作業員 | 可試點（白班陪跑）| 真聲音告警通道（外部 alerting）、手機實機點擊驗證 |
| 現場工程師 | 可試點（上線接 historian）| historian/PI 趨勢 deep-link（外部，需客戶 DCS）|
| 生產製程工程師 | 可試點（非正式上線）| 測試段圈選、生命週期 UI 接線（demo 可補）；驗收對實際 golden（demo 可補）；真 confirmed-normal 資料（外部）|
| 生產處長 | **可採購試點** | 真 SSO/RBAC、PDF 月報（外部/導入期 IT 整合）|

### 已修 demo 真 bug（0012c8c）
- 驗收 window 對齊使用者選值（原寫死 60 脫鉤）+ 明示「採標準 hold-out，上線應對實際 golden 驗收」。
- _run 自動開案/SOP 套 tag_map（事件肇因顯 DCS 位號，非 xmeas07）。
- 作業員視圖去術語洩漏（verdict reason 改白話 op_reason，不複用工程師字串）。

### loop 終止理由（Rule 12 誠實）
4 角色一致達「可採購試點」；絕對「可上線」的剩餘項本質需客戶現場環境（SSO/historian/聲音通道/PDF/真實 confirmed-normal
資料）——**公開資料 demo 無法滿足**。續跑 5 分鐘 loop 無法推進外部項，故停止 cron（CronDelete 8e6c72d2）。

### 可選後續（demo 仍可補，非試點 blocker）
- 測試段 RangeSlider + 選定區間密集評分；生命週期面板接 lifecycle.py；驗收對使用者實際 golden 驗收。
- 事件卡→該窗結果 deep-link；門檻 slider「套用此門檻」寫回 bundle；前端 _event_action 署名 callback 測試。
- 正式上線（pilot 後）：接企業 SSO/RBAC、historian 趨勢 deep-link、真聲音告警、PDF 月報。
