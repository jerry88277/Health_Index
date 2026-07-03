# 紅隊驗證後問題總冊（演算法 + UX，已排除資安）

> 狀態（2026-07-03 註記）：本冊為 2026-06 複審之紅隊驗證存檔，逐筆 verdict 維持不動供備查。2026-07-02/03 專案已重定向（G1/G2/G3 三目標＋9 步新精靈為現行最優先；SMTP 串接與誤報/驗收指標暫緩；現行 5 步精靈將被取代），§(e) 修復順序不再是現行優先序——現行優先序見 docs/batch_avm_design.md §10 與 docs/devlog/2026-07-03.md。

> 本檔彙整三組紅隊獨立驗證（偵測器統計重推／驗收 gate 重推／邏輯正確性懷疑者／領班視角 UX）對 110 筆原複審結論的「重推、不信任既有結論、audit-the-audit」結果，外加驗證過程新發現 20 筆、看不懂概念盤點 25 筆。
> 統計口徑：每個 finding 以「不同 verifier 對同一主題的多筆 verdict」去重後計嚴重度。資安/RBAC/並發鎖等項目已標「PoC 後」並移出主修順序。

---

## 0. 統計總覽

| 類別 | 數量 |
|---|---|
| confirmed（含 partly_true/nuanced 但核心成立） | 99 |
| false_positive（核心被推翻或顯著誇大） | 11 |
| 確認 blocker（演算法/邏輯，排除資安） | 4 |
| 確認 major（演算法 + UX，排除資安） | 約 28（去重後主題約 18） |
| 看不懂概念盤點 | 25 |

> 註：原 110 筆含大量「同一根因被不同 verifier 各記一次」的重複（例如 close TypeError、(product,kind) 去重、評分窗長未進 bundle、品質事件借 X confidence 各被記 3–4 次）。下方依「主題」去重呈現，避免重複計數誤導修復排序。

---

## (a) 驗證確認的演算法 / 邏輯問題（附正確理解）

### A1. [BLOCKER] close() 對所有資料集事件拋 TypeError → 事件閉環根本無法閉合
- **位置**：`events.py:123`（`fromisoformat(closed_at) - fromisoformat(detected_at)`）、`demo.py:286`（detected_at=naive ts）、`demo_app.py:956`（`except Exception: return no_update` 吞例外）。
- **正確理解（比原清冊更嚴重）**：原清冊說「MTTR 算出荒謬巨大值（數年）」是**高估了健全度**。實測真相是 `detected_at` 來自資料集 ts（ccpp/tep/steel 皆 **naive** datetime），`closed_at=now().astimezone()` 是 **tz-aware**，naive 減 aware 在 CPython 直接 `raise TypeError`，被 UI 靜默吞掉。結果不是「算出大數字」，而是**關閉按鈕對所有真實資料集事件完全失效、事件永遠 active、MTTR 永不計算**。只有 ts 為 None 的 synthetic 路徑才關得掉。
- **修法**：`detected_at` 與 `closed_at` 統一時區語意（重放用模擬時鐘或對 detected_at 補同一 tz），或在 close 內把兩端正規化為同一 aware/naive。

### A2. [BLOCKER] 驗收建「前半 golden」臨時模型，部署「全 golden」模型 → FPR/recall 不可轉移
- **位置**：`acceptance.py:176-179`（Xfit=前半 golden、`build_bundle(...HealthIndex().fit(Xfit))`）vs `demo.py:182-183`（Xg=完整 golden、`HealthIndex().fit(Xg)`）。
- **正確理解**：`fit()` 從傳入 golden 推導 PCA basis、控制限、σ baseline、FWER split（`health.py:40-95`）。Xfit 的 n 約為 Xg 的一半 → 控制限/σ 估計更不穩、FWER 可能退回較不保守的 in-sample、PCA basis 不同。**簽核 PASS/FAIL 量的是「前半 golden 臨時模型」，不是實際上線的「全 golden 模型」**，統計效力不可轉移。此為真 blocker。
- **修法**：acceptance 對實際存檔 bundle 評 hold-out，或部署也只 fit 前段、後段純 hold-out（兩路徑同一 fit 集）。

### A3. [BLOCKER] 驗收 gate 完全不含 Y / 品質維度 → 含品質飄移的模型仍判 PASS 上線
- **位置**：`acceptance.py:179`（build_bundle 不傳 y_health）、`bundle.py:63`（y_health 預設 None）、`acceptance_report` 只用 poll_once 對 X 側評 FPR/recall。
- **正確理解**：驗收 bundle 永遠無 Y 健康，acceptance 完全不碰 Y。對含 Y 軟測量的 ccpp/steel 模型，PASS 不涵蓋任何品質維度，**含 Y 飄移仍 PASS**。前端驗收文案亦無 Y 維度標註。
- **修法**：acceptance 對 Y 維度（map_health / dist_health / Ŷ-drift）獨立評 FPR/recall 並納入 verdict；UI 揭露「此驗收是否涵蓋 Y」。

