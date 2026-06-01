# 連續製程的「無批次邊界」障礙：樣本定義與 X–Y 對齊文獻調查

> 查證日期：2026-06-01
> 範圍：半導體 AVM（wafer-to-wafer 離散 run）→ 化工連續製程 transfer 的核心障礙——連續製程沒有天然 batch boundary，X 是時間流、Y 稀疏延遲。
> 原則：嚴禁捏造文獻。每筆附真實 DOI；查不到標 `NOT FOUND`。技術術語保留英文。
> 配套檔：`docs/literature_crossref.md`（既有五維度半導體↔化工錨點與資料集清單）。

---

## 1. 問題本質：半導體 batch vs 化工 continuous 的差異

半導體 AVM 之所以能成立，是因為製程本身內建「明確的離散切割點」：每片 wafer = 一個 run，該 run 的 trace（FDC 時序）聚合成一組 X，明確對應到該片的一個量測 Y。把這個「一組 X → 一個 Ŷ」模式搬到連續製程時，三個前提全部消失。

| 面向 | 半導體 AVM（離散 run） | 化工連續製程 | 對 AVM 模式的衝擊 |
|---|---|---|---|
| **樣本邊界** | wafer = 天然離散單元；recipe step 提供 trace 切點 | 製程參數為連續時間流，無天然 run 邊界 | (a) 「一個樣本」需人為定義（窗口／穩態段／事件段） |
| **X→Y 對應** | 一片 wafer 的 X 集合 ↔ 該片 Y，一對一明確 | 反應停留時間、輸送延遲、實驗室分析延遲使 Y(t) 對應「過去某段 X」，非當下 | (b) 需估計 time delay 並對齊；錯位會污染映射 |
| **Y 取樣** | 每片或抽樣量測，節拍規律 | Y 稀疏、不規則、延遲（lab assay 數小時～數天） | (b)(e) 多速率（multi-rate）配對與 label 對齊 |
| **模式結構** | recipe / chamber 切換 = 已知 context 標籤 | grade A→B→C、停機維修，transition 期混入穩態資料 | (c) 需 multimode / change-point 偵測切出純 A 穩態段 |
| **drift 形態** | recipe 切換造成階躍 domain shift | 觸媒老化、季節等連續慢時變 + grade 切換階躍並存 | (c)(d) 自適應更新 vs golden-A 基準須分離 |
| **監控目標** | 逐片品質 + VM 可信度（RI/GSI） | grade-A re-entry 期的隱性多變量飄移 | 全鏈需先解 (a)(b)(c) 才談得上 L2–L5 偵測 |

> 三個待解子問題（後續以代號引用）：
> **(a)** 無 batch boundary 下如何定義「一個樣本/一次 run」。
> **(b)** X 與 Y 之間製程動態與時間延遲如何對齊。
> **(c)** grade/campaign 切換與 transition 期如何偵測並排除/特別處理。
> （另含 **(d)** 線上自適應、**(e)** 稀疏延遲 lab Y 配對，併入下表。）

---

## 2. 五大解決方案族對照表（每筆均經 CrossRef / 出版商查證，VERIFIED）

