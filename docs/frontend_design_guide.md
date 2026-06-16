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