### A4. [BLOCKER] demo/registry 建模路徑永不建立 dist_health → 多維品質分布維度全程失效（假綠）
- **位置**：`demo.py:186-195`（只在 `Y_VALUE in fr.columns` 時 fit YHealthIndex，**Yq_golden 從未傳入**）、`y_health.py:53-58`（Yq_golden=None → y_mspc_=None）、`y_health.py:90-92`（y_mspc_=None → dist_health=None）。對照 `server.py:326-327` 有傳 Yqg。
- **正確理解**：經精靈/registry 建的**所有 demo 模型 dist_health 恆 None**。docstring 宣稱的「分布健康（換產品 G/H 比例變）」正交軸在 demo 完全失效，但前端 `demo_app.py:760/763` 仍以「品質維度」總稱呈現，使用者誤以為涵蓋分布漂移。「換產品比例變」正是 AVM 軟測量核心價值，假綠成立。
- **修法**：demo 建模路徑傳入 Yq_golden（或明確 UI 揭露 demo 不含 dist 維度，避免承諾不存在的能力）。

---

### A5. [MAJOR] 降採樣時相鄰窗間有未評分間隙 → 短事件漏報
- **位置**：`demo.py:247-254`（subsampled 時 `step=max(window, n//max_windows)>window`）、`demo_app.py:745`（前端只標「已降採樣為 N 窗」無漏報警示）。
- **正確理解**：相鄰窗 `[s,s+window)` 之間有 `step-window` 筆**完全未評分**，短於 step 的真實 drift episode 完全不被抽到 → 真漏報（非顯示問題）。正是本系統存在理由被靜默掏空。
- **修法**：降採樣時 UI 明確警示「窗間有間隙、短事件可能漏」，或對高維資料改用重疊抽樣保證覆蓋。

### A6. [MAJOR] 降採樣下 persistence_k 跨非相鄰窗計數 → consecutive 語義失真
- **位置**：`demo.py:252-254`、`runner.py:85-105`（cons 跨被抽樣窗累加，無真實時間間隔校正）、`demo.py:330`（n_alarms 計 persisted_alarm）。
- **正確理解**：兩個相隔 step（可達數百列）的被抽樣窗會被當「連續 2 窗」→ persistence 物理語義（濾單窗毛刺）在降採樣下破壞；n_alarms 在高維降採樣資料集上不可與低維資料集直接比較。
- **修法**：降採樣時標註 persistence 口徑已改變，或改用窗級獨立判決不跨窗累計。

### A7. [MAJOR] 監控特徵子集（10取7）丟掉帶訊號位號 → RBC 永遠指不到真因，下鑽不提醒盲區
- **位置**：`demo.py:245`（src 只用 bundle.x_columns）、`demo_app.py:845-863`（下鑽 RBC top5 只在子集內排序）。
- **正確理解**：若排除真因位號，RBC 排行永不出現它，工程師對著 RBC 首位永遠查不到根因且毫不知情。建模時 recall 警告只針對**已知** drift，對未來未知飄移無提醒。隱性飄移產品的核心盲區被靜默化。
- **修法**：下鑽卡/事件卡標「只監控 7/10 參數（X 未含）」，並對「排除參數=完全不看」於選擇當下提示。

### A8. [MAJOR] recall gate 統計功效極低（recall>0.5 武斷門檻 + 短段窗數少 + step=window 非重疊）
- **位置**：`acceptance.py:117`（`recall_ok = recall > 0.5`）、`acceptance.py:116`（窗級 Bernoulli 均值）、`runner.py:78`（`st=int(step or w)` 非重疊）、`AcceptanceReport`（無 `n_drift_windows` 欄）。
- **正確理解**：300 列、window=60 → 僅 5 窗，5 個 Bernoulli 均值在 p=0.5 時標準誤 ≈0.22，`recall>0.5` 判決近擲硬幣；且使用者無從判斷可靠度。
- **修法**：重疊窗增樣、回報窗數 + CI、門檻依風險上調，門檻提到 config 並在 verdict 顯示。

### A9. [MAJOR] recall gate 只警告不擋 → 特徵子集可丟掉帶訊號參數仍上線
- **位置**：`demo.py:636-637`（只 fpr_ok=False 才擋存檔，recall_ok 不在擋的條件內）、`demo_app.py:632-648`（recall_ok 警告但仍走存檔上線）。
- **正確理解**：允許上線一個對已知 drift 近全盲的模型，與 DoD 第 2/3 條（早於 SPC 抓隱性飄移）直接衝突。屬產品決策權衡，但風險揭露屬實。
- **修法**：將 recall_ok 納入硬擋（或高風險產線可設定），至少「上線需明確覆寫並留記錄」。

### A10. [MAJOR] FPR gate 可被「圈平穩段」放水（跨次重選 golden 的結構性 p-hacking）
- **位置**：`acceptance_from_dataset`（`acceptance.py:166-177`，同一段 golden 內時間連續 holdout split）、`demo_app.py:612`（FAIL 文案直接寫「請改選更平穩的黃金期…重建」=鼓勵重試）。
- **正確理解（修正原清冊）**：acceptance 內部用**時間連續 split**（非隨機），故 FPR 不是隨機 split 的樂觀偏誤，而是**「跨次重選 golden 段」的選擇偏誤**——無 attempt counter、無獨立第三段。選最平穩段使 σ 偏小、控制限更緊 → 對真實上線窗更易誤報。原清冊把兩種偏誤混述，真正可操弄點是跨次重試。
- **修法**：記錄重試次數、保留獨立第三段驗收、UI 明示 PASS 的保證範圍。

