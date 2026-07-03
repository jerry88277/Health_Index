# CLAUDE.md — Health_Index 專案規範

本檔為專案級規範，與全域 `~/.claude/CLAUDE.md` 衝突時以本檔為準。
偏好：非 trivial 工作「謹慎 > 速度」；trivial 任務自行判斷。

---

## 專案脈絡 (Context)

取成大鄭芳田教授 **AVM（自動虛擬量測）的精神**，做一個**泛化工製程**的健康度／隱性飄移偵測程式。產品核心（北極星，2026-07-02 定調）：**多產線健康儀表板**——點產線→線上即時記錄／告警歷史／模型建立資訊，告警下鑽到偏移的 X 參數或 Y 量測；三目標 G1（純 Y-vs-歷史漂移，獨立於 X）／G2（Y 漂移→X 歸因）／G3（Ŷ 越適用域→X 歸因），各以 SMTP 通知收尾（串接暫緩）。當前最優先＝9 步 batch-AVM 精靈（設計見 docs/batch_avm_design.md）。

- **要解的問題**：同一條產線跑產品 A → 換線生產 B/C 或停機維修 → 回頭跑 A 時，**A 有沒有隱性飄移**？「隱性」＝每個感測器都還在單變數規格內、但多變量關係或 X→Y 映射已偏移，單變數 SPC 抓不到。
- **AVM 初衷**：以虛擬量測（軟測量）取代破壞性／昂貴抽樣——用製程參數 X 算出可能的量測值 Ŷ，並在預測不可信時提前預警。
- **判斷鏈（MECE，第一性原理）**：
  `L1 DQI_x 資料效度閘 → L2 T²/SPE/GSI 多變量域相似度 → L3 軟測量 Ŷ + conformal（CP-band）可信度 → L4 campaign 級 Wasserstein/KL 分佈漂移 →（批次）L5 DTW 軌跡對齊 → Health Index 0–1 + 觸發旗標`，重點監看「非 A campaign 或維修事件後第一段 A」的 re-entry 期。
- **資料基準**：連續製程＝**TEP (Tennessee Eastman)**；批次軌跡＝**penicillin / IndPenSim**；G1 純 Y 漂移之 ground truth＝**合成儀器漂移 adapter**（TEP 的 Y=f(X)，結構上不可證 G1）。架構預留真實產線資料的 adapter 接口。
- **技術棧**：Python；numpy / scipy / scikit-learn / pandas / POT / pytest。**偵測器為確定性數學，runtime 不呼叫 LLM**。
- **文獻佐證**：以 `docs/literature_crossref.md`（半導體↔化工兩邊參照，逐筆查證）為唯一真相，嚴禁捏造。

### 成功判準 (Definition of Done)
在有 ground-truth 的情境上，Health Index 必須：
1. golden-A 期間維持低分（健康）。
2. 對「每變數都在規格內」的隱性多變量飄移，**早於單變數 SPC** 升高。
3. 能區分「乾淨換線後 A 正常回歸」vs「A 回歸但殘留飄移」。
> 綠燈才 commit：unit test → 型別 → health check 全過才 `git commit`，訊息帶 `[verified]`。連續 3 次同錯 / regression / doom loop 時自動 `git reset --hard <last-green>` 回退重規劃。

### 規則適用總覽
| 規則 | 適用度 | 本專案重點 |
|---|---|---|
| 1,3,4,7,8,10,12 | ✅ 直接 | 設計與紀律主幹 |
| 2,11 | 🔁 重詮釋 | 簡單性 / 沿用既定慣例 |
| 5 | ✅（重詮釋後） | 偵測器須確定性，不靠 LLM |
| 9 | ✅（寫程式任務啟用） | 測試編碼 WHY |
| 6 | ⚠️ runtime N/A | 改為「線上運算成本上限」 |

---

## Rule 1 — Think Before Coding
明列假設，尤其**半導體→化工的可轉移性假設**（如：AVM 預設 batch/R2R，化工多為連續製程；GSI 門檻來自靜態歷史）。不確定就問，不要猜。模稜兩可時並陳多種詮釋。有更簡單做法就反對。搞不清楚「某指標在化工是否成立」時停下並指名。

## Rule 2 — Simplicity First
最小可解程式，不做投機功能。先在 TEP + penicillin 上跑通五維度判斷鏈即可；**Health Index 融合先用簡單加權**，不要一開始就上 learned meta-model。指標不超出五維度框架（例外：G1 純 Y-vs-歷史監控依 2026-07-02 裁決為**獨立輕量模組**（CUSUM/KS on raw Y），刻意不強塞五層 PCA/T²/SPE 框架——這正是 Rule 2 的應用）。資深工程師會嫌過度設計就簡化。