| 方案族 | 代表方法 | 代表文獻 + DOI | 解決 (a)(b)(c) 哪個 | 對「grade-A 隱性飄移偵測」場景的適配與限制 |
|---|---|---|---|---|
| **族 1：無邊界下定義樣本**（steady-state detection / windowing） | SSD 統計檢定切穩態段；moving window 定義樣本 | Kelly & Hedengren, "A steady-state detection (SSD) algorithm to detect non-stationary drifts in processes", *J. Process Control*, 23(3):326–331, 2013. DOI: 10.1016/j.jprocont.2012.12.001 | **(a)**，間接 **(c)** | **適配**：SSD 可自動切出「純穩態 A 段」當作可比較的 run，正是 golden-A baseline 與 re-entry 段的切割器，且其設計初衷即偵測 non-stationary drift，與本專案隱性飄移目標同源。**限制**：window 長度無最佳通解（太長延遲偵測、太短假警報多）；需逐製程調參。 |
| **族 2：X→Y 時間對齊與動態建模**（delay estimation / DPCA / lagged） | Dynamic PCA（時間滯後展開）；time-difference GPR + 局部 delay 重建；dynamic time-delay estimation | Ku, Storer, Georgakis, "Disturbance detection and isolation by dynamic principal component analysis", *Chemom. Intell. Lab. Syst.*, 30(1):179–196, 1995. DOI: 10.1016/0169-7439(95)00076-3 · Xiong, Li, Zhao, Huang, "Adaptive soft sensor based on time difference Gaussian process regression with local time-delay reconstruction", *Chem. Eng. Res. Des.*, 117:670–680, 2017. DOI: 10.1016/j.cherd.2016.11.020 · Wang et al., "A soft sensor modeling method with dynamic time-delay estimation and its application in wastewater treatment plant", *Biochem. Eng. J.*, 172:108048, 2021. DOI: 10.1016/j.bej.2021.108048 | **(b)** | **適配**：DPCA 用 lagged variables 把製程動態納入，使 T²/SPE 在含時間相關性的連續資料上不誤判；delay estimation 解決 X(t) 與延遲 Y 的對齊。對本鏈 L2（T²/SPE）與 L3（軟測量 Ŷ）是必要前處理。**限制**：lag 階數與 delay 是超參數，估錯會把動態當成飄移；time-difference 法假設 delay 局部平穩。 |
| **族 3：grade/campaign 分段**（multimode / change-point / transition） | multimode change-point detection（同時抓 mode transition 與 parameter change）；trajectory-based transition monitoring；multigrade soft sensor 顯式識別 transition mode | Xu, Zhou, Huang, Wang, "Change point detection of multimode processes considering both mode transitions and parameter changes", *IISE Transactions*, 56(12):1263–1278, 2024. DOI: 10.1080/24725854.2023.2266001 · Wang, Zheng, Wong, "Trajectory-based operation monitoring of transition procedure in multimode process", *J. Process Control*, 96:67–81, 2020. DOI: 10.1016/j.jprocont.2020.09.008 · Liu & Chen, "Integrated soft sensor using just-in-time support vector regression and probabilistic analysis for quality prediction of multi-grade processes", *J. Process Control*, 23(6):793–804, 2013. DOI: 10.1016/j.jprocont.2013.03.008 | **(c)**，部分 **(a)** | **適配**：直接對應「A→B/C→A」的 campaign 結構。Xu 2024 能區分「換模式」與「同模式內參數飄移」——後者正是本專案要抓的隱性飄移、前者是 grade 切換需排除，概念對齊度極高。Liu & Chen 2013 以「樣本不像任何穩態 grade ⇒ 判為 transition mode」提供可直接落地的 transition 排除規則。**限制**：multimode 法需事先知道或學出 mode 數；transition 段資料須有足量樣本才學得穩。 |
| **族 4：線上自適應 MSPC / soft sensor**（recursive / moving-window / JITL） | Recursive PCA；Moving Window PCA；JITL 局部模型；自適應綜述分類 | Li, Yue, Valle-Cervantes, Qin, "Recursive PCA for adaptive process monitoring", *J. Process Control*, 10(5):471–486, 2000. DOI: 10.1016/S0959-1524(00)00022-6 · Wang, Kruger, Irwin, "Process Monitoring Approach Using Fast Moving Window PCA", *Ind. Eng. Chem. Res.*, 44(15):5691–5702, 2005. DOI: 10.1021/ie048873f · Cheng & Chiu, "A new data-based methodology for nonlinear process modeling"（JITL local model）, *Chem. Eng. Sci.*, 59(13):2801–2810, 2004. DOI: 10.1016/j.ces.2004.04.020 · Kadlec, Grbić, Gabrys, "Review of adaptation mechanisms for data-driven soft sensors", *Comput. Chem. Eng.*, 35(1):1–24, 2011. DOI: 10.1016/j.compchemeng.2010.07.034 | **(d)** 自適應，間接 **(b)** | **適配**：Kadlec 2011 把自適應機制 MECE 分三類（moving window / recursive / ensemble），是選型骨架。**⚠️ 對本專案的關鍵張力**：自適應會「吸收」慢飄移使模型追上去——但本專案要的是「相對 golden-A 基準偵測飄移」，若 baseline 也跟著自適應更新就抓不到隱性飄移。故族 4 適合用於「正常時變補償（觸媒老化）」與「偵測基準」**分離**的設計，不可讓 golden-A baseline 無條件 recursive 更新。**限制**：與偵測目標直接衝突，需謹慎隔離。 |
| **族 5：稀疏延遲 lab Y 配對**（multi-rate / delayed irregular label） | 顯式建模 delayed/infrequent/irregular 量測；變動取樣時間軟測量 | Guo, Zhao, Huang, "Development of soft sensor by incorporating the delayed infrequent and irregular measurements", *J. Process Control*, 24(11):1733–1739, 2014. DOI: 10.1016/j.jprocont.2014.09.006 · Kadlec, Grbić, Gabrys 2011（同族 4，綜述含 multi-rate 處理）DOI: 10.1016/j.compchemeng.2010.07.034 | **(e)**，與 **(b)** 重疊 | **適配**：化工 lab Y 數小時/數天一筆且延遲不定，Guo 2014 顯式把「延遲、不頻繁、不規則」量測納入估計框架，正是把稀疏 Y 對回連續 X 的方法。對 L3 軟測量訓練/校正必要。**限制**：需可靠的 lab timestamp；delay 分佈假設若偏離實況，配對會系統性錯位。 |