### A11. [MAJOR] 驗收 FPR(k=1) vs 線上 persistence_k=2 口徑脫鉤，且偏誤方向相反放大不對稱風險
- **位置**：`acceptance.py:80,91,102,114`（k=1, raw_alarm）vs `runner.py:79,91,100`（config k=2, persisted_alarm）。
- **正確理解**：驗收量單窗原始口徑——FPR 系統性**高估**（gate 偏嚴、可能誤擋）、recall 系統性**高估**（gate 偏鬆、放大「FPR 硬擋、recall 只警告」的不對稱）。`acceptance.py:91` docstring 自稱刻意設計，但未向簽核者揭露「此 FPR/recall 為單窗口徑、與線上 k=2 不可直接比較」。
- **修法**：verdict/UI 揭露口徑差異，或提供線上口徑（k=2）的對照數字。

### A12. [MAJOR] 軟測量 CP 採 in-sample 校準（fit 與 calibrate 同一份 golden）→ 覆蓋窄於名目
- **位置**：`y_health.py:51-52`（fit 後緊接 `calibrate_cp(X,y)` 用同一份 X,y）、`soft_sensor.py:80`（docstring 自承 X_cal 須與 fit X 不重疊）。
- **正確理解（修正原清冊）**：原「覆蓋保證形同虛設」略誇大——`y_health.py:52` 行內註解已誠實標「in-sample 校準（覆蓋為近似）」。真相是**窄於名目、近似而非保證**（GPR 過擬合壓小殘差 → cp_q_ 偏窄）。但 UI 圖例仍寫「conformal 帶」、`soft_sensor.py:108` docstring 仍寫「保證 ≥1−α」，過度信任風險真實。
- **修法**：UI/predict_interval docstring 同步標「近似覆蓋」；理想做法用 disjoint 校準集。

### A13. [MAJOR] Ŷ-drift z 用 golden Ŷ 的 σ 當門檻，GPR 外推回 prior mean → 遠離 golden 時 Ŷ 反趨中、z 縮小 → 隱性品質漏報
- **位置**：`demo.py:307-308`（`z=(wy_mean-gy_mu)/gy_sd`）、`soft_sensor.py:62-68`（GPR normalize_y → 域外回 prior mean ≈ gy_mu）。
- **正確理解**：X 大幅離域（最該擔心的 re-entry）時 Ŷ→gy_mu → z→0 → 過不了 `y_trend_z_max=3`，與直覺相反。GPR vs PLS（外推無界放大）對同一 z 門檻統計意義不一致。GPR 的 `return_std` 可得卻未用於 z 信賴加權。補強：此漏報只影響 Ŷ-level-drift 旗標，X 大離域時 X 側 L2/L4 仍會抓 → 非全盤漏，但 Y 維度該訊號確被壓低。
- **修法**：z 併入 GPR std 做信賴加權；或在 confidence 低（外推）時不以 z 縮小為「健康」憑據。

### A14. [MAJOR] 品質事件 confidence 直接借用 X 側 health confidence → severity 失真
- **位置**：`demo.py:297`（`confidence=bundle.health.confidence(Xw)`=X 側操作域 T²）、`demo_app.py:710-711`（quality 事件用該值）、`events.py:43-51`（severity_of 只吃 health/confidence）。
- **正確理解**：X 在域內（高 confidence）→ 品質事件不降級 → 即使 Y 觀測極稀疏不可信仍可判 critical；反之 X 外推又把可信品質告警壓成 warning。Y 維度缺自有可信度量（n_y_obs / cp_available 未進 severity）。
- **修法**：Y 側 severity 改用 n_quality_obs 與 ss_.cp_available 等 Y 自有可信度量。

### A15. [MAJOR] Ŷ 水準漂移在無實際 Y 觀測時仍獨立開 critical，magic number 9 無依據，且與 X 側雙重計數
- **位置**：`demo.py:308-319`（level_drift 只看 yhat_drift_z，無需實際 Y）、`demo_app.py:709`（`qh=1-min(|z|/9,1)`，9 無解析關聯）、`demo_app.py:704-711`。
- **正確理解**：無實際 Y（mh=None）時 health 由純 Ŷ-z 經 `/9.0` 映射（z=3→qh≈0.667、z=9→qh=0），9 為硬編 magic number 與門檻 3 脫鉤；Ŷ 由已漂移 X 外推 = 推論的推論，X 漂移已被 X 側 health 抓 → 雙重計數 + 警報疲勞。合流效應：可在零 Y 落地證據下灌出 critical 並污染 KPI。
- **修法**：Ŷ-only（mh is None）路徑強制降級為 info/warning 且不計入品質閉環 KPI，除非窗內 ≥y_map_min_obs 實際 Y；z→health 改用可解釋 z_ref 並併 GPR std。

### A16. [MAJOR] MTTR 混用樣本索引重放時間（detected_at）與真實牆鐘（closed_at）
- **位置**：`demo.py:286`（detected_at=資料集 ts）、`events.py:123`（直接相減）、各 adapter ts 為 `pd.date_range('2026-01-01')` 重放時鐘。
- **正確理解**：對「能成功關閉」的 synthetic 路徑，MTTR=now−replay_ts ≈ 數千小時的荒謬值，污染處長 KPI / 交接摘要 / ROI。（對真實資料集則因 A1 的 TypeError 根本關不掉，是 A1 的另一面。）
- **修法**：同 A1，統一時間軸語意。