## Rule 3 — Surgical Changes
**五維度 MECE 判斷鏈與統一資料契約 (`interface.py`) 是骨架，保持穩定**；只動領域層（adapters、案例、門檻、製程命名）。不順手「改善」相鄰 code／註解／格式，不重構沒壞的東西，沿用既有風格。

## Rule 4 — Goal-Driven Execution
以上方三條成功判準為 loop 目標，迭代到 ground-truth 驗證通過為止，不照步驟流水帳。強判準讓你能獨立 loop。

## Rule 5 — Use the model only for judgment calls
**Health_Index 的偵測決策必須是確定性數學**（PCA / T² / SPE / DTW / Wasserstein），**禁止用 LLM 做飄移分類、routing、重試或確定性轉換**——code 能算的就用 code 算。LLM 僅用於文件草擬、摘要、文獻萃取等判斷性任務。

## Rule 6 — Token budgets（runtime N/A，重詮釋為運算成本上限）
本專案 runtime 無 LLM，原 4,000 token/task 約束不適用（依 Rule 7 明確標記此衝突並擇此解）。改採**線上運算成本上限**：Wasserstein O(N³logN)、DTW O(n²) 等重指標，線上路徑須用 Sakoe-Chiba band／降採樣／FastDTW 限縮；扛不住即時節拍者只走離線。指標超出目標節拍要 surface，不得默默拖慢。

## Rule 7 — Surface conflicts, don't average them
半導體 vs 化工慣例衝突（batch vs continuous、AVM vs soft sensor 術語、不同 MSPC 公式）時**擇一並說明理由**，另一個標記待清理。MSPC 公式分歧時優先採化工原生且更經驗證者（如 Nomikos & MacGregor），不混血兩種公式。

## Rule 8 — Read before you write
新增指標前先讀：`interface.py` 契約、adapter 輸出、golden-A baseline 定義、共用工具。**不臆測 TEP/penicillin 欄位語意**，對照資料集官方文件確認。不懂某結構為何這樣設計就問。

## Rule 9 — Tests verify intent, not just behavior
測試編碼 **WHY**：例如「純多變量飄移（每變數在規格內）被 T²/SPE 抓到、卻被逐變數管制圖漏掉」——這正是本 index 存在的理由。**當 index 停止偵測隱性飄移時仍會通過的測試是錯的。** 改 production code 前先補測試（紅→綠→重構）。

## Rule 10 — Checkpoint after every significant step
以里程碑 M0–M9 為 checkpoint，每階段總結「做了什麼／已驗證什麼／還剩什麼」。綠燈 commit 帶 `[verified]`。描述不出當前狀態就停下重述。

## Rule 11 — Match the codebase's conventions, even if you disagree
M0 定下的模組結構、numpy/scipy 慣用法、命名與 docstring 規範，後續一律沿用；文件 LaTeX 公式格式比照研究報告慣例。覺得某慣例有害就 surface，不要默默另立一套。

## Rule 12 — Fail loud
跳過任何步驟卻說「完成」是錯的；跳過任何測試卻說「測試通過」是錯的。**文獻一律以 `docs/literature_crossref.md` 為準，查不到就標 NOT FOUND，嚴禁捏造**。某指標在某資料形態跑不了（如 DTW 用在連續穩態）就明說，不造假。預設 surface 不確定性，不隱藏。

---

## 審核獨立性（Anti-self-certification）

凡屬「架構決策／schema 變更／對**自己產出**的審核／回填設計文件前」的**承載性結論**，**禁止以自審為終局**（自審有共同盲點＝球員兼裁判）：

1. 必須派**未接觸該推理過程**的獨立子代理紅隊（**≥2 視角**，如統計嚴謹度／產業落地／文獻誠信）對抗複審，明確指示「**重推、不信任既有結論、audit-the-audit**」。
2. 衝突**擇一說明、不平均**（Rule 7）；對帳產出「我漏的／我審錯的」清單。
3. 事實主張落地前須**確定性查證 primary source**；未查證標 **NOT VERIFIED**，嚴禁當已驗證引用（Rule 12）。
4. **觸發門檻**：高風險或不可逆決策、或對自身審核的再確認；trivial 任務豁免。
5. **機制**：`.claude/settings.json` 的 PreToolUse hook 在 `git commit` 時印出本規則提醒（確定性檢查點）。註：hook **無法驗證紅隊是否真的跑過**（需語意判斷），它只提醒；真正的獨立性靠「派獨立子代理」這個**結構**，不是靠自覺。