---

## 3. 主流慣例結論：連續製程 soft sensor 的「樣本定義」與「X–Y 對齊」

### 3.1 「一個預測樣本」怎麼定義？——主流是「逐時刻 X(t)→Ŷ(t)，但 X(t) 為含 lag 的增廣向量」

文獻主流並非把連續流硬切成假 batch，而是兩種慣例並存：

1. **逐時刻動態樣本（最主流）**：在時刻 t 預測 Ŷ(t)，但輸入不是單一時刻 X(t)，而是**加入時間滯後（lagged variables）的增廣向量** `[X(t), X(t-1), …, X(t-l)]`，以涵蓋製程動態與輸送延遲——即 Dynamic PCA/PLS（Ku 1995, DOI: 10.1016/0169-7439(95)00076-3）。「一個樣本」= 一個帶歷史窗口的時刻。
2. **窗口聚合樣本（用於穩態比較/MSPC）**：當目的是 campaign 級比較或穩態監控時，先以 steady-state detection（Kelly & Hedengren 2013, DOI: 10.1016/j.jprocont.2012.12.001）切出穩態段，對段內聚合（統計量或代表向量）成「一個 pseudo-run」。本專案 L4 campaign 級分佈漂移、L2 穩態相似度屬此類。

> 結論：**逐時刻 lagged 樣本（動態建模/軟測量）+ 穩態段聚合 pseudo-run（campaign/MSPC 比較）**雙軌並行是業界標準，視監看層級而定，二者不互斥。

### 3.2 X–Y 對齊的業界標準

- **delay 估計後對齊**：以 transport/measurement delay（停留時間 + lab 分析延遲）把 Y(t) 對回 `X(t-d)`；delay 可由動態 time-delay estimation 在線更新（Xiong 2017, DOI: 10.1016/j.cherd.2016.11.020；Wang 2021, DOI: 10.1016/j.bej.2021.108048）。
- **multi-rate / 延遲不規則量測顯式建模**：lab Y 稀疏延遲時，用顯式 multi-rate 框架配對而非粗暴 down-sampling（Guo 2014, DOI: 10.1016/j.jprocont.2014.09.006）。
- **transition 期排除**：grade 切換的 transition 樣本不可混入 A 的 baseline；以「不像任何穩態 grade ⇒ 標 transition」規則剔除（Liu & Chen 2013, DOI: 10.1016/j.jprocont.2013.03.008）。