### A17. [MAJOR] ROI「估省金額」由使用者自填假設驅動 + n_critical 含未關閉事件 → 可灌水
- **位置**：`roi.py:29-32`（`savings=n_critical×prevented_fraction(0.5 寫死)×avg_loss(自填,預設 1e6)`）、open 事件 `close_reason=None != 'false_alarm'` → 計入。
- **正確理解**：三個乘數無一實測；n_critical **含未關閉/未確認** critical 事件（誤報已排除）。結合 A1（事件關不掉），實務上幾乎所有 critical 都停在 open → ROI 完全由「未確認自動告警數 × 自填損失 × 0.5」堆出。UI 大綠字壓過免責小字。
- **修法**：n_critical 分母限定 `close_reason=='real'` 的已關閉真實處置事件；prevented_fraction 開放可調並標來源；金額去醒目綠或免責同等視覺權重。

### A18. [MAJOR] 事件 (product,kind) 鎖一個 active episode → 同製程後續飄移全併入第一案
- **位置**：`events.py:90-92`（命中既有 active 直接 return，不更新窗/肇因/health）。
- **正確理解（上調為 major）**：結合 A1（事件永遠關不掉），此去重把同製程整個生命週期的所有後續飄移**永久併入第一案**——不是偶發摺疊，而是系統性「一製程只會有一筆 process + 一筆 quality 事件」。對隱性飄移偵測產品 = 重複頻次統計歸零、稽核軌跡嚴重失真。
- **修法**：命中 active 時 append 新窗/肇因明細，或肇因顯著變化時升級/開子案。

### A19. [MAJOR] 事件 severity 自動定級不看 RBC 肇因/層一致性 → 停車優先序失真
- **位置**：`events.py:43-51`（只吃 health/confidence）、`demo.py:448-461`（verdict 已算 n_bad 卻沒寫進 incident）、`demo_app.py:701-702`。
- **正確理解**：一筆 L1+L2+L4 三層一致 vs 一筆 L2 單層邊緣，health 可能相近卻判同級，正是「該先停哪台」失準。
- **修法**：將 n_bad（層一致數）納入 severity 並於事件卡顯示「N 層一致」。

### A20. [MAJOR] 評分窗長從不存進 bundle → 建模/驗收/總覽燈/時效/下鑽用不同 window，治理不可轉移
- **位置**：`bundle.py:54-63`（ModelBundle 無 window 欄）、`demo.py:229`（score_timeline 預設 60）、前端各處吃 `State('window')`。
- **正確理解（重要修正原清冊因果鏈）**：「window 從不存進 bundle」為**真**，但原清冊把後果誇大為「SPE/T²/RBC/health 全不一致」**不精確**：
  - T²/SPE/GSI/RBC/confidence 控制限與 PCA basis 在 **fit 時凍結**，與評分窗長**無關**——換窗長不改每樣本的 SPE/T² 值或限。
  - `_severity_health` 採 per-sample 標準化後取窗均值，期望**設計上不受窗長影響**（`health.py:118-138` docstring），故 health_index 對窗長不敏感（僅變異受影響）。
  - **真正不可轉移的是**：事件窗 [start,end] 區段（去 historian 對照的時間段會錯）、acceptance 與線上不同窗的 FPR/recall 口徑、降採樣 step 行為。
- **嚴重度**：維持 major（治理可追溯性與事件時間對齊確有實害），**非「統計結論全面崩壞」的 blocker**。
- **修法**：將模型實際 fit 的 golden 範圍與評分窗長存入 bundle 作唯一基準；下鑽/匯出一律讀 bundle 的 window。

### A21. [MAJOR] clickData 下鑽：confidence 折線 trace 無 customdata → 點它走退路 `start=pointNumber*window`，降採樣時系統性錯位
- **位置**：`demo_app.py:660-662`（confidence trace 無 customdata）vs `655/663/666`（其他 trace 帶 start）、`demo_app.py:795-799`（cd=None 退路）、`demo.py:252-254`（降採樣 step≠window）。
- **正確理解（比原清冊更易觸發）**：confidence 點線**根本沒帶 customdata**，使用者點該虛線必走退路；降採樣時 `真實 start=pointNumber*step ≠ pointNumber*window` → 下鑽到錯誤窗的 GSI/T²/SPE/RBC。HI 主 trace 與告警 trace 有帶 start，點它們無誤。
- **修法**：所有可點 trace 末位統一帶 start；customdata 缺失時直接拒絕下鑽而非用脆弱退路。

### A22. [MAJOR] 時間線 x 軸對 synthetic 是樣本索引非時鐘，ts 為 str(ts) 無時區/格式保證 → 與 historian 對齊風險
- **位置**：`demo_app.py:654`（`xs=p.get('ts') or p['start']`，synthetic ts=None 退列索引）、`demo.py:286`（ts=str() 無時區）。
- **正確理解**：領班核心需求「這告警幾點發生、去 historian 拉同時刻趨勢」在 synthetic 上只有列索引、在有時戳資料上格式可能跟 DCS 差時區；夜班交接「幾點的事」卡死。與 A16 同根（混軸）。
- **修法**：統一時間戳格式與時區並存入 bundle；synthetic 明示為「相對重放時間」。

### A23. [MAJOR] _dl_timeline 匯出 CSV 用預設窗長 60，與顯示窗長可能不一致
- **位置**：`demo_app.py:967-975`（score_timeline 不傳 window → 落回 60，且重評一遍）。
- **正確理解**：建模用 window=120 時匯出窗界/health 與螢幕不符，且每次匯出重新評分（高維 L4 permutation 昂貴）。CSV 內每窗數值本身正確，只是窗切分口徑與畫面不同。會被拿去對 historian。
- **修法**：匯出讀畫面當前 window（或 bundle 的 window）；序列化已算好的 tl-store 而非重評。