### 3.3 grade transition 在文獻中如何被偵測與排除/特別處理

- **顯式分類為 transition mode**：Liu & Chen 2013 用樣本對各穩態 grade 的機率/相似度，低於門檻即判 transition，從穩態建模/監控中排除。
- **change-point 同時辨識「換模式」與「同模式內參數飄移」**：Xu 2024（IISE T. 56(12)）的雙重變化偵測恰好把「grade 切換（要排除）」與「A 內隱性飄移（要偵測）」分開，是本專案 L3/L4 與 transition gate 的理想參照。
- **transition 軌跡單獨建模監控**：Wang 2020 對 transition 過程本身建 trajectory 模型，而非僅當雜訊丟棄——若未來要監看 transition 品質可採用，但本專案當前只需「切出並排除 transition、保留純 A 穩態段」。

---

## 4. 對本專案 `interface.py` 資料契約的具體建議

> 注意：`interface.py` 目前**尚未建立**（Glob 全庫未找到）。以下為 M0 設計該契約時的欄位建議，落地時請與五維度判斷鏈對齊，並遵守 Rule 3「資料契約是骨架，保持穩定」。

建議的最小資料契約欄位（對應 (a)–(e)）：

| 欄位 | 型別 | 語意 | 對應子問題 | 來源依據 |
|---|---|---|---|---|
| `timestamp` | datetime | 連續 X 的取樣時刻（製程節拍） | (a) | 連續流基礎軸 |
| `campaign_id` | int/str | 同一 grade 的連續生產區段 ID（A 的每次 re-entry 各給新 id） | (c) | multimode 分段（Xu 2024） |
| `grade_label` | enum {A,B,C,...} | 當前生產 grade | (c) | grade transition（Liu & Chen 2013） |
| `mode` | enum {steady, transition, shutdown/maintenance} | 穩態 / 過渡 / 停機；transition 與 maintenance 預設排除於 A baseline | (a)(c) | SSD（Kelly 2013）+ transition 分類 |
| `run_id` | int | 由 SSD 切出的「穩態段 pseudo-run」序號（campaign 內遞增） | (a) | steady-state windowing（Kelly 2013） |
| `window_index` | int | 逐時刻 lagged 樣本在其 run 內的位置（供動態建模） | (a)(b) | DPCA lagged 樣本（Ku 1995） |
| `x_lag_order` | int（meta） | 該樣本增廣向量的滯後階數 l | (b) | DPCA（Ku 1995） |
| `y_value` | float / NaN | lab 量測（多數時刻為 NaN） | (e) | 稀疏 Y |
| `y_timestamp` | datetime / null | lab 取樣的真實時刻（非登錄時刻） | (b)(e) | delayed irregular（Guo 2014） |
| `y_delay` | float / null | 估計的 X→Y 對齊延遲 d（用於把 Y 對回 X(t−d)） | (b) | time-delay est.（Xiong 2017） |
| `is_golden_A` | bool | 是否屬乾淨的 golden-A baseline 段（建基準用，不參與自適應更新） | (c)(d) | baseline 與自適應分離（Kadlec 2011 之張力） |