---

## (b) 確認的 UX 情境問題（領班 / 工程師視角）

### U1. [MAJOR] 事件清單無法點回該窗下鑽 → 現場工程師拿不到肇因細節（閉環斷裂）
- `demo_app.py:901-927` 事件卡只有 ACK/note/reason/關閉，`Incident.window=[start,end]`（events.py:28）UI 完全未用。要看 RBC/各層 p-value 只能回精靈重建同模型肉眼找紅點，且窗長可能對不上（見 A20）。
- **修法**：事件卡加「查看該窗」連結帶 window 直接下鑽。

### U2. [MAJOR] _run 進結果頁即自動開事件（CQS 違反：讀路徑帶持久化副作用）
- `demo_app.py:678-711` 是渲染 callback 卻呼 `open_incident` 寫 incidents.json。
- **正確理解（修正原清冊）**：「開案時間=點進結果頁的時間」**錯**——detected_at 傳 `worst.get('ts')`（最嚴重窗的資料窗時刻），非 now()。又因 (product,kind) 去重，一個 active episode 內不會反覆開新案。CQS 違反屬實、時間歸因子主張假。
- **修法**：把開案移出渲染路徑（明確動作或背景 job），結果頁讀路徑純呈現。

### U3. [MAJOR] 結果頁無 historian 趨勢：只有窗級彙總，看不到單一位號原始時序
- `demo_app.py:308-313` 只有 timeline(health) 與 ymap，window_detail 只回 RBC 排行與均值。RBC 指向 TIC-205 後必須離開系統去 DCS 確認真漂 vs spike。
- **修法**：下鑽提供告警窗前後的位號原始 trend。

### U4. [MAJOR] 事件清單只能依狀態篩選，無法依製程/嚴重度/時間/肇因篩選或排序
- `demo_app.py:338-345` evt-filter 只 all/open/ack/closed；`events.py:127-134` list 固定時間排序。領班「只看自己那條塔、最近、critical」做不到。
- **修法**：加 product/severity/kind/時間多維篩選與排序。

### U5. [MAJOR] 健康燈「灰」混入「不可得」與「待建模」兩語意，data_unavailable 不進全廠燈 → 監控盲區
- **正確理解（修正原清冊）**：卡片層級**有**區分兩種灰（`_STATUS` 棕「待建模」vs 灰「資料源不可得」），原「視覺塌縮」對卡片誇大。**真正問題在 banner/分母**：`plant_status` 只看 n_alarm，data_unavailable 不算 alarm 也不算 healthy → 一條資料源掉線的現役製程不會讓全廠燈變色。
- **修法**：data_unavailable 觸發全廠燈異色（或獨立第三態），banner 拆分計數。

### U6. [MAJOR] 刪除製程一鍵無二次確認，誤點即軟刪整製程並強關事件 → 汙染 MTTR/ROI
- `demo_app.py:155-156`（刪除緊鄰歷史，同色同尺寸）、`demo_app.py:1005-1016`（無 ConfirmDialog）。被強關事件不會因還原自動重開。
- **修法**：二次確認 + 刪後 toast「可到歷史還原」+ 刪除移出常用按鈕列。（純 UX 誤觸面，非權限）

### U7. [MAJOR] 精靈第②關 golden 選擇圖 Y 軸「標準化偏離度 (σ)」對領班不可解 → 不知該圈哪段
- `demo_app.py:262-264,517-532`。選黃金基準是整個精靈最關鍵一步（直接決定模型好壞），卻用統計語言的軸。
- **修法**：提供白話「這段最穩定，建議當基準」自動標註，或用實際製程量（溫度/流量）認段。

### U8. [MAJOR] 精靈第③關只給「評分窗長」一個數字、預設 60，領班不知是什麼也不知該填多少
- `demo_app.py:266-272`。catalog 有 default_window 自動帶入但 UI 沒說「已依資料源推薦、通常不用改」。
- **修法**：窗長旁加白話「一次看幾筆資料判一次健康；已依資料源推薦 N，多數情況不用改」+ 過小窗友善警示。

### U9. [MAJOR] lifecycle.assess_model_currency / rebuild_model 完全未接到任何 UI
- grep `demo_app.py` 無 currency/assess_model/lifecycle 呼叫。
- **正確理解（修正原清冊 blocker→major）**：功能缺席屬實，但對只看紅綠燈的領班日常**非阻斷**；blocker 應保留給「看不懂/做不了當下決策」的問題。
- **修法**：歷史頁加「時效評估」入口，餵近期確認正常的 A 段檢查基準老化。

### 其餘確認 minor（UX，擇要）
- 角色切換只影響下鑽卡，事件頁/ROI/總覽不隨角色變（作業員仍見處長 KPI）—`demo_app.py:86-89,786`。
- 門檻 slider what-if 不接線（拉了告警不動）造成認知摩擦—`demo_app.py:301-307,776-783`。
- RBC 排行對非告警窗也照算 → 點綠窗看到肇因排名誤讀。
- incident id 用 max+1（刪最大號後重用，純演算法缺陷）—`events.py:76-78`。
- banner 三數 alarm⊂monitored 未明示、placeholder 計數混合。
- 結果頁 60s tick 不重評時間線（盤面悄悄過時）；無「快照時間」標示。
- 換版後無 rollback/「設為現役」UI 入口；更換模型無新舊版本對比；無模型年齡指標。
- 精靈第①關標題「選資料源」卻夾特徵子集勾選，少選參數要到第④關才被擋（驗證點延後）。
- 品質事件 top_cause 固定模板字串，無具體品質變數定位。
- 事件 severity 門檻寫死 0.6/0.45，不可依產線風險調整。

---

## (c) 看不懂的概念完整對照表（術語 / 在哪 / 白話 / 直覺度 / 改法）

> 直覺度 1=最難懂、5=直覺。依直覺度由低到高排序。

| # | 術語 | 在哪 | 白話 | 直覺度 | 改法（摘要） |
|---|---|---|---|---|---|
| 1 | **T² / SPE / GSI** | 工程師下鑽、hover、ymap 子圖標題 | T²=離正常中心多遠；SPE=參數「之間關係」偏多少（隱性飄移主訊號）；GSI=整體相似度。越大越異常 | 1 | 各加極短副標/tooltip；「限」→「管制限」、「越限X%」→「有X%點超管制限」；預設只顯 SPE+T²，GSI 收進階 |
| 2 | **指紋健康度 (fingerprint_hi)** | 建模成功訊息 0.xxx | 模型剛建好拿黃金基準自回測的分數，當基準指紋（應接近1） | 1 | 改「模型自我健康基準 X（接近1表基準乾淨）」或直接拿掉（無行動價值） |
| 3 | **健康度 subscores (dict)** | 工程師下鑽直接印 Python dict | 健康指標由 L1/L2/L4 三層子分數加權合成，這裡裸印字典 | 1 | 改具名三欄「資料效度0.9｜多變量關係0.4｜分佈飄移0.8（合成→總健康度）」，不裸印 dict |
| 4 | **各層 p-value / Holm / FWER** | 工程師表格欄、結果頁說明 | 每層算一個 p-value（無問題前提下看到此異常的機率，越小越可能真異常），多層用 Holm/FWER 校正避免假警報 | 1 | 表頭 tooltip「越小越可能真異常（<0.05顯著）」；「—」=此層未觸發/不適用；告警旁標「已做多重比較校正」 |
| 5 | **評分窗長 (window)** | 精靈第③步 | 把連續資料切成每 N 列一段，逐段算健康分；決定時間解析度 | 2 | 標籤改「每段分析多少筆資料（時間窗長）」+一行「越大越平穩但反應慢、越小越靈敏但易雜訊；約≈N×取樣週期」+標建議值 |
| 6 | **可信度 (confidence)** | 圖例虛線、下鑽「操作域T²」 | 不是「健不健康」，是「這次判讀本身可不可信」——操作點在建模看過範圍內=可信(高)，跑到沒見過的區=外推(低) | 2 | 全程改「判讀可信度」+固定白話「高=系統熟悉、告警可信；低=操作跑到沒看過的區，先當參考」；移除工程師裸詞「操作域T²」改 tooltip |
| 7 | **RBC 肇因排行** | 工程師下鑽 top5、事件卡「肇因」 | 告警後告訴你最可能是哪幾支表造成異常，按貢獻排序給維修查修 | 2 | 工程師視圖「RBC」→「最可能肇因參數（貢獻排行）」，縮寫降 tooltip；括號數字標「相對貢獻度（越大越可能）」 |
| 8 | **事故 recall / drift_recall** | 建模 build-result、驗收快照 | 在「已知有飄移」測試資料上抓到了百分之幾，越高偵測力越強；偏低多因勾的監控參數排除了帶訊號的表 | 2 | 改「已知飄移偵測率/抓到率」；數值旁標「（越高越好，<0.5偏弱）」；recall 縮寫降 tooltip |
| 9 | **Ŷ / 軟測量 / conformal 帶 / X→Y 可信度** | ymap 子圖、下鑽 | 用便宜製程量推估貴慢的化驗值（Ŷ），conformal 帶=有覆蓋率保證的誤差帶，X→Y 可信度=製程↔品質對應還成不成立 | 2 | Ŷ 旁標「（推估品質值）」；conformal→「可信誤差帶(90%覆蓋)」；**「X→Y 可信度」改名避免與判讀可信度撞名**（如「製程→品質關係健康度」） |
| 10 | **品質飄移 / X→Y 殘差超界 / Ŷ 水準偏移** | 結果頁③、事件卡 kind | Y側問題兩種：①殘差超界=製程正常但實際品質對不上；②Ŷ水準偏移=推估品質整體搬家。都恐量產次級品 | 2 | ③標題加「品質維度=直接盯化驗品質（前面盯製程參數）」；「殘差超界」→「製程正常但實際品質對不上」、「Ŷ水準偏移」→「推估品質整體偏移」 |
| 11 | **severity (critical/warning/info)** | 事件卡直接顯英文 | 嚴重等級決定先處理誰，依健康度與可信度自動定級 | 2 | 中文化「嚴重/警示/參考」+配色；卡片加「（依健康度與判讀可信度自動定級）」；採 A19 把層一致數納入 |
| 12 | **MTTR** | 交接摘要、KPI tile、事件卡 | 平均處理時間（偵測→關閉的小時數），越短反應越快 | 2 | 首次出現展開「平均處理時間 MTTR（偵測→關閉，小時）」 |
| 13 | **監控特徵子集（10取7）** | 精靈第①步 | 從所有感測器勾要監控的幾個，不勾完全不看，至少2個（要看參數「之間」關係） | 4 | 「至少2個」後加原因；勾選區灰字「排除某參數=完全不看；若它正是會飄的關鍵表，可能漏報」 |
| 14 | **golden / 黃金基準** | 精靈第②步 | 挑一段你認定健康正常的歷史，系統學正常長相，挑不乾淨後面整個判斷會歪 | 3 | 標題下加後果提示；英文 golden 收斂為「黃金基準段」單一稱呼 |
| 15 | **連續區間/勾選campaign/自動挑（三模式）** | 精靈第②步 | 三種挑黃金段法：拉連續範圍／從批段勾幾段（可不連續）／系統自動挑最乾淨 | 2 | campaign 中文化「運轉週期/批段」；每個 radio 加情境 helper |
| 16 | **health index 健康度(0–1)** | 結果頁、時間線y軸、卡片 | 多層收斂成0–1綜合分，1=最健康，低於門檻告警 | 4 | y軸/卡片補錨點「1=和黃金基準一樣健康，門檻0.6以下=該查看」；0.6 標「告警線」 |
| 17 | **persistence_k / 持續告警** | 不顯式（行為呈現於紅✕與自動開案） | 防誤報：連續好幾窗都低才算真告警才開事件（類SPC連續N點） | 3 | 結果頁/事件頁加「需連續N窗低於門檻才視為持續告警」並顯示目前N |
| 18 | **誤報率 FPR / hold-out golden / 驗收verdict** | 建模第④步 | 在「本該全綠的健康資料」上試跑看誤報幾%，太高=太敏感，直接擋上線 | 3 | 「hold-out golden 誤報率」→「在一段健康資料上的誤報率」；寫出目標值；擋存檔訊息補白話 |
| 19 | **region（黃金/乾淨回歸/殘留飄移/換產品）** | 時間線顏色、hover | 標每點屬哪種時期；殘留飄移=A回來但仍帶偏移（最該抓）；換產品=非A | 3 | 加四色小圖例，標「殘留飄移=回頭跑A仍帶偏移，重點警戒」 |
| 20 | **標準化偏離度(σ)** | golden 預覽圖 y 軸 | 每點離全域平均幾個σ，純看資料長相找平穩段用，不是健康判斷 | 3 | y軸補「（標準差倍數，僅輔助挑段）」+「此圖不參與健康評分」 |
| 21 | **告警門檻試算 slider (what-if)** | 結果頁 | 拖滑桿試看門檻設某值會有幾窗告警，純預覽不改實際告警 | 3 | label 警語前置「（僅預覽，不改實際告警）」+方向提示「門檻越高越敏感」；長期加「套用此門檻」鈕 |
| 22 | **ROI 效益估算 / 避免比例 / 假設損失** | 事件頁 roi_card | 情境試算：假設每嚴重事件避免一定比例停車×每次損失=估省金額，是假設非實測 | 3 | ROI 展開；免責與金額同等視覺權重；避免比例標「（保守假設值，可調）」；作業員角色隱藏整卡 |
| 23 | **處置 reason（真實處置/誤報/已知忽略）** | 事件關閉 Dropdown | 關事件時標性質，回饋誤報統計 | 4 | 「已知忽略」加 tooltip「已知非異常、不計入誤報」與「誤報」區分 |
| 24 | **資料源狀態（待建模/資料源不可得）** | 總覽卡三態 | 待建模=已佔名未建監控；資料源不可得=綁的資料源拿不到資料 | 4 | 「待建模」hover 補「尚未設定健康監控基準」；「資料源不可得」補「請檢查連線後重建」 |
| 25 | **作業員/工程師 角色切換** | 頁首 RadioItems | 切換顯示詳略，作業員藏術語、工程師給完整指標 | 4 | 擴大角色作用範圍（作業員隱藏 ROI/統計KPI），或標「主要影響告警明細詳略」 |