設計要點（第一性原理）：
1. **雙軌樣本**：契約同時支援「逐時刻 lagged 樣本」（`window_index`/`x_lag_order`）與「穩態 pseudo-run」（`run_id`），對應 §3.1 兩種慣例，避免日後為某一層硬改骨架。
2. **transition / maintenance gate 前置**：`mode` 欄位讓 L1–L5 一律先過濾 transition 與 maintenance，確保 A 的 re-entry 飄移不被 grade 切換污染。
3. **baseline 與自適應隔離**：`is_golden_A` 明確隔開「偵測基準（凍結）」與「正常時變補償（可更新）」，化解族 4 的張力（自適應會吸收飄移）。
4. **Y 對齊用真實時刻**：保留 `y_timestamp`/`y_delay` 而非只存登錄值，才能正確把延遲 Y 對回 X(t−d)。

---

## 5. 風險旗標與 NOT FOUND 清單

| 項目 | 旗標 | 說明與處置 |
|---|---|---|
| **AVM 明確用於連續化工製程（逐 run 切割）的原生文獻** | ⚠️ 部分 NOT FOUND | 查得 VM 綜述（Tandfonline, *Int. J. Prod. Res.* 2021, DOI: 10.1080/00207543.2021.1976433）指 VM「可推廣至整個 manufacturing / continuous manufacturing」，但**未找到「把 AVM 逐 wafer 切割模式原生落地到連續化工、並明確說明如何取代 batch boundary」的具體實作論文**。本專案正是要補這個 gap：以 steady-state windowing + multimode 分段「人工製造可比較的 pseudo-run」。撰寫正文時須標明此為**本專案的原創組合**，而非引用既有 AVM-continuous 方法。 |
| **族 4 自適應與偵測目標的衝突** | ⚠️ 設計紅線 | recursive/moving-window 自適應會吸收慢飄移，與「相對 golden-A 偵測隱性飄移」直接矛盾。必須以 `is_golden_A` 隔離凍結基準，**禁止** golden-A baseline 無條件自適應更新。已在 §2 族4 與 §4 要點 3 標註。 |
| **window 長度 / lag 階數無最佳通解** | ℹ️ 需調參 | SSD window（族1）與 DPCA lag（族2）皆為超參數，文獻明言無通用最佳值；TEP/penicillin 上需以 ground-truth 掃描定值，並記錄於案例設定，不可硬編一個魔數。 |
| **time-delay 平穩性假設** | ℹ️ 注意 | time-difference / 局部 delay 重建（Xiong 2017）假設 delay 局部平穩；化工負載變動會使停留時間漂移，delay 估計須可在線更新（Wang 2021），否則 X–Y 配對系統性錯位。 |
| **multimode mode 數需先驗或學出** | ℹ️ 注意 | 族3 方法多需已知或估計 mode 數；本專案 grade {A,B,C} 已知，可直接用標籤分段，降低此風險。 |
| **Kourti & MacGregor 1996 與本主題關聯** | ℹ️ 說明 | "Multivariate SPC Methods for Process and Product Monitoring"（*J. Quality Technology* 28(4):409–428, 1996, DOI: 10.1080/00224065.1996.11979699）是 grade change/transition 監控的奠基綜述（multiway PCA 推廣到 start-up/shut-down/grade change），可作 §3.3 背景引用，已驗證為真實文獻。 |
| ScienceDirect 全文頁 | ℹ️ 說明 | 多數 ScienceDirect 頁面回傳 HTTP 403，無法 WebFetch 全文；本報告所有 DOI/卷期改以 **CrossRef API** 交叉查證，全部 VERIFIED，無一筆需標 NOT FOUND（除上述「AVM-continuous 原生實作」概念性缺口）。 |

---

### 查證方法說明
- 解決方案族代表文獻共 **11 筆**，全部經 CrossRef API（api.crossref.org）回傳 title/authors/journal/volume/issue/page/year/DOI 比對，標題與卷期一致者列為 VERIFIED。
- WebSearch 用於發現候選文獻，CrossRef 用於確認精確中繼資料，避免二手摘要誤植卷期/作者。
- 唯一非具體文獻的缺口為「AVM 原生連續化工實作」，已明確標記為本專案待補的 research gap，不捏造替代來源。