---

## (d) 被推翻 / 顯著誇大的 false_positive（為何不成立）

1. **「評分窗長變→SPE/T²/RBC/health 全不一致」**：因果鏈過度。控制限與 PCA basis 在 fit 時凍結，與評分窗長解耦；health 經 per-sample 標準化後取窗均值，期望不受窗長影響。真正受影響的只有窗均值/邊界/persistence/事件區段。→ 改記為 A20（major，限「事件時間對齊與口徑」）。

2. **「軟測量 CP 覆蓋保證形同虛設」**：略誇大。`y_health.py:52` 已誠實標 in-sample 近似。真相是「窄於名目、近似而非保證」，問題在 UI/docstring 未同步。→ A12。

3. **「事件開案時間=某人最後一次點進結果頁的時間」**：錯。detected_at 傳 `worst.get('ts')`（資料窗時刻），非 now()/點擊時間；且 (product,kind) 去重，一個 active episode 內不反覆開案。CQS 違反本體仍真。→ U2。

4. **「健康燈灰被當中性灰、視覺塌縮」（對卡片）**：對卡片誇大——卡片層級已用棕/灰文字區分「待建模」vs「資料源不可得」。真正問題在 banner 計數合併 + 全廠燈不變色。→ U5（降為「banner 層問題」）。

5. **「clickData 退路屬常態 major」（領班視角複審）**：所有可點 trace（主曲線/告警）都附 customdata，退路只在點 confidence 虛線時觸發 → 常態路徑不踩。但 confidence trace 確實無 customdata 是真漏洞。→ A21（核心保留，常態誤觸機率低）。

6. **「驗收 _resolve_golden config 不一致即靜默破壞」**：過度泛化。config 依賴只在 `golden='auto'`（變點切段）或比例路徑才有；(start,end)/bool mask/segments mask 路徑不碰 config，無此風險。→ 降為 minor 且限定觸發條件。

7. **「太小窗即建出無功效模型／n<p 退化」**：混談兩件事。MSPCModel.fit 的 PCA 在 golden 全段 fit，**小窗不影響模型 fit 品質**，只影響評分時每窗的統計功效；「n<p 退化」是 golden 樣本數 vs p，與評分窗長無關。→ minor，且「window<2p 即無功效」的精確門檻未經逐行確認，屬合理推論非定論。

8. **「currency/recall/FPR 三套門檻可同時為真卻矛盾」**：部分屬刻意設計分工——acceptance 故意用 persistence_k=1 量原始窗 FPR、線上用 k=2 濾毛刺。不是 bug 是口徑分工，但缺文件對齊。alarm_rate_max=0.3 vs 0.05 的 6× gap 才是真治理空洞。→ A11 + minor 文件化。

9. **「dist_health 飽和度量」為當前 demo 實害**：受 A4 牽連——dist_health 在 demo 路徑恆 None、不會被觸發，屬休眠瑕疵（只在 server.py 路徑或未來接 Yq 後生效）。→ minor 且註明休眠。

10. **「lifecycle 未接 UI 是 blocker」**：對只看紅綠燈的領班日常非阻斷，降為 major（U9）。

11. **「進結果頁 current_model=None 常見靜默失敗」**：略誇大。「查看結果」按鈕只在 healthy/alarm 卡出現（必有 current_model），None 只在刪除競態短窗發生。→ minor（罕見路徑）。

---

## (e) 建議修復順序（2026-06 快照；部分已被 2026-07 重定向取代，見檔頭狀態註記）

### 第一波：演算法/邏輯 blocker（產品核心價值與簽核效力直接受損）
1. **A1** close() naive vs aware TypeError → 事件閉環全失效（連帶解 A16/A18 的疊加放大）。
2. **A4** demo 路徑傳入 Yq_golden（或誠實揭露不含 dist 維度）→ 修「品質假綠」。
3. **A2** 驗收與部署同一 fit 集（前半/全 golden 統一）→ 恢復簽核統計效力。
4. **A3** 驗收 gate 納入 Y/品質維度 → 含品質飄移不再 PASS。

### 第二波：演算法 major（偵測力與口徑可信度）
5. **A7** 監控特徵子集盲區下鑽提示 + **A5/A6** 降採樣漏報/persistence 失真警示。
6. **A8/A9/A11** recall gate 統計功效 + 硬擋選項 + FPR/recall 口徑揭露。
7. **A13/A14/A15** Y 維度：Ŷ 外推漏報、品質事件 confidence 借錯、magic 9 / 雙重計數。
8. **A10** FPR p-hacking（attempt counter + 獨立第三段）。
9. **A20/A21/A22/A23** 評分窗長與時間戳存入 bundle、下鑽 customdata 統一、匯出口徑一致。
10. **A17** ROI 分母限已關閉真實處置 + prevented_fraction 可調揭露。
11. **A18/A19** 事件去重 append 明細 + severity 納入層一致數。

### 第三波：UX 情境（領班/工程師可用性）
12. **U1** 事件→該窗下鑽連結（閉環）；**U3** 下鑽位號原始 trend。
13. **U7/U8** 精靈 golden 選段白話化 + 窗長白話說明。（註：現行 5 步精靈將由 9 步新精靈取代；U7「不知該圈哪段」的解法已由新精靈 Golden 兩關卡「看圖選，不盲挑」設計吸收——多批疊圖 trim＋批次勾選＋[param×stat] run 圖，見 docs/batch_avm_design.md §3）
14. **U5** banner data_unavailable 觸發異色；**U2** 開案移出渲染路徑。
15. **U4** 事件多維篩選排序；**U6** 刪除二次確認；**U9** 時效評估 UI 入口。
16. **看不懂概念 top 8**（見下節）批次術語改寫，配合各功能頁同步落地。

### 第四波：minor 治理一致性與文件化
17. 門檻 slider 接線/「套用」鈕、角色切換擴大作用範圍、incident id 改單調計數器、各門檻口徑文件化、模型年齡/版本對比/rollback UI。

### 標「PoC 後」（資安/RBAC/並發，本任務排除）
- incidents.json 非原子寫、DoS 放大器、event ack/close 無權限檢查與狀態前置、刪除軟刪權限——**PoC 驗證演算法價值後再處理**。

---

## 看不懂概念 top 8（最該先解釋/改，依直覺度由低到高）

1. T² / SPE / GSI（1）
2. 指紋健康度 fingerprint_hi（1）
3. 健康度 subscores 裸印 dict（1）
4. 各層 p-value / Holm / FWER（1）
5. 評分窗長 window（2）
6. 可信度 confidence（2，且與「X→Y 可信度」撞名是最大混淆源）
7. RBC 肇因排行（2）
8. Ŷ / conformal 帶 / X→Y 可信度（2，撞名 + 行話堆疊）

> 這 8 個是「懂製程不懂統計」的工程師與領班最直接的攔路虎；其中 confidence 與 X→Y 可信度**撞名**、subscores **裸印 dict**、fingerprint_hi **無行動價值卻硬塞數字**三者投報率最高（純文案/呈現改動、零演算法風險）。
