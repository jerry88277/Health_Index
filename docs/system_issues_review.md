# 系統問題完整清冊 — 2026-06-22 增量7–9 多角色複審

> 背景：本清冊彙整 2026-06-22「增量7（Y 側品質飄移預警）、增量8、增量9（監控特徵子集選擇）」三批變更上線後，由 12 個複審視角（10 個使用情境角色：凌晨夜班作業員、現場工程師、生產製程工程師、生產處長、品保/QA、維修/可靠度工程師、資安/IT、軟體可靠度、新手使用者、統計嚴謹度；外加 2 個 critic：系統性/架構債、無人查的面向）獨立提出的 204 筆問題。本清冊只合併「同一技術根因、不同角色重複提出」的條目（保留最完整描述並標註所有提出角色），**不過濾小問題或不確定問題**。依 area 分節、severity（blocker > major > minor）排序。
>
> 唯一真相提醒：本清冊為複審輸出，承載性結論（如『應加 SSO 才能上線』）仍需獨立查證 primary source 與紅隊對抗，未在此終局背書。
> → 紅隊對抗複審已完成：逐筆 verdict（99 confirmed / 11 false_positive，含多筆嚴重度與因果鏈修正——如 window-未存-bundle 之後果被縮限、MTTR「荒謬巨大值」實為 close() TypeError 全面失效、lifecycle 未接 UI 降 blocker→major、灰燈「視覺塌縮」限縮為 banner 層、開案時間歸因被推翻）見 docs/redteam_verified_issues.md；與本冊衝突時以該冊為準。

---

## 1. 模型時效 / 生命週期（lifecycle currency）

### [blocker] lifecycle.assess_model_currency / rebuild_model 完全未接到任何 UI（最高頻重複，7+ 角色）
- **情境**：維修停機後 A 回頭跑、換產品回歸 A、模型上線數月後，使用者想用一段「現場確認為正常的近期 A」餵進現役模型，確認基準是否老化、要不要重建——但 UI 沒有任何入口。
- **影響**：lifecycle.py 是後端唯一能回答「基準是否老化、要不要重建」的能力，整支（assess_model_currency / CurrencyReport / rebuild_model / ModelRegistry / check_threshold_portability）全前端 grep 0 命中＝死碼。維修 re-entry 的核心判斷在 UI 根本做不到；AVM 核心的「基準老化偵測」在產品面缺席；老化 vs 真飄移無系統輔助，可能反覆假告警或把真飄移當老化重建把問題藏起來。design guide §7 自承「生命週期 UI 接線」P1 未補。
- **evidence**：`src/health_index/deploy/lifecycle.py:64-133`（assess_model_currency / CurrencyReport / rebuild_model，frontend grep currency|lifecycle|assess_model 0 命中）；`frontend/demo_app.py:1041-1047`（歷史頁只列 acceptance 快照）；`docs/frontend_design_guide.md:71,103,116,129`
- **建議**：歷史頁/總覽加「時效評估」面板：圈選近期確認-正常段→呼叫 assess_model_currency→顯示 CURRENT/REBUILD_RECOMMENDED 與 alarm_rate；REBUILD_RECOMMENDED 顯著提示。
- **提出角色**：現場作業員、現場工程師、生產製程工程師、生產處長、品保/QA、維修/可靠度工程師、軟體可靠度

### [major] UI 沒有任何模型「年齡 / 上次建模距今」指標
- **情境**：巡檢全廠想一眼看出哪些製程基準很久沒重建、最可能老化。
- **影響**：created_at 只在歷史頁版本表顯示，總覽 _asset_card 與 assets_overview 完全不帶建模時間或「距今幾天」，無老化提醒徽章；必須逐一點進歷史頁，巡檢效率與遺漏風險都差。
- **evidence**：`frontend/demo_app.py:1047`（唯一 created_at）；`frontend/demo_app.py:140-167`（_asset_card 無時間欄）；`src/health_index/deploy/demo.py:685-719`（assets_overview 回傳無 created_at/age）
- **建議**：assets_overview 帶回 current_model.created_at，_asset_card 顯「建模於 YYYY-MM-DD（N 天前）」，逾門檻加黃旗。
- **提出角色**：維修/可靠度工程師

### [major] currency alarm_rate_max=0.3 與驗收 target_fpr=0.05、線上 persistence_k=2 三套門檻互打架
- **情境**：用近期確認-正常段做時效評估得 alarm_rate 0.2→CURRENT，但同段上線驗收用 0.05 FPR 會 FAIL；剛上線 PASS（≤0.05）的模型要等告警率漲 6 倍到 0.3 才被建議重建，中間 0.05–0.3 是治理盲區。
- **影響**：「基準還適用嗎」「能上線嗎」「線上有無告警」三句可同時為真卻互相矛盾；0.3 寬鬆門檻可能把已老化基準誤判 CURRENT。assess_model_currency 用 persistence_k=1（原始單窗），線上走 config k=2（濾單窗），口徑再差一層。
- **evidence**：`src/health_index/deploy/lifecycle.py:69,93,99`（alarm_rate_max=0.3, persistence_k=1）；`src/health_index/deploy/acceptance.py:74,80,102`（target_fpr=0.05, k=1）；`src/health_index/config.py:76`（drift_persistence_k=2）；`src/health_index/deploy/runner.py:79`
- **建議**：三處統一到同一 (persistence_k, 告警率門檻) 口徑，或明文定義各自為何不同並在報告對齊。
- **提出角色**：維修/可靠度工程師、系統性/架構債 critic、資料科學家／統計嚴謹度

### [major] 模型沒有任何到期 / 重新驗收提醒機制（時效是一次性而非持續）
- **情境**：模型上線三個月，想知道系統有沒有定期提醒「該重新評估基準時效」。
- **影響**：acceptance 只在建模當下跑一次存快照，之後無任何排程/到期重評；CurrencyReport 是被動函式無人週期呼叫；runner 只評分不做時效檢查。老化是漸進的，一次性驗收抓不到，缺「模型健康度監控的監控」。
- **evidence**：`src/health_index/deploy/demo.py:631-642`（acceptance 一次性快照）；`src/health_index/deploy/runner.py`（無時效檢查）；無任何排程呼叫 assess_model_currency
- **建議**：依 created_at + 門檻天數在總覽標「建議重新評估時效」；或提供批次 currency 重評入口。
- **提出角色**：維修/可靠度工程師

### [major] 重建 / 更換模型沒有任何「與舊版基準比較」呈現
- **情境**：懷疑基準老化要重建，重建前後想看新舊 golden 差多少，避免把真飄移當老化、把問題基準化。
- **影響**：lifecycle 自己強調「重建無法自動區分老化 vs 真飄移，須人決」，但 build_model_for_process 更換時只跑驗收 gate，完全沒把新 golden 與現役 golden 做分佈比較（drift.py 已有 Wasserstein/KL 能力）；歷史頁版本表只列 golden_range 字串。等於閉著眼覆蓋舊基準。
- **evidence**：`src/health_index/deploy/demo.py:616-645`（無新舊比較）；`frontend/demo_app.py:1046`（版本表僅列 range）；`src/health_index/deploy/lifecycle.py:8-10`
- **建議**：重建前置「新 golden vs 現役 golden 分佈距離」報告（重用 drift.py），距離過大時警告「可能是真飄移而非老化」。
- **提出角色**：維修/可靠度工程師

### [minor] currency 評估用 persistence_k=1 但線上走 persistence_k>1，口徑不一致
- **情境**：用時效評估判老化，結果與結果頁實際告警窗數對不起來。
- **影響**：assess_model_currency 內 poll_once 寫死 persistence_k=1 量單窗 raw_alarm_rate，線上 score_timeline/runner 用 config.drift_persistence_k 做持續性過濾；時效評估可能因單窗毛刺高估 alarm_rate→誤建議重建。
- **evidence**：`src/health_index/deploy/lifecycle.py:93`；`src/health_index/deploy/runner.py:79`
- **建議**：report 註明「此為單窗原始告警率，與線上 persisted 告警口徑不同」，或提供兩種數字。
- **提出角色**：維修/可靠度工程師、資料科學家／統計嚴謹度

### [minor] rebuild_model 不接 incident_store，重建後舊基準的未結告警不會被解除
- **情境**：基準老化用 rebuild_model 重建，原本針對舊基準開的告警應隨基準更新而檢視。
- **影響**：soft_delete_process 會傳 incident_store 強關孤兒事件，但 rebuild_model 與 build_model_for_process 更換模型都不碰 incident；重建後 open/ack 事件仍掛著，未結事件數/MTTR 失真。
- **evidence**：`src/health_index/deploy/lifecycle.py:109-133`；`src/health_index/deploy/demo.py:616-645`
- **建議**：更換/重建時提示「是否關閉舊基準下的未結事件並註記 reason=baseline_rebuilt」。
- **提出角色**：維修/可靠度工程師

### [minor] data_unavailable 製程的「重建模型」按鈕仍引導建模，但根因可能是資料源不可得
- **情境**：某製程因資料源指紋漂移/檔損標成「資料源不可得」，點卡上「重建模型」想處理。
- **影響**：data_unavailable 根因可能是資料源載不進來（_score_current except 吞所有例外），走建模精靈會在 preview 階段再炸一次；按鈕文案「重建」暗示問題在模型，實際可能是資料源接口壞了。
- **evidence**：`frontend/demo_app.py:153-154`；`src/health_index/deploy/demo.py:672-682`
- **建議**：data_unavailable 卡顯示診斷原因（檔損/指紋漂移/資料源缺）並給對應動作，而非一律「重建模型」。
- **提出角色**：維修/可靠度工程師

---

## 2. 評分窗長 / bundle 單一真相（window 未持久化）

### [blocker] 評分窗長從不存進 bundle：建模/驗收/總覽燈/時效用不同 window，治理結論不可轉移（多角色重複）
- **情境**：工程師以 window=120（或 catalog 推薦 ccpp 48 / steel 96）建模並驗收上線，回總覽從卡片「查看結果」直接進結果頁（未走精靈），時間線/最嚴重窗事件/RBC 下鑽全部用殘留的 State('window')（預設 60）重算。
- **影響**：bundle/model record 都沒存 window；score_timeline / acceptance / monitoring_overview / _score_current / assets_overview / plant_overview / assess_model_currency 各處 window 預設 60。同一模型在四個地方用兩三種窗長，窗邊界、SPE/T²/RBC 肇因、health、acceptance 口徑全不一致；事件開案窗也錯，現場去 historian 對照的時間區段是錯的；處長看到的綠燈與簽核時驗的不是同一量測口徑。
- **evidence**：`src/health_index/deploy/bundle.py:38-63`（無 window 欄）；`frontend/demo_app.py:677,686,787,795,800`（吃 State window）；`src/health_index/deploy/demo.py:229,465,490,543,672,685`（散落預設 60）；`src/health_index/deploy/lifecycle.py:69,91`；catalog default_window 48/96；build_model_for_process / build_and_save_model 未存 window
- **建議**：把 window 凍進 bundle（與 golden 一樣是模型不可變屬性），所有 score/overview/currency/window_detail 一律讀 bundle.window，UI State 只在精靈內用，移除散落的 60 預設。
- **提出角色**：現場工程師、生產製程工程師、軟體可靠度、系統性/架構債 critic

### [major] _dl_timeline 匯出時間線 CSV 用預設窗長 60，與顯示時間線可能不一致
- **情境**：用 window=120 建模並查看結果，再按「匯出時間線 CSV」。
- **影響**：_dl_timeline 呼 score_timeline 不傳 window→落回預設 60，窗界/health/region 與螢幕不符；且每次匯出重新評分一遍（高維昂貴）；CSV 也不含 RBC 肇因/位號欄。
- **evidence**：`frontend/demo_app.py:967-975`（不傳 window）；`src/health_index/deploy/demo.py:592-604`
- **建議**：匯出改直接序列化 tl-store（畫面那份 points）不重評；或統一傳建模窗長並補 top_cause/位號欄。
- **提出角色**：現場工程師、軟體可靠度、新手使用者、無人查的面向 critic

### [major] clickData 下鑽在降採樣（step≠window）時退路會算出錯誤窗 start
- **情境**：高維/長資料集觸發 subsampled（step 加大），點時間線某點下鑽且 customdata 缺失走退路。
- **影響**：退路 `start = pointNumber * w` 假設窗非重疊且 step==window，subsampled 時 step≠window，系統性錯位→下鑽到錯誤窗的 GSI/T²/SPE/RBC，工程師被導向錯誤肇因。
- **evidence**：`frontend/demo_app.py:795-800`；`src/health_index/deploy/demo.py:252-254`
- **建議**：退路乘 step 不是 window；或 subsampled 時禁用退路（強制要求 customdata），統一所有 trace customdata 末位皆為 start。
- **提出角色**：生產製程工程師、軟體可靠度

### [minor] 從總覽卡進結果再回，State(window) 殘留上次精靈值，跨製程時間線解析度莫名變化
- **情境**：建模 A→回總覽→從另一張卡「查看結果」B。
- **影響**：window 沒有 per-bundle 記錄，從卡片進來用上次精靈殘留值；時間線粗細時好時壞，難理解。
- **evidence**：`frontend/demo_app.py:674-686`；_open_model 未帶 window
- **建議**：window 存入 bundle 並在 _run 優先採用 bundle 窗長。
- **提出角色**：新手使用者

---

## 3. 驗收 / acceptance gate

### [blocker] 驗收建的是「前半 golden」臨時模型，部署的是「全 golden」模型——驗收與部署不同模型，FPR/recall 不可轉移
- **情境**：使用者圈一段 golden 建模上線，build_model_for_process 先呼 acceptance_summary 拿 gate、再呼 build_and_save_model 存實際上線 bundle。
- **影響**：acceptance 用 `HealthIndex().fit(Xfit)`（前 holdout_frac 段）驗收，但上線用 `HealthIndex().fit(Xg)`（完整 golden）。兩者 PCA basis、控制限分位、_severity_health μ/σ、confidence baseline、block_len_ 全不同；半量 n 更小→控制限/σ 更不穩、FPR 偏高（誤擋合格模型）或 recall 高估。驗收 PASS/FAIL 對上線模型不具統計效力，簽核依據量錯對象。
- **evidence**：`src/health_index/deploy/acceptance.py:179`（fit Xfit）vs `src/health_index/deploy/demo.py:183`（fit Xg）；二者由 build_model_for_process 各自呼叫（demo.py:631,639）
- **建議**：驗收對「實際要存檔的 bundle」評 hold-out，或讓部署也只 fit 前段、後段純 hold-out，二擇一並文件化。
- **提出角色**：資料科學家／統計嚴謹度

### [blocker] 驗收 gate 完全不含 Y / 品質維度，含品質飄移的模型仍判 PASS 上線
- **情境**：建含 Y 軟測量的模型（ccpp/steel），驗收顯 PASS，但驗收過程完全沒碰 Y 維度。
- **影響**：acceptance_from_dataset 用 build_bundle 但**沒傳 y_health**，驗收 bundle 永遠 y_health=None，acceptance_report 只評 X 側 FPR/recall/spc_blind；部署 bundle 卻會 fit YHealthIndex。處長簽核的「PASS：可部署」完全不涵蓋品質維度，含 Y 飄移模型照樣上線。
- **evidence**：`src/health_index/deploy/acceptance.py:179`（無 y_health）；`src/health_index/deploy/demo.py:184-195`（fit YHealthIndex）；`frontend/demo_app.py:619-627`
- **建議**：驗收 bundle 也 fit y_health 並加 Y 維度 gate（golden 期 y_quality FPR、若有 Y-drift 段算 recall），或 UI 明標「驗收僅涵蓋 X 多變量，Y 品質維度未驗收」。
- **提出角色**：品保/QA 工程師、系統性/架構債 critic

### [major] FPR gate 可被「圈平穩段」放水：驗收的 golden ≠ 上線監看段，且選平穩段反抬高上線 FPR（結構性 p-hacking）
- **情境**：資料含非平穩尾段使固定真值 golden 恆 FAIL，使用者改圈最平穩子段直到 acceptance fpr_ok=True 後上線。
- **影響**：acceptance 在「同一段 golden」內做 holdout 時間切分驗 FPR，使用者反覆挑段＝在同一資料上多重嘗試選參數（selection on validation set）→ hold-out FPR 樂觀偏誤、上線實際 FPR 更高；選最平穩段使 in-sample σ 偏小→控制限更緊→上線對真實窗更易誤報。無嘗試次數記錄、無獨立第三段確認。UI 文案只是小灰字，PASS 被當全域可信。
- **evidence**：`src/health_index/deploy/demo.py:469,631`；`src/health_index/deploy/acceptance.py:150-181`；`frontend/demo_app.py:625-626`；commit c3ac9e0
- **建議**：鎖定 golden 後在獨立未用於選段的第三段驗 FPR，或記錄嘗試次數做多重比較校正；另報「全程非 golden 段告警率」或 golden 平穩性檢查並納入 PASS 條件，文件明示偏誤。
- **提出角色**：生產製程工程師、生產處長、資料科學家／統計嚴謹度

### [major] recall gate 只警告不擋，特徵子集（10取7）可丟掉帶訊號參數而仍上線
- **情境**：工程師 10 取 7 把恰好帶 drift 訊號的參數排除，drift_recall 掉到 0.2。
- **影響**：治理 gate 對 FPR 硬擋、對 recall 只警告（「知情取捨」），一行橘字提示後仍存檔上線；對隱性飄移偵測產品＝允許上線一個對已知 drift 幾乎全盲的模型，總覽顯示「健康」與正常模型無異，產品核心價值被靜默掏空，事故漏報責任難釐清。
- **evidence**：`src/health_index/deploy/demo.py:632-645`；`frontend/demo_app.py:630-637,1043`
- **建議**：recall 極低（如 <0.3）升級為需二次確認硬阻擋或要求填排除理由；總覽卡與全廠 banner 持續標「偵測力受限」徽章。
- **提出角色**：生產製程工程師、生產處長

### [major] 驗收用「資料集標準 hold-out」而非真實上線 golden，PASS 不代表線上不誤報
- **情境**：處長把「驗收 PASS（FPR≤目標）」當可上線合規憑證。
- **影響**：acceptance_from_dataset 以 holdout_frac=0.5 把同一連續段切兩半（同分布），對「換線回歸後是否誤報」「真實未來 golden」毫無覆蓋；PASS 只證明同分布內低誤報，保證範圍遠小於「可上線」直覺。
- **evidence**：`src/health_index/deploy/acceptance.py:138-182`；`src/health_index/deploy/demo.py:625-631`
- **建議**：上線前要求對真實 confirmed-normal 的未來 golden 段做二次驗收，UI 區分「開發驗收」vs「現場驗收」。
- **提出角色**：生產處長

### [major] recall gate 統計功效極低：recall>0.5 武斷門檻 + 短事故段窗數極少 + step=window 非重疊抽樣
- **情境**：drift_mask 段較短（數百列）、window=60，acceptance 用 persistence_k=1 評 recall。
- **影響**：recall_ok = recall>0.5 對安全關鍵漏報極寬鬆；poll_once step=window 使短 drift 段只切極少窗（300 列→5 窗），recall 是 5 個 Bernoulli 均值（標準誤 ~0.22）幾乎擲硬幣；acceptance 也未報 n_drift_windows 供判斷可靠度。
- **evidence**：`src/health_index/deploy/acceptance.py:114-117`；`src/health_index/deploy/runner.py:79`；acceptance_report 未回 n_drift_windows
- **建議**：事故段評 recall 改用重疊窗增樣本量、回報窗數與信賴區間，recall 門檻依風險上調並文件化。
- **提出角色**：資料科學家／統計嚴謹度

### [minor] recall_ok 用 recall>0.5 硬切，門檻寫死且不在同一 config、不可調、不透明
- **情境**：drift_recall=0.5 恰好判 FAIL。
- **影響**：0.5 門檻與 fpr target(0.05) 不在同一 config，工程師無法調；對弱 drift 場景過嚴或過鬆，文案沒說 0.5 從何而來。
- **evidence**：`src/health_index/deploy/acceptance.py:58,117`
- **建議**：把 0.5 提到 config 並在 verdict 顯「recall {x} < 門檻 {0.5}」。
- **提出角色**：生產製程工程師

### [minor] acceptance 的 _resolve_golden 未顯式傳 config，與建模靠「DEFAULT 恰好相同」隱性對齊
- **情境**：未來把變點切段參數改可配置（非 DEFAULT），demo 與 acceptance 的 auto golden 會悄悄選不同段。
- **影響**：兩條本該保證「驗收 golden＝建模 golden」的路徑靠「都沒傳剛好都吃 DEFAULT」維持，任一處改傳非 DEFAULT 即靜默破壞驗收口徑，無測試守護。
- **evidence**：`src/health_index/deploy/acceptance.py:169`（未傳 config）vs `src/health_index/deploy/demo.py:131,181`；`dataframe.py:115`
- **建議**：acceptance.py:169 顯式傳同一 config，並加測試斷言「同 spec 下 acceptance 與 build 解析出同一 golden mask」。
- **提出角色**：生產製程工程師、系統性/架構債 critic

### [minor] acceptance recall_ok/spc_blind 為 None 時前端顯裸 None，無法判斷偵測力
- **情境**：資料集無 drift_mask 時看歷史頁版本表判某版該不該回退，drift_recall 顯 None。
- **影響**：歷史頁直接把 None 塞進文案「recall None」，無從判斷是「沒測」還是「測了沒過」，污染回退決策。
- **evidence**：`src/health_index/deploy/acceptance.py:109-110`；`frontend/demo_app.py:1043-1044`
- **建議**：None 時顯「（此資料集無事故標記，未評偵測力）」，文案區分 N/A 與 FAIL。
- **提出角色**：維修/可靠度工程師

### [minor] 建模窗長 vs 偵測器有效窗長下限無前端校驗，太小窗可建出無功效模型
- **情境**：把評分窗長設成 10（min=10）對高維資料集建模。
- **影響**：window min=10 但 health/fwer block-bootstrap、L2 SPE 在小窗下 recall≈0；前端不擋、不警告窗長相對維度 p 過小（n<p 退化）；acceptance 同窗驗 FPR 可能照樣 PASS 但無偵測力，與「recall gate 只警告」疊加放大盲區。
- **evidence**：`frontend/demo_app.py:271`；`src/health_index/health.py:283`
- **建議**：窗長相對維度過小（如 window<2p）時前端警示，或鎖最小窗長為 catalog default。
- **提出角色**：生產製程工程師

### [minor] 驗收 PASS/FAIL 只在建模當下顯示，回總覽後現役卡片不顯示驗收狀態
- **情境**：建好幾個模型回總覽，想一眼看哪些製程現役模型驗收 PASS。
- **影響**：_asset_card 不顯 acceptance.passed（快照其實存在 model record），要看驗收得進歷史頁逐版本看；總覽看不出哪些是「FPR 合格但 recall 低」的勉強上線版。
- **evidence**：`frontend/demo_app.py:140-167`；`src/health_index/deploy/assets.py:120`
- **建議**：卡片加驗收徽章（PASS/recall低警示），點擊跳歷史。
- **提出角色**：生產製程工程師

---

## 4. 事件 / 告警閉環

### [blocker] 事件清單無法點回該窗下鑽，現場工程師拿不到肇因細節（事件→該窗下鑽連結斷裂）
- **情境**：作業員通報後工程師開「事件」頁看 INC-0007，想看該窗 RBC 排行/各層 p-value/Ŷ-vs-Y 再決定停不停車。
- **影響**：事件卡只顯 product｜top_cause｜health｜confidence｜detected_at，無任何連到結果頁該窗的連結；事件存了 window=[start,end] 但 UI 完全沒用它 deep-link。工程師只能自己回精靈重建同模型、手動找紅點再點下去（窗長還可能對不上）。閉環斷裂、延長 MTTR。
- **evidence**：`frontend/demo_app.py:901-927`（事件卡無下鑽按鈕）；window 欄存在但 UI 未使用
- **建議**：事件卡加「查看此窗」按鈕：載入該 product 現役 bundle + 帶 window→直接渲染 window_detail。
- **提出角色**：現場工程師

### [major] _run 進結果頁即自動開事件：讀路徑帶持久化副作用（CQS 違反，多角色）
- **情境**：工程師只是想「查看健康指標」點進結果頁，或畫面掛 60s tick 一整夜，每次重評都嘗試 open_incident 寫 incidents.json。
- **影響**：_run 是呈現 callback 卻內含 open_incident（製程+品質兩種），每次切回 results 都重評重開；事件開案時間＝「某人最後一次點進結果頁的時間」而非真正偵測時間；新手看事件頁驚訝「我沒做什麼怎麼有事件」；無 auth 下可被當放大器反覆觸發昂貴 score_timeline 造成 DoS；事件來源不可歸因。incidents.json 又非原子寫，高頻寫放大損毀窗口。
- **evidence**：`frontend/demo_app.py:678-711`（呈現 callback 內 open_incident）；`frontend/demo_app.py:77,170-172`（tick）；`src/health_index/deploy/events.py:71-74`（非原子 _save）
- **建議**：把開案移到明確的偵測/排程路徑（runner）或顯式使用者動作，results 屏只讀不寫；對自動刷新加快取/節流。
- **提出角色**：現場工程師、生產製程工程師、品保/QA、資安/IT、軟體可靠度、新手使用者、系統性/架構債 critic

### [major] 事件 severity 由 health/confidence 自動定級，與 RBC 肇因/層數一致性無關，停車優先序失真
- **情境**：兩筆事件 health 相近，但一筆 L2 SPE 單層邊緣、一筆 L1+L2+L4 三層一致並命中關鍵安全位號，需先處理後者。
- **影響**：severity_of 只看 health 與 confidence；window_detail 的 verdict 已算 n_bad（多少層一致）與「可信告警/存疑」更貼近停車判斷，卻沒寫進 incident；open_incident 只帶 top_cause。事件清單紅黃綠無法反映幾層一致，排序可能先處理單層邊緣後處理三層一致的真飄移。
- **evidence**：`src/health_index/deploy/events.py:43-51`；`src/health_index/deploy/demo.py:448-461`；`frontend/demo_app.py:701-702`
- **建議**：把 verdict/n_bad/層狀態快照寫進 incident，severity 納入層一致性。
- **提出角色**：現場工程師

### [major] 事件 top_cause 鎖在建模時最嚴重窗的 RBC 首位，與當下點開的窗未必同因；RBC smearing 警語未上 UI
- **情境**：一段 re-entry 期前後肇因不同（先 TIC 漂後 FIC 漂），事件 top_cause 鎖在最低 health 那窗。
- **影響**：事件卡只顯單一 top_cause、不顯涵蓋哪些窗各窗肇因；飄移源頭轉移時被單一肇因誤導；RBC 自陳「定位非因果、多方向漂移殘留 smearing」但 UI 完全沒把不確定性 surface，易把 RBC 首位當唯一真因→查錯位號。
- **evidence**：`frontend/demo_app.py:692-702`；`src/health_index/detectors/mspc.py:11-12`
- **建議**：事件卡列 top-3 RBC 並標「定位非因果」；下鑽帶出 smearing 風險文案。
- **提出角色**：現場工程師

### [major] 存疑（外推、低可信）告警仍持續開成事件，且事件卡不顯「存疑」語意
- **情境**：操作點移到建模域外（confidence<0.6），HI 低但其實是外推不可信，系統照樣連續告警並開事件。
- **影響**：persisted_alarm 不看 confidence；window_detail verdict 會標「存疑（外推）建議先觀察」但沒傳進事件；事件卡只顯 severity 字串無「存疑/先觀察」指引，工程師易把 warning 事件當真去現場處置外推假警→警報疲勞、稀釋真實告警。
- **evidence**：`frontend/demo_app.py:692-702`；`src/health_index/deploy/demo.py:452-454`；`src/health_index/deploy/events.py:45`
- **建議**：開事件帶入 verdict label；事件卡顯「存疑（外推）」建議先觀察，或低可信不自動開案只記錄。
- **提出角色**：現場工程師

### [major] 品質事件 confidence 直接借用 X 側 health confidence，severity 因而失真
- **情境**：X 側操作點落在建模域內（confidence 高）但 Y 側 map_health 崩（X→Y 關係斷）→開 quality 事件。
- **影響**：confidence=qw 的 X 側 T² 操作域相似度，與 Y 品質可信度無關；severity_of 用它定級→X confidence 高→不降級為 warning→品質事件被判 critical（即使 Y 觀測極稀疏不可信）；反之 X 外推又把可信品質告警壓成 warning。Y 維度缺自己的可信度量。
- **evidence**：`frontend/demo_app.py:710-711`；`src/health_index/deploy/events.py:43-51`
- **建議**：品質事件 severity 改用 Y 側量（map_health + n_y_obs/cp_available），或明確標「可信度為 X 側、僅參考」。
- **提出角色**：品保/QA 工程師

### [major] Ŷ 水準漂移 z 在無實際 Y 觀測時仍獨立開 critical 品質事件，無 Y 落地佐證且 health 用 magic number 9
- **情境**：延遲量測：整段窗都沒實際 Y 到達，但製程 X 漂移使 Ŷ 窗均值偏離 golden Ŷ 基準 >3σ。
- **影響**：level_drift 只看 yhat_drift_z（純 Ŷ 推估，無實際 Y），連續 k 窗即開 quality 事件；但 Ŷ 由已漂移 X 經 golden 模型外推＝「推論的推論」，X 漂移本身已由 X 側 health 抓→雙重計數+警報疲勞；qh=1−min(|z|/9,1) 的 9 是無依據 magic number。
- **evidence**：`src/health_index/deploy/demo.py:307-319`；`frontend/demo_app.py:707-711`
- **建議**：Ŷ-only 漂移降級為提示（非開 critical），或要求窗內有最低 Y 觀測才升級；移除 magic 9 改可解釋映射。
- **提出角色**：品保/QA 工程師

### [major] 事件告警清單只能依狀態篩選，無法依製程/嚴重度/時間/肇因篩選或排序
- **情境**：全廠 30 製程上百筆事件，只想看自己負責的某塔、critical、最近 8 小時。
- **影響**：只有 evt-filter（all/open/ack/closed），無 product/severity/時間/kind 篩選，無排序，list() 固定 detected_at 新→舊。事件多了無法快速定位，交接整頁滑，「該先停哪台」丟給肉眼掃。
- **evidence**：`frontend/demo_app.py:338-345`；`src/health_index/deploy/events.py:127-134`
- **建議**：加 product/severity/kind/時間範圍篩選與可選排序（嚴重度/時間/MTTR）。
- **提出角色**：現場工程師

### [major] ROI / 事件 KPI 為全量跨製程彙總，無法依廠區/製程下鑽歸因
- **情境**：處長在事件頁看到全廠 MTTR/critical/估省金額，想知道哪個廠區/製程貢獻最多事件與損失。
- **影響**：event_overview stats/roi 對全部 incidents 一次彙總，evt-filter 只篩 status 且 KPI/ROI 仍全量；無 by product/area 分組，「哪條線最該投資/最該擔心」無法回答，喪失資源配置決策價值。
- **evidence**：`src/health_index/deploy/demo.py:535-540`；`frontend/demo_app.py:340,881-887`
- **建議**：事件頁增加 by-product / by-area 的 MTTR/事件/ROI 分組表與篩選。
- **提出角色**：生產處長

### [minor] 事件防重複以 (product, kind) 鎖一個 active episode，同製程並發/接續不同肇因被併入同一案（多角色）
- **情境**：同製程先後出現兩個不同位號的飄移，第二個發生時第一個事件還沒關。
- **影響**：open_incident 同 (product,kind) 已有 active 就回既有事件不開新案、top_cause/window 不更新；第二個飄移若短暫就完全沒留痕；維修場景下不同成因被摺成一案，掩蓋重複發生問題頻次，影響稽核軌跡與可靠度統計。
- **evidence**：`src/health_index/deploy/events.py:80-101`
- **建議**：命中既有 active 時把新窗/新肇因 append 進該事件明細；或肇因顯著變化時開子案/升級；可加時間窗。
- **提出角色**：現場工程師、生產處長、維修/可靠度工程師

### [minor] 品質事件 top_cause 固定為一句模板文字，無具體品質變數定位
- **情境**：QA 收到品質飄移事件，想知道是哪個品質指標（哪個 Yq 維/哪個 X 經 RBC）在飄。
- **影響**：開品質事件時 top_cause = 固定字串「品質飄移：X→Y 殘差超界…」，不像 X 側用 RBC 給具體變數；dist_health 又失效，多維品質哪一維崩無從報。QA 只知「Y 飄了」不知哪個標的。
- **evidence**：`frontend/demo_app.py:707-711`
- **建議**：品質事件附 X→Y RBC 或最異常 Yq 維；至少把該窗 yhat vs y_actual 偏差量帶入事件。
- **提出角色**：品保/QA 工程師

### [minor] 事件 severity 規則寫死門檻（0.6/0.45），不可依產線風險調整，且與健康門檻試算脫鉤
- **情境**：處長想依不同製程風險等級設定「什麼健康度算 critical」。
- **影響**：severity_of confidence<0.6→warning、health<0.45→critical 寫死不可配置；結果頁門檻 slider 是 what-if 不影響 severity 分級與 ROI critical 計數，調了 slider 以為調了靈敏度實際毫無影響。
- **evidence**：`src/health_index/deploy/events.py:43-51`；`frontend/demo_app.py:303,776-783`
- **建議**：severity 門檻 per-製程 config 化；門檻 slider 提供「套用寫回模型」或明標「僅視覺試算」。
- **提出角色**：生產處長

### [minor] incident id 用 max(現有編號)+1，無唯一性保證，並發或外部刪改會碰撞
- **情境**：兩請求並發各自 _load 得同一 max→產生同一 id；或外部刪掉最大號再開案→id 重用指向不同事件。
- **影響**：_next_id 非單調持久計數器（對比 assets 用 next_version 較佳），無鎖加劇碰撞→稽核引用錯亂、CSV 匯出對不上。
- **evidence**：`src/health_index/deploy/events.py:76-78`
- **建議**：改持久單調計數器或 UUID，配合檔案鎖。
- **提出角色**：資安/IT 整合

### [minor] _run 每次進結果頁開事件，與門檻 what-if 脫鉤導致事件數與畫面不一致
- **情境**：把 what-if 門檻拉到 0.5 看到「沒幾窗低於門檻」，但事件頁已按 0.6 開了告警事件。
- **影響**：畫面門檻線可拉到 0.5 顯「更少窗超標」，事件頁仍 0.6 口徑；兩數字並存不一致，營造「調低就少告警」錯覺但事件閉環不受影響→認知失調。
- **evidence**：`frontend/demo_app.py:690-711,776-783`
- **建議**：what-if 區塊明示「不影響已開事件」，或讓事件數隨套用後門檻一致。
- **提出角色**：生產製程工程師

### [minor] ROI「每次停車損失」處長字眼夾在事件流干擾作業員 / 預設一百萬視覺權重壓過免責小字
- **情境**：夜班作業員/新手想快速處理告警事件，事件頁先擺「停車損失 100 萬」「估省 $X」ROI 卡；新手把綠字大數字當系統算出的真實節省。
- **影響**：ROI 是處長 KPI，對作業員是雜訊還可能誤觸改損失假設值；roi_card 雖有小字「情境假設非實測」但綠色大字視覺權重遠高，誤把假設性 ROI 當實測，對 demo 可信度是風險。
- **evidence**：`frontend/demo_app.py:333-336,888-895`
- **建議**：operator 視圖隱藏 ROI/損失區塊；把「情境估算」做成同等視覺權重標籤貼數字旁，而非小字。
- **提出角色**：現場作業員、新手使用者

---

## 5. ROI / KPI / MTTR 時間語意

### [major] ROI「估省金額」由使用者自填假設驅動，可被操弄成任意數字，採購背書風險高
- **情境**：拿 ROI 看板向上呈報採購效益，但 roi-loss 自填（預設 100 萬）、prevented_fraction 寫死 0.5、est_savings = n_critical × 0.5 × loss。
- **影響**：三個乘數沒一個是實測（避免比例 0.5 憑空、critical 數來自系統 severity 規則、損失由使用者輸入）；n_critical 還含未關閉甚至誤報事件；放採購決策看板上數字暗示力遠大於免責小字，事後實測對不上會反噬信任、可被灌水。
- **evidence**：`src/health_index/deploy/roi.py:29-32`；`frontend/demo_app.py:333-336,888-894`
- **建議**：ROI 區分「已關閉真實處置事件」分母、prevented_fraction 可輸入並標敏感度區間、加「需上線後實測回填」為強制欄而非小字。
- **提出角色**：生產處長

### [major] MTTR 混用樣本索引重放時間（detected_at）與真實牆鐘（closed_at），算出荒謬巨大值（多角色）
- **情境**：用 MTTR 比較各製程修復效率，但 detected_at = score_timeline 給的 str(ts_col.iloc[s.start])（資料集歷史時間戳），closed_at = datetime.now()（按關閉鈕當下）。
- **影響**：兩個時間屬不同時間軸，相減出的 MTTR 在 demo 是無意義巨大數字（可能數年）；污染處長 KPI、交接摘要、ROI；事件 detected_at 與其他時間（_iso 帶 offset）格式不一致。
- **evidence**：`src/health_index/deploy/demo.py:286,701-702`；`src/health_index/deploy/events.py:55,122-125`
- **建議**：demo 模式對重放事件用模擬時鐘或標「MTTR 在重放模式不適用」；統一 detected/closed 皆用真實牆鐘，資料窗時間另存欄供 historian 對照。
- **提出角色**：生產處長、現場工程師

### [minor] ROI 預設一百萬、結果頁未標單位脈絡，新手易誤讀為實測效益
- （與 §4「ROI 處長字眼」部分重疊，此筆聚焦 ROI 數字視覺權重）
- **evidence**：`frontend/demo_app.py:334,888-894`
- **建議**：把「情境估算」做成同等視覺權重標籤貼數字旁。
- **提出角色**：新手使用者

---

## 6. 總覽 / banner / 健康燈語意

### [major]「全廠視圖」其實只是單機 temp 目錄裡的清單，無多廠/廠區拓樸
- **情境**：處長要「全廠/廠區階層」，實際 registry 與模型存在 tempfile.gettempdir()，每 session 共用同一台機器 temp，重開機即清空，只有單層 area 分組。
- **影響**：assets_overview 只依單一 area 字串扁平兩層（區域→製程），無「廠」層、無跨廠彙總；area 是選填自由文字，不同人填不同字就分到不同區；採購方期待的全廠階層治理視圖不存在，落地工作量被低估。
- **evidence**：`frontend/demo_app.py:25,119`；`src/health_index/deploy/demo.py:558-562,712-716`
- **建議**：明示 demo 為單裝置/單機範圍；全廠階層列為導入期工程項並給工時估算。
- **提出角色**：生產處長

### [major] 健康燈的「灰」混入「不可得」與「待建模」兩種完全不同語意，data_unavailable 被當中性灰、全廠燈仍綠（多角色）
- **情境**：某製程燈灰，到底是「還沒建模（正常，新製程）」還是「資料源不可得/模型壞了（異常，需處理）」？兩者在 banner 與 tile 被合併。
- **影響**：assets_overview 把 placeholder 與 data_unavailable 都算進 n_placeholder 並排除綠紅分母，banner「K 待建模」混為一談；data_unavailable（模型載入失敗/指紋漂移/資料源消失）是該告警的異常卻被歸中性灰，一個資料源掉線的製程不會讓全廠燈變色＝監控盲區；判定散在 _score_current / assets_overview / monitoring_overview 三處各自 try/except，無單一狀態機，任一處改動三屏不一致。
- **evidence**：`src/health_index/deploy/demo.py:704,708-711,681,507`；`frontend/demo_app.py:129-130,177`
- **建議**：把製程健康狀態抽成單一狀態機（enum: placeholder/healthy/alarm/data_unavailable/stale），所有屏讀同一函式；data_unavailable 對現役模型升為警示（黃/灰閃）並納入需關注分母，banner 分開計數。
- **提出角色**：生產處長、系統性/架構債 critic

### [minor] 閃示是全廠級，單一製程告警就整個 banner 狂閃，看不出是哪條線、多嚴重
- **情境**：整片 banner 紅閃以為全廠出事，其實只是 10 條線裡 1 條告警。
- **影響**：className 只要 plant_status=='alarm' 就掛 pg-flash，banner 文字是彙總數字；要找哪條製程得往下捲；沒把「最嚴重那條」提到 banner，也沒嚴重度分級閃法→無法 30 秒定位、過度警覺後鈍化。
- **evidence**：`frontend/demo_app.py:158,176-180`
- **建議**：banner 直接點名最嚴重製程與健康值並提供跳轉；依 severity 分閃法。
- **提出角色**：現場作業員

### [minor] banner 文案與分母自相矛盾：placeholder 算進 n_placeholder 卻又說「不計入綠紅燈」，alarm⊂monitored 未說明
- **情境**：看 banner「N 監控中／M 告警／K 待建模」與清單標題，三數關係不直觀。
- **影響**：n_alarm 是 n_monitored 子集，三數相加重複計告警，非技術讀者快速掃視可能算錯全廠總數或告警佔比。
- **evidence**：`frontend/demo_app.py:177,182-183,196`；`src/health_index/deploy/demo.py:708-711`
- **建議**：明示「監控中（含告警 M）」「待建模/不可得」；或「總數 = 監控中 + 待建模」一致拆法。
- **提出角色**：生產處長

### [minor] plant_status='empty' 在「有 placeholder 但無已監控製程」時 banner 與卡片清單語義不自洽
- **情境**：建了 3 個 placeholder（都還沒建模），banner 顯「尚無監控中製程」但下方列了 3 張卡「待建模」。
- **影響**：plant_status='empty'（n_monitored=0 不看 placeholder）使 banner「尚無」與「有 3 個待建模」同屏衝突，新手誤以為系統沒記住剛建的製程。
- **evidence**：`src/health_index/deploy/demo.py:711`；`frontend/demo_app.py:176,184-198`
- **建議**：增 'placeholder_only' 態，banner 改「N 個製程待建模，尚未開始監控」。
- **提出角色**：無人查的面向 critic

---

## 7. 治理 / 權限 / 稽核問責

### [blocker] 全系統零認證/授權，任何能連到埠的人皆可建/刪製程、關事件、改 ROI（多角色）
- **情境**：試點上線後，任何能開到 http://127.0.0.1:8051 的人（含承包商、訪客、其他班別、同主機任一帳號）都能直接操作；角色切換只是前端 RadioItems 純呈現濾鏡，無「處長」角色。
- **影響**：無 login/SSO/RBAC、無 session、無 auth middleware；所有 callback（_build/_del_proc/_event_action/_restore_proc）直接寫持久化；可軟刪生產製程、關閉/誤標事件、竄改稽核 actor、改 ROI；稽核軌跡可偽造、破壞性操作無問責、合規（21 CFR Part 11/ISO）完全過不了→對採購決策是硬否決項、IT 不可能放行。
- **evidence**：`frontend/demo_app.py:86-90,932,1005-1016,1077`；`docs/frontend_design_guide.md:117,131`
- **建議**：前置反向代理 + 企業 SSO/OIDC（或至少 basic auth）；actor 取自驗證後身分而非自填欄位；破壞性動作（刪除/關案/建模）做角色 server-side 授權並記真實身分。
- **提出角色**：生產處長、資安/IT 整合

### [blocker] 稽核 log 可竄改：純 JSON、無簽章/雜湊鏈/append-only 強制，actor 自由文字可冒名（多角色）
- **情境**：稽核要當合規證據（誰建模、誰刪製程、誰關事件 INC-0007），但 audit 是 registry.json 內一個 list，任何能讀檔的人可直接編輯 .json 改 actor/at/action 或整段刪除；且 actor 是使用者自填 free text，可填任何名字或留空變「未具名」。
- **影響**：AssetStore._audit 每次 _save 整檔覆寫，無 hash chain/HMAC/WORM/外部 append-only sink；記的是「使用者宣稱的身分」無驗證。稽核 log 看似完整但誠信為零（比沒有稽核更危險，營造可信假象）；事故責任歸屬、false_alarm（影響 ROI/MTTR）都可被任意人篡改署名→無法抗否認、合規/事故調查無效。
- **evidence**：`src/health_index/deploy/assets.py:56-62,72-74`；`src/health_index/deploy/events.py:112-125`；`frontend/demo_app.py:328-329,942`；`docs/model_registry_design.md:97`
- **建議**：actor 必須來自已驗證登入身分（server-side）；audit 條目加前向 hash 鏈或 HMAC，或寫獨立 append-only log（O_APPEND）並定期外送 SIEM。
- **提出角色**：生產處長、資安/IT 整合、現場工程師、生產製程工程師、現場作業員

### [major] 刪除製程一鍵無二次確認，誤點即軟刪整製程並強制關閉其事件（多角色，最高頻 UX 風險）
- **情境**：凌晨/巡檢/新手在密集排列的 mini 按鈕中誤點某製程「刪除」（緊鄰「歷史」「更換模型」），製程立刻消失、孤兒事件被強制關閉。
- **影響**：_del_proc 直接呼 soft_delete_process 無 confirm dialog；雖軟刪可在歷史還原，但被強關的 open/ack 事件不會因還原自動重開（restore 只翻 deleted 旗標），MTTR/ROI 統計被永久污染；UI 不告訴使用者「已刪、可到歷史還原」，卡片就消失，使用者恐慌以為資料弄丟或系統故障。
- **evidence**：`frontend/demo_app.py:155-156,1005-1016`；`src/health_index/deploy/assets.py:143-171`
- **建議**：刪除加 dcc.ConfirmDialog 二次確認 + 權限 gate；刪除後 toast「已刪除，可到歷史還原」；還原時提供「一併重開被強關事件」選項；把刪除移出常用按鈕列或收進次選單。
- **提出角色**：現場作業員、生產製程工程師、生產處長、新手使用者、軟體可靠度

### [major] 換版後沒有 rollback（回退舊版設為現役）的 UI 入口
- **情境**：換 v2 後發現比 v1 差，想退回 v1 當現役。
- **影響**：assets 有 soft_delete_model/restore_model 但無公開「設某舊版為現役」方法；歷史頁只有「還原製程」按鈕，無「設為現役/回退」；要退回只能軟刪 v2（副作用大、語義不對），破壞版本歷史。
- **evidence**：`src/health_index/deploy/assets.py:130-182`；`frontend/demo_app.py:1041-1061`
- **建議**：加 set_current(model_id) 後端方法 + 歷史頁每版「設為現役」按鈕。
- **提出角色**：生產製程工程師

### [major] 更換模型流程不顯示「新舊版本對比」，工程師無法判斷是否該換
- **情境**：製程已有 v1 現役健康偏低，想換 v2 但先比 v1/v2 的 golden、驗收、FPR 再決定。
- **影響**：更換走 build-cta→精靈→建模同條路，建完直接 record_build 把 current 指到新版，無「v_new vs v_current 對比」畫面；可能換到 recall 更差/FPR 更高的版而不自知，要回歷史頁才發現已切 current。
- **evidence**：`frontend/demo_app.py:152,595-602`；`src/health_index/deploy/assets.py:104-128`
- **建議**：建模結果頁加「與現役 vN 對比」表（FPR/recall/golden 範圍），並提供「暫不設為現役」選項。
- **提出角色**：生產製程工程師

### [minor] 事件操作者欄空白記「未具名」，刪製程/建立用的 actor 欄藏在事件頁
- **情境**：半夜 ACK 忘填工號→記「未具名」；在總覽刪製程時 event-actor State 為空→稽核記「未具名」。
- **影響**：actor 可留空、無登入綁定，趕著處理常忘填，稽核形同虛設；event-actor 輸入框只在事件頁渲染，在總覽刪/建時拿不到→問責鏈斷裂。
- **evidence**：`frontend/demo_app.py:328,942,1006,1014,1065,1073`
- **建議**：未填操作者擋下動作並提示，或接登入身分自動帶入；全域放一次操作者欄或就地要求填名。
- **提出角色**：現場作業員、生產製程工程師、資安/IT、新手使用者

### [minor] event ack/close 任何人填名即可、無認證，且 close 可由非 ack 者直接關閉
- **情境**：稽核要追「誰認領、誰關閉」這筆停車相關事件。
- **影響**：close 不要求事件先被 ack（無狀態前置檢查），ack_by 用 rec.ack_by or by 補；安全相關事件稽核軌跡可信度低。
- **evidence**：`frontend/demo_app.py:328,942`；`src/health_index/deploy/events.py:116-125`
- **建議**：至少約束 close 前須 ack，並把 actor 與登入身分綁定。
- **提出角色**：現場工程師

### [minor] version 單調計數器永不回收，外部編輯 registry 可使 peek/record assert 永久卡住建模並產生孤兒模型檔
- **情境**：build_and_save_model 存檔在前、record 在後、assert 在最後；兩步間 registry 被並發/外部改動使 record 給出不同 version→raise RuntimeError，但 .joblib 已存檔→孤兒模型檔。
- **影響**：孤兒檔不在 registry 卻佔名、可被後續同名覆蓋或被 monitoring_overview glob 掃到當未知資產評分，污染總覽且無稽核。
- **evidence**：`src/health_index/deploy/demo.py:638-644,496-509`
- **建議**：先 record 成功再 save，或失敗時清掉已存檔；overview 統一只認 registry 登錄者。
- **提出角色**：資安/IT 整合

### [minor] create_process 純中文名 slug 落空回 dataset 名，多個同 dataset 中文製程 id 互疊但 display 相同
- **情境**：建兩個都叫「常壓蒸餾塔」、都用 tep 的製程。
- **影響**：_slug 純中文 len<2 回 fallback(dataset)，同名去重給 tep、tep-2…，display_name 仍中文相同，總覽兩張卡 display 一樣難辨；np-status 不提示重名/pid 後綴。
- **evidence**：`src/health_index/deploy/assets.py:32-35,90-93`；`frontend/demo_app.py:1001`
- **建議**：display_name 重複時附短 id 後綴顯示或允許自訂英數代號；建立前檢查重名給警告。
- **提出角色**：軟體可靠度、新手使用者

### [minor] 軟刪除「絕不刪 .joblib」+ temp 目錄：敏感 golden/位號無保留期、無法真正清除、重開機全失（多角色）
- **情境**：客戶要求刪除某產線模型與 golden 製程資料（含 DCS 位號），操作者按刪除，但 .joblib 連同 golden 指紋樣本仍留共用 temp。
- **影響**：soft delete 只翻旗標不刪檔；bundle 內含 fingerprint_x（golden 前 20 列原始值）與 x_columns，tags/{product}.json 含 DCS 位號，全存 tempfile.gettempdir()（同機他人可讀、重開機 OS 清 temp 全失、跨天 demo「全廠清空」）；GDPR/客戶刪除權無法滿足，敏感資料明文殘留共用 temp。
- **evidence**：`src/health_index/deploy/demo.py:648-657,340-351`；`src/health_index/deploy/bundle.py:59,113`；`frontend/demo_app.py:25`；`docs/model_registry_design.md:101`
- **建議**：soft delete 對 .joblib 與 tags 設保留期 + 受稽核硬刪入口；持久化目錄移出 temp 到受權限保護固定路徑並設 retention policy；評估 fingerprint_x 匿名化。
- **提出角色**：資安/IT 整合、系統性/架構債 critic、生產處長

---

## 8. 資安 / IT 整合

### [blocker] joblib.load 反序列化 bundle，任意 .joblib 進 _MODELS_DIR 即可 RCE
- **情境**：_MODELS_DIR 在系統 temp（多使用者共用、權限寬鬆），攻擊者放惡意 *.joblib（pickle __reduce__），使用者一進總覽 monitoring_overview/assets_overview glob 掃描並 load() 即反序列化執行任意程式碼。
- **影響**：bundle.load 用 joblib.load（底層 pickle 非安全），verify 指紋比對發生在反序列化之後（pickle RCE 在 load 當下觸發，verify 防不了）；本機其他使用者→RCE，temp 全域可寫使此路徑特別現實。
- **evidence**：`src/health_index/deploy/bundle.py:134-139`；`src/health_index/deploy/demo.py:496-500`；`frontend/demo_app.py:25`
- **建議**：模型目錄移出 temp 到受限權限路徑；驗證來源（簽章/HMAC over bytes）後才反序列化；或改安全序列化（skops/onnx）。
- **提出角色**：資安/IT 整合

### [blocker] _MODELS_DIR 放系統共用 temp，registry/incidents/模型全曝於同機其他使用者
- **情境**：多使用者主機（terminal server/共用工作站）上，gettempdir() 其他登入者可讀寫 registry.json/incidents.json/*.joblib。
- **影響**：機密性（誰監控什麼製程、事故內容外洩）+ 完整性（被改）+ 持久性（重開機資料消失）三重失守。
- **evidence**：`frontend/demo_app.py:25-27`
- **建議**：改用應用專屬資料目錄（%PROGRAMDATA% 或設定指定受限路徑），目錄權限 0700。
- **提出角色**：資安/IT 整合（與 §7 軟刪/部署 §9 temp 重開機高度相關）

### [major] incidents.json 寫入非原子（無 temp+os.replace），崩潰/並發整本事件庫損毀且靜默歸零
- **情境**：關閉/開案瞬間程序被殺/磁碟滿/並發寫入，json.dump 直接覆寫→寫一半即整個 incidents.json 損毀，_load 命中 JSONDecodeError 回 []→歷史事件與 MTTR/稽核全部歸零無聲。
- **影響**：assets.AssetStore 有 temp+os.replace 原子寫，events.py 卻直接 open(path,'w') 覆寫，連 crash-safe 都沒有；事件閉環/MTTR/ROI/稽核可被單次中斷整批毀掉。
- **evidence**：`src/health_index/deploy/events.py:71-74`（對比 `assets.py:56-62`）
- **建議**：IncidentStore._save 比照 AssetStore 用 temp+os.replace；JSONDecodeError 要 surface/備份而非靜默回 []。
- **提出角色**：資安/IT 整合、軟體可靠度

### [major] registry/incidents 持久化全程無檔案鎖，並發 read-modify-write race condition 丟資料
- **情境**：Dash 多執行緒，兩個 callback（建模+刪製程、自動開案+手動關案）並發各自 _load→改→_save；os.replace 只保單次寫不損毀，不保 read-modify-write 不互蓋→後寫者覆蓋前寫者，丟失製程/事件/稽核。
- **影響**：build_model_for_process 有 version peek/assert 偵測會 raise RuntimeError（fail-loud 但體驗差），其餘路徑靜默丟資料；soft_delete_process 內多次 _load 之間可被覆蓋、incident 與 registry 無交易邊界，半關閉狀態留孤兒事件。
- **evidence**：`src/health_index/deploy/assets.py:88-128,143-161`；`src/health_index/deploy/events.py:89-101`；`src/health_index/deploy/demo.py:643-644`
- **建議**：加跨程序檔案鎖（portalocker/msvcrt.locking）包住 load-mutate-save，或單寫入序列化佇列；一次 _load 內完成所有 registry 變更再單次 _save。
- **提出角色**：資安/IT 整合、軟體可靠度

### [major] bundle 指紋只防意外漂移不防惡意竄改（無金鑰、指紋與資料同檔）
- **情境**：指紋 fingerprint_x/hi/sub 都存同一序列化 bundle，攻擊者可同時改模型與改指紋使 verify 通過。
- **影響**：指紋是完整性自證非真實性；配合 joblib RCE，verify 給人「有完整性保護」錯覺；模型供應鏈完整性無保護，被掉包的 bundle 可冒充正常。n_fingerprint=20 還把 golden 前 20 列原始值明文嵌進每個 .joblib（敏感資料外洩面）。
- **evidence**：`src/health_index/deploy/bundle.py:65-78,111-123`
- **建議**：對序列化 bytes 做 HMAC（金鑰外存）或數位簽章，load 先驗簽再反序列化；指紋改存 golden 統計摘要的雜湊（脫敏）；docstring 明標「僅防意外漂移、不防惡意竄改」。
- **提出角色**：資安/IT 整合、系統性/架構債 critic

### [major] tag_map_for / plant_hierarchy 用使用者控制的 product 名直接拼檔路徑，潛在路徑穿越
- **情境**：product/process_id 源自製程命名；若任何路徑的 product 來源未過 _slug（舊資料/API 直呼/name 直接當 product），含 ../ 可讀任意 json。
- **影響**：tag_map_for / plant.json / build path 用 product 直接 os.path.join；UI 路徑經 _slug 緩解，但無集中防護是脆弱設計，product 來源擴大到未清洗輸入→任意檔讀取/覆寫。
- **evidence**：`src/health_index/deploy/demo.py:197,346,565,638-639`
- **建議**：集中一個 safe_join 拒含路徑分隔/.. 的 component；所有 product/process_id 落地前強制 _slug 驗證。
- **提出角色**：資安/IT 整合

### [major] Dash 為開發伺服器，無生產 WSGI/TLS/反代，直接 app.run 上線
- **情境**：__main__ 直接 app.run(debug=False, port=8051)——Werkzeug 開發伺服器，無 TLS、無限流、無 worker 管理。
- **影響**：開發伺服器已知不耐並發/不安全；無 HTTPS→稽核 actor、事故內容明文過網（若被反代曝出）。
- **evidence**：`frontend/demo_app.py:1078`；`frontend/app.py:578`
- **建議**：以 waitress/gunicorn + nginx(TLS) 部署；文件標明 app.run 僅供本機 demo。
- **提出角色**：資安/IT 整合

### [major] 所有持久化異常被靜默吞掉（except Exception/JSONDecodeError→回空/no_update），故障與安全訊號不可觀測
- **情境**：檔損、權限不足、磁碟滿、bundle 投毒驗證失敗等，monitoring_overview/_score_current/_event_action/tag_map_for 都 except 後回退（data_unavailable/no_update/{}）。
- **影響**：BundleIntegrityError 這種安全訊號（可能被竄改）被吞當「資料源不可得」灰掉；關案失敗使用者以為成功；違反 fail-loud（Rule 12）於安全面。
- **evidence**：`src/health_index/deploy/demo.py:507-509,681-682`；`src/health_index/deploy/events.py:68-69`；`src/health_index/deploy/assets.py:49-50`；`frontend/demo_app.py:956-957`
- **建議**：區分「安全相關例外（IntegrityError/PermissionError）」與「資料缺」，前者顯著告警並記 log；寫入失敗回明確錯誤給 UI。
- **提出角色**：資安/IT 整合

### [minor] runner save_state 非原子寫，線上重啟游標可被截斷損毀
- **情境**：線上 poll_once 後 save_state 寫 cursor/consecutive，寫入瞬間中斷→state 損毀；load_state 只接 FileNotFoundError，JSONDecodeError 會拋使排程器崩潰或游標歸零重放整段（重複開案）。
- **evidence**：`src/health_index/deploy/runner.py:126-139`
- **建議**：save_state 用 temp+os.replace；load_state 同時接 JSONDecodeError 回初始狀態並 warn。
- **提出角色**：資安/IT 整合

### [minor] 產線拓樸/DCS 位號（tags/*.json、plant.json）為敏感現場資料，明文無保護存 temp
- **evidence**：`src/health_index/deploy/demo.py:346-351,558-568`；`frontend/demo_app.py:25`
- **建議**：敏感 config 移到受控目錄/設定管理系統，存取走授權。
- **提出角色**：資安/IT 整合

### [minor] index_string 自訂 HTML 引入內聯 style、未設 CSP，缺安全標頭
- **影響**：無 Content-Security-Policy/X-Frame-Options/X-Content-Type-Options；display_name 自由文字雖走 React 文字節點較安全但無 CSP 兜底（clickjacking/未來 XSS 縱深防禦缺）。
- **evidence**：`frontend/demo_app.py:34-40,115,228`
- **建議**：反代層加 CSP/X-Frame-Options/HSTS；輸入長度與字元集限制。
- **提出角色**：資安/IT 整合

### [minor] CSV 匯出未做 formula injection 防護，事件 top_cause/close_note 可挾帶試算表公式
- **情境**：close_note 來自自由輸入，若以 =/+/-/@ 開頭，Excel 開匯出檔→CSV injection 執行公式。
- **evidence**：`src/health_index/deploy/demo.py:577-589`；`frontend/demo_app.py:907`
- **建議**：對以 =+-@ 開頭的儲存格前綴單引號或 tab，並用 QUOTE_ALL。
- **提出角色**：資安/IT 整合

---

## 9. 軟測量 Y / 品質維度

### [blocker] demo/registry 建模路徑永不建立 dist_health（多維品質分布維度全程失效）
- **情境**：QA 想靠「換產品/品質分布整批搬家」(dist 維度) 的偵測力，但任何透過精靈或 registry 建的模型 dist_health 永遠回 None。
- **影響**：build_and_save_model 只用純量 Y_VALUE 呼叫 YHealthIndex().fit(Xg, yg)，從不傳 Yq_golden→y_mspc_ 恆 None；只有 api/server.py 才傳 Yqg。前端 demo 全程沒有「分布健康」維度，y_health docstring 宣稱的兩條正交品質軸只剩一條；UI 仍以「品質維度」總稱呈現，使用者以為涵蓋分布漂移→換產品比例變/品質分布位移類隱性飄移在 demo 完全無偵測、假綠。
- **evidence**：`src/health_index/deploy/demo.py:191`；對比 `src/health_index/api/server.py:326`
- **建議**：build_and_save_model 接 Y_QUALITY 多維欄傳入 fit；或 UI 明標「demo 模型不含分布健康維度」。
- **提出角色**：品保/QA 工程師

### [major] 軟測量 CP 採 in-sample 校準（fit 與 calibrate 同一份 golden），覆蓋保證形同虛設
- **情境**：QA 看到 window_detail「conformal，覆蓋 90%」就信任那條 ±帶。
- **影響**：YHealthIndex.fit 先 ss_.fit(X,y) 再 ss_.calibrate_cp(X,y) 用同一份資料；split-CP 有限樣本覆蓋保證要求 calibration 與 fit disjoint/exchangeable（soft_sensor docstring 自己要求不重疊）；in-sample 殘差被 GPR/PLS 過擬合壓小→cp_q_ 偏窄→帶過窄→實際覆蓋 <1−α；UI/docstring 仍寫「覆蓋保證 ≥1−α」造成過度信任→QA 低估帶寬把超界 Y 當帶內→漏報品質偏移。
- **evidence**：`src/health_index/y_health.py:51-52`；`src/health_index/deploy/soft_sensor.py:79-80,108`
- **建議**：demo 路徑也切 disjoint calibration（golden 前段 fit、後段 calibrate），或文案改「近似帶（in-sample，非保證）」。
- **提出角色**：品保/QA 工程師、資料科學家／統計嚴謹度

### [major] Ŷ-drift z 用 golden Ŷ 的 σ 當門檻，GPR 外推回 prior mean 使遠離 golden 時 Ŷ 反趨中→z 縮小，隱性品質飄移漏報
- **情境**：X 大幅離開 golden 操作域（最該擔心的 re-entry 飄移），GPR RBF kernel 在訓練域外 predict 回歸 prior mean（≈訓練 y 均值 ≈ gy_mu）。
- **影響**：「離域越遠→Ŷ 越趨 golden 均值→|z| 越小」與直覺相反，最該抓的外推情形 z 反被壓低過不了 3σ；PLS（線性）外推則無界放大，同門檻對兩種 base estimator 統計意義不一致。
- **evidence**：`src/health_index/deploy/demo.py:307-318`；`src/health_index/deploy/soft_sensor.py:62-68`；`src/health_index/config.py:64`
- **建議**：Ŷ-drift 併入 GPR 後驗 std（return_std）做信賴加權，或外推（confidence 低）時抑制 Ŷ-drift 旗標改由域相似度承載。
- **提出角色**：資料科學家／統計嚴謹度

### [major] Y 稀疏時 UI 雖標稀疏提醒但仍以 ✅ 預測品質穩定 呈現綠燈，假綠掩蓋未判窗（多角色）
- **情境**：整段 Y 觀測 <50% 窗（sparse=True），③品質維度顯綠「✅ 預測品質穩定」，作業員/QA 安心。
- **影響**：n_quality==0 時 qtxt 以 ✅ 開頭只在括號補一句稀疏，顏色用橘非紅；但 map_health 在 obs<y_map_min_obs 的窗回 None 完全不參與判斷（等於「沒看過」而非「健康」）；把大量未判窗呈現為 ✅ 綠＝危險假綠，品質飄移（量產次級品）在 Y 稀疏時被掩蓋，作業員放行，正是 AVM 軟測量要防的事。
- **evidence**：`frontend/demo_app.py:757-765`；`src/health_index/deploy/demo.py:310-317`
- **建議**：Y 稀疏時不給 ✅，改中性灰「品質：資料不足，無法判定」並顯已判窗比例（如「僅 12% 窗有足夠 Y 可判」）。
- **提出角色**：現場作業員、品保/QA 工程師

### [minor] y_map_min_obs 預設 5，對破壞性/昂貴抽樣的真實 QA 情境過於樂觀
- **情境**：真實抽檢一個窗(60列)可能只有 1–3 筆實驗室回報，QA 期待據此判 X→Y。
- **影響**：map_health 需 obs≥5 才算，低於回 None→該窗品質維度直接不判（非保守告警）；低頻抽樣窗大量被判 None，削弱真實稀疏 Y 下的覆蓋；docstring 標「起手值待掃描」。
- **evidence**：`src/health_index/config.py:60`；`src/health_index/y_health.py:81`
- **建議**：UI 可調或依窗長/抽樣率自適應；文件標明此門檻對抽樣頻率的敏感度。
- **提出角色**：品保/QA 工程師

### [minor] y_map_scale / y_fusion_weights 等 Y 維度敏感度旋鈕全為未校準起手值，且 UI 不可調
- **影響**：y_map_scale=1.0 / y_flag_threshold=0.5 / y_trend_z_max=3.0 / y_fusion_weights=(1,1) 全 config 預設標「起手值將於 TEP 掃描定值」；X 側有門檻 slider，Y 品質維度完全沒等價 what-if 或調參，QA 對品質靈敏度零控制，FPR/recall 不明不可控。
- **evidence**：`src/health_index/config.py:58-64`；`frontend/demo_app.py:303`
- **建議**：為 Y 品質維度提供 what-if slider 或至少在驗收揭露 FPR/recall；補 Y 維度校準。
- **提出角色**：品保/QA 工程師

### [minor] dist_health 用 Y-MSPC is_anomaly 的「異常率」(1−frac)，退回 X 側已棄用的飽和度量
- **影響**：dist_health = 1 − is_anomaly(Yq).mean() 是二值越限比例，正是 X 側 health.py 指出「超限比例在弱隱性飄移下飽和漏報」而刻意棄用改 _severity_health 的問題；Y 側對弱品質分布飄移同樣飽和漏報，與 X 側設計不一致。
- **evidence**：`src/health_index/y_health.py:90-98`；`src/health_index/health.py:118-124`
- **建議**：dist_health 比照 _severity_health 改 per-sample 標準化嚴重度，統一兩側度量。
- **提出角色**：資料科學家／統計嚴謹度

### [minor] y_flagged 安全網在「無任何可用分量」時回 False，與「健康」在 UI 不可區分
- **影響**：y_flagged 對「無可用分量」回 False（不可判，不假陽），但 UI 對 y_flagged=False 一律顯正常；「不可判」與「判定健康」視覺塌縮為同一狀態，覆蓋盲區被當安全。
- **evidence**：`src/health_index/y_health.py:132-133`；`src/health_index/deploy/demo.py:430-431`
- **建議**：UI 對 y_flagged 區分三態（旗標/正常/不可判），「不可判」以中性灰標示並計數。
- **提出角色**：品保/QA 工程師

### [minor] 純量品質與多維品質 UI 文案混用「品質維度」/「無 Y 資料集 vs 有 Y 但未建」混淆
- **影響**：結果頁③統一寫「預測品質 Ŷ 偏移／X→Y 殘差超界」未區分模型是否含 dist；uci 等 y_label=None 的無 Y 資料集顯通用「此模型無 Y」模板，混淆「資料集結構上無 Y」與「此次建模沒接 Y」；QA 高估涵蓋面。
- **evidence**：`frontend/demo_app.py:738-741,755-765`；`src/health_index/adapters/uci_gas_drift.py:131`；`src/health_index/deploy/catalog.py:35`；`docs/algorithms_plain_guide.md:250-251`
- **建議**：結果頁列出模型實際啟用的 Y 分量（map ✓ / dist ✗）；y_label is None 時標「此資料集無品質量測標的（結構性，非建模選項）」。
- **提出角色**：品保/QA 工程師、無人查的面向 critic

### [minor] y_quality persistence 用 drift_persistence_k 但 X 側 persisted_alarm 由 runner 另算，兩條持續性語義不一致；config 註解誤導
- **影響**：score_timeline 內 y_quality_persisted 用 cfg.drift_persistence_k 自己數，X 側 persisted_alarm 來自 runner 預設；兩條邏輯分散不同層、預設值來源不同；config 註解寫 drift_persistence_k「預留未使用」但這裡已用於品質維度，文件與程式不符。
- **evidence**：`src/health_index/deploy/demo.py:322-325`；`src/health_index/config.py:76`
- **建議**：統一持續性路徑或 score_timeline 顯式傳 persistence_k；更新 config.py:76 註解。
- **提出角色**：品保/QA 工程師

### [minor] score_timeline 的 golden Ŷ 基準用資料集真值 golden_mask 而非模型實際 fit 的 golden，Ŷ 水準漂移 z 參考錯基準
- **影響**：build 用使用者選 golden、score region 用 gt.golden_mask 真值，gy 基準可能與 build 基準不一致。
- **evidence**：`src/health_index/deploy/demo.py:256-279`
- **建議**：score_timeline 的 golden 基準應用模型實際 fit 的 golden 範圍（存入 bundle），非資料集真值。
- **提出角色**：軟體可靠度

---

## 10. 偵測器 / 統計嚴謹度

### [major] MSPC 控制限以 in-sample 經驗分位估計→golden 自身 FPR 結構性低估（hold-out FPR≈2×）
- **影響**：MSPCModel.fit 用同一份 golden 同時估 PCA 又取經驗 (1−α) 分位當控制限，PCA basis 被擬合最小化這批點殘差→in-sample SPE/T² 偏小、控制限偏低；health docstring 自承 in-sample≈2α vs hold-out≈4α gap；總覽燈號走 compute_fwer=False 快路徑用此偏樂觀控制限→線上 FPR 系統性偏低估名目 α。
- **evidence**：`src/health_index/detectors/mspc.py:51-52`；`src/health_index/health.py:59-62`；`src/health_index/deploy/demo.py:505,679`
- **建議**：控制限也走 split（fit 段定 basis、hold-out 段定分位），或對 in-sample 限做有限樣本膨脹校正並文件化名目 α。
- **提出角色**：資料科學家／統計嚴謹度

### [major] confidence(T²) 宣稱「與 health 正交」但兩者建在同一 PCA basis，T² 與 SPE 非統計獨立（synthetic r≈0.39）
- **影響**：confidence=保留子空間 T²、health L2=殘差 SPE，實際 golden 非高斯、basis 有限樣本估、共用 _std 與同一 P_k_，docstring 自報 r≈0.39（非 0）；verdict 把中度去相關的兩量當乾淨兩軸，中間帶「存疑（外推）」與「可信告警」二分不穩。
- **evidence**：`src/health_index/health.py:153-188`；`src/health_index/deploy/demo.py:452-460`
- **建議**：verdict 改用連續分數而非硬門檻，或文件標明殘餘相關避免 0.6 硬切。
- **提出角色**：資料科學家／統計嚴謹度

### [major] _severity_health 用 golden per-sample σ 標準化，自相關下低估窗級變異 2.2×→融合 HI 對連續製程 covert drift recall≈0，但 HI 仍對外為主分數
- **情境**：連續 TEP（PC1 ρ₁≈0.93）隱性飄移段，使用者看 health_index 時間線判斷製程是否飄移。
- **影響**：窗均值除以單樣本 σ，自相關下窗均值真實變異 ≈2.2×(σ/√w)，標準化假設 iid→z 系統性低估，docstring 明寫「tep_tp drift 窗 HI<0.6 recall≈0」；最核心情境（連續製程隱性飄移）融合 HI 無偵測力全靠 fwer_alarm 補，但 UI 主曲線/燈號用 health_index 排序→使用者只看 HI 漏掉真飄移、給「健康」假象。
- **evidence**：`src/health_index/health.py:118-138`；`src/health_index/config.py:84`；`src/health_index/deploy/demo.py:504`
- **建議**：對 block_len_>1 改窗級 block-aware 標準化，或 UI 明標 HI 對自相關製程僅供參考、以 alarm/p-value 為準。
- **提出角色**：資料科學家／統計嚴謹度

### [major] golden 選「auto」取最早平穩 regime + 使用者可圈最平穩段過 FPR gate = 結構性 p-hacking
- （與 §3「FPR gate 圈平穩段放水」同根因，此筆從統計嚴謹度視角補述 selection-on-validation 偏誤；合併參見 §3）
- **evidence**：`src/health_index/deploy/acceptance.py:166-172`；`src/health_index/deploy/demo.py:469`；commit c3ac9e0
- **提出角色**：資料科學家／統計嚴謹度

### [major] Holm 用 fwer_alpha=0.05 但底層各層 p-value 多為近似/篩選統計量（非嚴格 uniform），FWER≤α 數學保證不成立
- **影響**：(1) L4 mmd_pvalue 自承「篩選統計量、型一 ≈6%@.05」；(2) L1 docstring「近乎無功效＝恆保守」破壞 uniform；(3) block window/perm 邊際近似；把這些近似 p 餵 Holm 並聲稱「FWER≤0.05」過度承諾（L4 單層就 6%>α），三層聯合真實 golden 誤報率未驗。
- **evidence**：`src/health_index/health.py:403-416,280`；`src/health_index/detectors/drift.py:136`
- **建議**：對組合 alarm() 做端到端 golden FPR 蒙地卡羅驗證並報實測值，文件把「≤α」改為「實測≈X%」。
- **提出角色**：資料科學家／統計嚴謹度

### [minor] block_len_ 只用 PC1 自相關代表全體→多模態/其他主成分強自相關時低估 ℓ、null 加寬不足、自相關 FPR 反彈
- **影響**：block_len_ 只看第一主成分，PC1 弱自相關但 PC2/PC3 強時整個 L4/L2 block 路徑退回 iid null→連續窗誤報（正是要修的根因）；block_len_ 也驅動 _fwer_l2_block_ 決定 L2 是否走 block p-value。
- **evidence**：`src/health_index/detectors/drift.py:55,80`；`src/health_index/health.py:69`
- **建議**：block_len_ 取各成分（或前 k 個）自相關長度的最大值/中位數。
- **提出角色**：資料科學家／統計嚴謹度

### [minor] _block_window_pvalue 當 s 接近 n 時可抽起點極少→null 退化、p 解析度崩
- **影響**：s=min(s,n) 起點 rng.integers(0,n−s+1)，s≈n（X 窗長接近 cal 段長）時 n−s+1 很小→bootstrap 起點幾乎重疊→null 近常數→p 只會是兩極端值；P2 continuous split 後 cal 段只約 n/3，遇 window=60 而 golden 不大時極易觸發；warn 只在「太短無法 split」時發，這個退化未被偵測。
- **evidence**：`src/health_index/health.py:76-79,326-329`
- **建議**：當 n_cal−s+1 < 下限（如 <B 或 <10）時 warn 並退保守處理或縮小評分窗。
- **提出角色**：資料科學家／統計嚴謹度

### [minor] MSPC T² 保留子空間最小 λ 仍可能很小，尾成分放大主導 T²，confidence 被尾成分綁架
- **影響**：t2=Σt_i²/λ_i，k 由 cum≥0.90 決定，最後納入的成分 λ 可能只佔幾%→1/λ 很大→微小波動被放大；clip 1e-12 對「小而非零」尾成分無作用；confidence(T²) 繼承此放大→操作域相似度被尾成分綁架；hard_gate L2 可能因尾成分噪聲誤觸。
- **evidence**：`src/health_index/detectors/mspc.py:42,44-48,58-61`
- **建議**：對 T² 保留子空間用更嚴格變異門檻或對尾成分加 ridge，或文件量化最小 λ_k 佔比。
- **提出角色**：資料科學家／統計嚴謹度

### [minor] DQI_x 門檻 = factor × support 內 trim_mean，是中心傾向量級倍數而非分位/尾機率，名目 FPR 未定義且與維度 k 耦合
- **影響**：threshold_ = 3.0 × trim_mean(dq[support])，dq 是 k 維歐氏距離（卡方尺度隨 k 增長），3×mean 不對應固定尾機率 α，k 越大有效 FPR 越漂移；不像 T²/SPE 用經驗分位，L1 域閘 FPR 隨維度漂移、跨資料集不可比。
- **evidence**：`src/health_index/detectors/dqi_x.py:126-127`；`src/health_index/config.py:26`
- **建議**：DQI_x 門檻改用 support 內距離經驗 (1−α) 分位（與 T²/SPE 一致）。
- **提出角色**：資料科學家／統計嚴謹度

### [minor] spc_blind 用 hold-out σ 而非建模 golden 全段 σ，in-sample σ 偏小使 SPC 越界率高估→spc_blind 偏保守
- **影響**：gstd = G.std()（hold-out golden），3σ 界用此 σ；SPC 真實產線用建模 golden 全段定界，這裡用 hold-out 段且若含暫態抬高 σ→exc(D) 偏小→更易判 spc_blind=True（誤認 SPC 抓不到），誇大本系統相對 SPC 的優勢；spc_blind_max=0.15 門檻對 σ 來源敏感未文件化。
- **evidence**：`src/health_index/deploy/acceptance.py:78,119-122`
- **建議**：SPC 界 σ 改用與線上 SPC 一致的建模 golden 全段，文件標明 σ 來源與門檻敏感度。
- **提出角色**：資料科學家／統計嚴謹度

### [minor] L4 is_drift 分層 KS+MMD 兩階段串聯，整體 α 未控制且為 hard_gate 繞過 FWER Holm
- **影響**：KS first-pass 用 ks_alpha、MMD 用 mspc_alpha，兩階段 AND 整體型一誤差不等於任一單獨 α；KS 已 Bonferroni、MMD 無跨維校正；is_drift 是 hard_gate L4 直接進 is_alarm 裸 OR 繞過 FWER；總覽燈走 compute_fwer=False 即此路徑→FPR 未受控、對高階漂移有盲區。
- **evidence**：`src/health_index/detectors/drift.py:226-229`；`src/health_index/health.py:220,231`
- **建議**：報告 is_drift 端到端 golden FPR；或讓總覽燈也走 alarm() 含 FWER（成本允許時）。
- **提出角色**：資料科學家／統計嚴謹度

### [minor] persistence_k 多處用 =1（acceptance/currency）量原始窗 FPR，但 health.py docstring 標「未接線」與實作不符
- （與 §1 currency 口徑、§9 持續性語義部分重疊；此筆聚焦 docstring 與實作落差）
- **evidence**：`src/health_index/deploy/acceptance.py:91,102,114`；`src/health_index/deploy/lifecycle.py:93`；`src/health_index/deploy/runner.py:79`；`src/health_index/health.py:13`
- **建議**：統一 currency 與線上口徑或明示理由；更新 health.py docstring 反映已接線。
- **提出角色**：資料科學家／統計嚴謹度

### [minor] fusion_weights/severity_scale/drift_scale/門檻全為未在 TEP 校準的「起手值」，但 acceptance gate、verdict、燈號全建其上
- **影響**：config 多處標「須 TEP 掃描定值/勿硬信」，這些值直接決定 health_index 數值、is_alarm 門檻、acceptance、verdict；未校準下 HI=0.6 門檻 + severity_scale=3.0 使 golden FPR≈0（門檻過鬆掩蓋偵測力），整套對外結論建在未校準參數上而 UI 未標示。
- **evidence**：`src/health_index/config.py:37,84,86,87,88`
- **建議**：UI/報告明確標示「參數未經 TEP 校準、為展示用預設」。
- **提出角色**：資料科學家／統計嚴謹度

---

## 11. 結果下鑽 / 時間線

### [major] 降採樣（subsampled）時相鄰窗間有未評分間隙，告警可能落在縫裡（漏報風險，多角色）
- **情境**：高維/長資料集 score_timeline step 放大到遠超 window（step=max(window, n//max_windows)）。
- **影響**：相鄰評分窗 [s,s+window) 之間隔 step-window 筆完全沒被評分的資料，短暫隱性飄移落兩窗之間就漏掉；前端只在標題加「已降採樣為 N 窗」沒警示「窗間有未評分間隙、可能漏短事件」；工程師看到全綠以為安全實際抽樣過頭→是漏報而非單純顯示問題。降採樣還改變 L4 null 取樣與窗集合，告警率/n_alarms 與驗收/線上不可比。
- **evidence**：`src/health_index/deploy/demo.py:247-255,330`；`frontend/demo_app.py:745`
- **建議**：降採樣只用於繪圖，告警率在全窗計算後再抽樣顯示；或改滑動覆蓋，並在標題明標「窗間有間隙、短事件可能漏、告警率非線上實況」。
- **提出角色**：現場工程師、資料科學家／統計嚴謹度、系統性/架構債 critic

### [major] 結果頁無 historian 趨勢：只有窗級彙總，看不到單一位號原始時序
- **情境**：RBC 指向 TIC-205，工程師想看這位號在告警窗前後原始趨勢確認是真漂還是 spike。
- **影響**：結果頁有 timeline（health）與 ymap（Ŷ vs Y）但無任何單變數/位號原始 trend；window_detail 只回 RBC 排行與均值不回逐點時序；確認根因的關鍵步驟必須離開系統去 DCS/historian，降低系統決策價值、拖慢停車判斷。
- **evidence**：`frontend/demo_app.py:308-313`；`src/health_index/deploy/demo.py:412-420`
- **建議**：下鑽時對 RBC top-k 位號畫窗前後原始時序 mini-trend，標控制限。
- **提出角色**：現場工程師

### [major] 監控特徵子集會丟掉帶飄移訊號的位號，RBC 永遠指不到被排除的真因，下鑽不提醒盲區
- **情境**：建模時 10 取 7 恰好排除日後真正飄移的位號。
- **影響**：scoring 與 RBC 都只用 bundle.x_columns，真因位號不在子集內 RBC 排行不會出現它→對著 RBC 首位查永遠查不到根因；建模時 recall 警告是對已知 drift 的，對未來未知飄移無從警示；下鑽/事件頁也沒提醒「只監控 7/10 參數」。
- **evidence**：`frontend/demo_app.py:584-593,632-637`；`src/health_index/deploy/demo.py:245,383`
- **建議**：下鑽/事件頁固定標示「監控 N/M 參數，未含：…」，提醒盲區。
- **提出角色**：現場工程師

### [minor] 門檻 slider 標明「不改實際告警」是 what-if，作業員/新手會誤以為調了就安全或功能壞掉（多角色）
- **情境**：作業員把「告警門檻試算」slider 往下拉，紅線移動，以為調好靈敏度安心去巡檢；新手拉了發現紅點不動以為功能壞。
- **影響**：_recolor 只重畫門檻線並標「what-if，不改模型實際告警」，實際告警仍由 persisted_alarm 決定；對作業員是危險的假控制（看似旋鈕其實沒接線），對新手是互動預期落空。
- **evidence**：`frontend/demo_app.py:303-305,663-667,776-783`
- **建議**：operator 視圖隱藏此 slider，或文案改更強的「僅供試算、不影響任何告警」並反白；旁加白話「正式告警門檻由系統校準」。
- **提出角色**：現場作業員、新手使用者

### [minor] RBC 排行對非告警窗也照算，工程師點任意綠窗會看到一堆肇因排名造成誤讀
- **影響**：_detail 對任何被點窗都跑 window_detail 顯 RBC top5，即使 alarm=False；健康窗 RBC 只是相對排序但仍列位號，主次不分→誤以為這些位號「有問題」。
- **evidence**：`frontend/demo_app.py:806-811,854-860`
- **建議**：非告警窗弱化或摺疊 RBC/越限表，明標「此窗正常，以下僅供參考」。
- **提出角色**：現場工程師

### [minor] window_detail 對空窗或 start>=end 無防護，下鑽越界會丟例外
- **影響**：X = ds.frame.iloc[start:end] 越界回空 DataFrame，m.t2/spe/hi.health_index 對 0 列拋 ValueError/除零；前端 _detail 有 try/except 顯「載入失敗」但函式內未 fail-loud 或回明確訊息。
- **evidence**：`src/health_index/deploy/demo.py:383-420`
- **建議**：window_detail 開頭 clamp end<=len(frame) 且 assert len(X)>=1，空窗回明確 dict。
- **提出角色**：軟體可靠度

### [minor] score_timeline region() 邊界窗採「任一 drift 即 drift」語義，視覺偏紅（已知近似）
- **evidence**：`src/health_index/deploy/demo.py:261-268`
- **建議**：文件標註邊界窗 region 語義，或用多數決。
- **提出角色**：軟體可靠度

### [minor] 結果頁 60s tick 不重評時間線（僅總覽/事件刷新），盤面數據悄悄過時
- **影響**：tick 只接 _home_metrics 與 _events_body，_run（結果頁時間線）只由 Input('screen') 觸發不吃 tick；結果頁開著當盤面看會誤把過時快照當即時。
- **evidence**：`frontend/demo_app.py:77,170,674-677,870`
- **建議**：結果頁標「快照時間」或讓 tick 也觸發重評，區分即時 vs 快照。
- **提出角色**：現場工程師

### [minor] _recolor 與 _run 同寫 timeline.figure，評分失敗後拖門檻 slider 會殘留前一製程舊時間線
- **影響**：_run 失敗回 go.Figure() 空圖且 tl-store=no_update，舊 tl-store 殘留讓 _recolor 用上一製程 points 重繪到新製程畫面。
- **evidence**：`frontend/demo_app.py:680-688,776-783`
- **建議**：_run 失敗時把 tl-store 設為空陣列而非 no_update。
- **提出角色**：軟體可靠度

### [minor] 進結果頁若 current_model 為 None 只 no_update，使用者點「查看結果」靜默失敗
- **影響**：_open_model 對 placeholder 或唯一模型被刪的製程回 no_update，畫面停原地無提示，疑似按鈕壞掉。
- **evidence**：`frontend/demo_app.py:382-395`
- **建議**：current_model None 時導到建模精靈或就地提示「此製程尚無現役模型」。
- **提出角色**：新手使用者

---

## 12. 時間戳 / wall-clock 對齊

### [major] 時間線 x 軸對 synthetic 是樣本索引非時鐘，且時間戳 str(ts) 無時區/格式保證，與 historian 對齊風險（多角色）
- **情境**：看到告警窗 [600:660] 想知道幾點發生、對應 DCS 哪段趨勢，但 X 軸只有樣本索引數字；或工程師拿紅點時間去 historian 拉同一時刻 trend。
- **影響**：x = p['ts'] or p['start']，只有資料集含 TIMESTAMP 才是 wall-clock，synthetic ts=None 退回樣本列索引；ts = str(ts_col.iloc[s.start]) 無時區無統一格式，若資料 naive/本地時間而 historian UTC 對齊差數小時；事件 detected_at 用此 str 與其他時間（_iso 帶 offset）格式不一致，MTTR 混用導致荒謬值。夜班 30 秒內對到時鐘與班別、交接說清「幾點的事」卡死。
- **evidence**：`src/health_index/deploy/demo.py:286`；`frontend/demo_app.py:654,702,712,834`；`src/health_index/deploy/events.py:28,55,123`
- **建議**：無 TIMESTAMP 時用「建模/重放起始時間 + 索引×取樣週期」推算近似 wall-clock；ts 統一輸出 ISO 帶時區；detected_at 用偵測當下真實時間，資料窗時間另存欄供 historian 對照。
- **提出角色**：現場作業員、現場工程師

---

## 13. 效能 / 擴展性

### [major] 60s tick 對每個製程重複全量重建資料集評最後一窗，無快取，製程一多即卡頓（多角色）
- **情境**：全廠掛 20-50 個製程後，總覽每 60s 觸發 _home_metrics→assets_overview→對每製程 _score_current（registry.build 重建整個 DataFrame + load bundle 指紋 verify + alarm）。
- **影響**：每 60s、每製程都重建整個資料集（高維 uci p=128 更貴），無快取無增量，製程數 × 資料集大小線性放大；多分頁各自 tick 加乘；總覽週期性卡頓/CPU 飆，與 Rule 6 線上成本上限衝突。registry 本身每次 _load 讀整個 JSON 線性過濾。
- **evidence**：`frontend/demo_app.py:77,170-172`；`src/health_index/deploy/demo.py:672-704`；`src/health_index/deploy/assets.py:45-54,79`
- **建議**：對 registry.build 與 load(bundle_path) 加 lru_cache（dataset/bundle session 內不變）；現役末窗評分加 TTL 快取，tick 只在 registry/事件變動時失效；或背景排程算好存快取 UI 只讀。
- **提出角色**：生產處長、軟體可靠度、系統性/架構債 critic、無人查的面向 critic

### [minor] window_detail 每次下鑽都 registry.build 整個資料集再切窗，無快取，與 score_timeline 重複重建
- **情境**：時間線上連點 5 個窗看肇因，每點一次就把整個 uci_gas_drift（128 維、上萬列）從頭 build + load + permutation。
- **影響**：同頁 _run 已 build 過一次同資料集，無 dataset/bundle 級快取，每互動付全量 rebuild + 指紋 verify + permutation 成本，下鑽延遲秒級。
- **evidence**：`src/health_index/deploy/demo.py:354-462,380-383,244,686`
- **建議**：對 registry.build(name) 與 load(bundle_path) 加 lru_cache，下鑽只切窗不重建。
- **提出角色**：系統性/架構債 critic、新手使用者

### [minor] 結果頁匯出 CSV 與下鑽會重新評分，慢且無進度感
- （與 §2 _dl_timeline 窗長、§13 快取重疊；此筆聚焦無進度回饋的 UX）
- **evidence**：`frontend/demo_app.py:802,967-975`；`src/health_index/deploy/demo.py:247-254`
- **建議**：匯出復用已算 tl-store 不重評；長操作給進度提示。
- **提出角色**：新手使用者

---

## 14. 架構債 / 單一真相（critic）

### [major] L5 DTW 批次維度在 demo 完全死碼：penicillin/IndPenSim 根本沒註冊進 registry
- **情境**：CLAUDE.md 明定批次基準＝penicillin/IndPenSim、判斷鏈含 L5 DTW，但使用者在第①關只看得到連續資料集，永遠選不到批次。
- **影響**：registry._BUILDERS 只註冊 9 個連續製程，無 penicillin/indpensim；batch_dtw.py 從未進入 health.py/demo.py/demo_app.py 評分路徑，health.py subscores 只融合 L1/L2/L4。「五維 MECE 判斷鏈」在可跑 demo 只有三維，L5 是規格書維度但 runtime 不可達；對外宣稱「五維/批次支援」但 DoD 批次驗證在 demo 無法執行＝未誠實揭露 demo-vs-spec gap。
- **evidence**：`src/health_index/adapters/registry.py:127-137`；`src/health_index/health.py:146,151,199`；grep batch_dtw 僅命中 config/indpensim/app.py
- **建議**：在 catalog/registry 註冊 indpensim builder 並把 L5 接進批次路徑，或在文件/UI 明標「本 demo 僅連續製程 L1/L2/L4，批次 L5 為離線能力」。
- **提出角色**：系統性/架構債 critic

### [major] lifecycle.ModelRegistry 與 assets.AssetStore 是兩套平行、互不知情的模型持久化系統，命名不相容
- **情境**：lifecycle.py 自帶目錄式 per-product 模型庫（{product}.joblib），demo/UI 走 assets.AssetStore 版本化命名（{process_id}__v{N}.joblib），兩者互不讀取。
- **影響**：assess_model_currency/rebuild_model 完全未被 UI 呼叫＝死碼，即便有人想接，命名不相容會載到錯檔；「模型老化提醒」後端齊備卻結構性接不上，是孤島架構債。
- **evidence**：`src/health_index/deploy/lifecycle.py:31-32,131-132`vs`src/health_index/deploy/demo.py:638-639`；`src/health_index/deploy/assets.py:11`
- **建議**：二擇一——刪 lifecycle.ModelRegistry 改讓 assess/rebuild 直接吃 AssetStore versioned bundle，或統一命名契約；先 surface 不要兩套並存。
- **提出角色**：系統性/架構債 critic

### [minor] bundle/lifecycle docstring 宣稱「created_at 須 git 時間權威」，但 runtime UI 全用 datetime.now()，不變式名實不符
- **影響**：docstring 把全域 CLAUDE.md commit-time 治理規則錯誤搬進 runtime API 契約，runtime 用 wall-clock 是對的但 docstring 誤導後續維護者可能花力氣「修正」或審查時把正確 now() 當違規。
- **evidence**：`src/health_index/deploy/bundle.py:7,98`；`src/health_index/deploy/lifecycle.py:115`；`src/health_index/deploy/demo.py:161`vs`frontend/demo_app.py:587,996,1013,1072`
- **建議**：docstring 改「created_at 由呼叫端提供（runtime 用 wall-clock；離線建構腳本用 git 時間）」。
- **提出角色**：系統性/架構債 critic

---

## 15. 測試覆蓋 / 文件落差 / 版本相容（critic）

### [blocker] 產品 UI（frontend/demo_app.py）零測試覆蓋，唯一前端測試測的是另一支已棄用的 app
- **情境**：任何人改 demo_app.py 的 callback（路由、建模、評分、事件開案、刪除製程），CI 全綠也不代表 UI 沒壞。
- **影響**：tests/test_frontend.py import 的是 `frontend.app`（舊 FastAPI+Dash 殼），實際產品 UI 是 demo_app.py（近 1100 行、40+ callback）；grep demo_app 命中 0 個 tests；所有純函式（_timeline_fig/_golden_fig/_asset_card/_home_metrics 上色與分母）與 callback 副作用都無回歸保護；違反 Rule 9 與「綠燈才 commit」DoD（綠燈是假綠）。
- **evidence**：`tests/test_frontend.py:17`；`frontend/demo_app.py` 全檔無對應測試
- **建議**：新增 tests/test_demo_app.py：對 _timeline_fig/_golden_fig/_asset_card 做鑑別測試（drift 窗紅、golden 窗綠、門檻線值），對 _home_metrics 分母與 _build features 判定做單元測試；或把純繪圖函式抽出便於測。
- **提出角色**：無人查的面向 critic

### [major] joblib bundle 只 pin sklearn>=1.1 無上限，跨版本載入靠指紋 verify 拒載——升 sklearn 後所有已建模型集體拒載而非優雅降級
- **情境**：demo 評估跨數週，期間 pip 升級 sklearn，重開 app 後總覽對每製程 load bundle→verify 指紋重算與存檔不符→BundleIntegrityError→全部製程顯「資料源不可得」灰燈。
- **影響**：verify rtol=1e-6 比對指紋，sklearn 升版若 GPR/MinCovDet/PLS 數值漂移 >1e-6 即拒載；load 失敗被 except 吞成 data_unavailable 或 no_update；UI 把「版本漂移拒載」與「資料源不在 registry」混成同一灰態，使用者無從得知該重建模型還是下載資料；疊加 temp 重開機清空，跨天/跨環境 demo 幾乎注定「全廠變灰」。
- **evidence**：`src/health_index/deploy/bundle.py:65-78`；pyproject sklearn>=1.1 無上限、joblib 未 pin；`src/health_index/deploy/demo.py:507,681`；`frontend/demo_app.py:25`
- **建議**：pyproject 對 sklearn/joblib 加相容上限（如 sklearn>=1.1,<1.7）；UI 把 BundleIntegrityError 與 FileNotFoundError 分成不同狀態文案；模型存非 temp 持久目錄。
- **提出角色**：無人查的面向 critic

### [major] imputation 通道在 demo/registry 建模路徑完全無法觸及，真實缺值資料只會 fail loud 而非進入文件承諾的假陰性風險路徑
- **情境**：工程師接真實產線資料（X 有缺值），預期照 from_frame docstring 用 impute='median'/'ffill'，但整個 demo/registry/UI 沒有 impute 入口，含 NaN 資料一律 ContractError 崩在 fit 前。
- **影響**：from_frame 有完整 impute 與假陰性警告（設計核心誠實邊界），但 build_and_save_model/build_model_for_process/score_timeline 全走 registry.build，from_frame 通道沒接到 registry，UI 也無上傳任意表入口；已實作的假陰性防護是死路徑只在單測走到；真實缺值資料無法經產品流程接入，與「架構預留真實產線 adapter 接口」context 落差。
- **evidence**：`src/health_index/adapters/dataframe.py:168-184,247-257`；`src/health_index/adapters/registry.py:127`
- **建議**：registry/demo 暴露 from_frame 通道（上傳表 + 角色映射 + impute 選擇），或文件明標「內建集無缺值，真實缺值接入需走 from_frame，UI 暫不支援」。
- **提出角色**：無人查的面向 critic

### [major] 資料集下拉提供 uci/ccpp/steel 等需先下載的集，未下載時選了直接報後端 exception（含本機路徑）給使用者
- **情境**：新使用者第①關下拉選「UCI 氣體感測器陣列漂移」但 data/uci_gas_drift 沒下載，畫面直接吐 FileNotFoundError 原文（含下載 URL 與本機絕對路徑）。
- **影響**：available_datasets() 回全部 9 個不過濾「資料是否就緒」；_on_dataset except 把 e 直接塞進 UI 文案，洩漏本機路徑（輕度資訊揭露），開箱即用體驗破裂。
- **evidence**：`frontend/demo_app.py:117,231,488-489`；`src/health_index/deploy/demo.py:33-35`；`src/health_index/adapters/uci_gas_drift.py:101-106`
- **建議**：下拉以「資料是否就緒」過濾或對未就緒集標灰顯「需先下載」（catalog 增 requires_download 旗標 + 預檢）；異常訊息不回吐路徑。
- **提出角色**：無人查的面向 critic

### [minor] _score_current/monitoring_overview 對 X 取最後一窗評分，當資料列數 < 窗長時用全段，未驗證足夠 fit 偵測器→極短資料源給無意義健康燈
- **影響**：Xw = X[-window:] if len(X)>=window else X，len(X)<window 直接用全段無「窗長 vs 偵測器有效窗長（n≳p）」校驗；配合特徵子集可能在 n<p 區跑 health_index，總覽顯不可信但綠的健康燈且無 FPR gate 把關。
- **evidence**：`src/health_index/deploy/demo.py:502-506,676-682`
- **建議**：對 len(Xw) < max(window, k_effective) 時回 status='insufficient'，UI 標「資料不足以評分」而非綠燈。
- **提出角色**：無人查的面向 critic

---

## 16. 無障礙 / i18n / 色彩語意 / 匯出列印

### [major] UI 全程硬編中文無 i18n 層，且狀態只靠顏色（紅綠色盲不可區分），<html> 無 lang
- **情境**：紅綠色盲（約 8% 男性）看總覽燈與時間線，健康綠 #16a34a 與告警紅 #dc2626 在色盲模擬下接近同色且形狀標記相同；非中文使用者完全無法操作。
- **影響**：卡片/banner 狀態僅 ●+顏色文字（色盲下 ● 形狀不變、顏色難辨）→可能把告警誤判為健康，違反 WCAG 1.4.1（不可只靠顏色傳達）；全檔字串硬編中文無 gettext/語言切換；index_string <html> 無 lang="zh-Hant"，螢幕報讀器無法判定語言。
- **evidence**：`frontend/demo_app.py:29-31,163,177,34-40,657`
- **建議**：狀態同時用形狀/圖示編碼（健康●、告警▲或加 ⚠）；index_string 補 lang="zh-Hant"；字串集中為可替換字典為 i18n 預留。
- **提出角色**：無人查的面向 critic

### [minor] 匯出 CSV 無 BOM/編碼宣告，中文 top_cause/位號在 Excel 亂碼；無列印/PDF 視圖，合規月報缺口（多角色）
- **情境**：處長用 Excel 開 incidents.csv，top_cause「品質飄移：X→Y 殘差超界」與中文位號變亂碼；想列印月度合規報表，系統只有逐窗/逐事件 CSV，無列印樣式或 PDF。
- **影響**：csv.DictWriter 產 UTF-8 無 BOM，Windows 繁中 Excel 以 ANSI/Big5 解讀→亂碼；index_string <style> 無 @media print，列印會把閃爍動畫/按鈕/深色背景全印出；處長無法直接產對上/對稽核的正式月報，需人工彙整 CSV。
- **evidence**：`src/health_index/deploy/demo.py:577-604`；`frontend/demo_app.py:34-40,961-975`；`docs/frontend_design_guide.md:104,117,131`
- **建議**：CSV 加 utf-8-sig BOM；index_string 補 @media print 隱藏按鈕/動畫白底；提供列印友善視圖或 server 端 PDF 月報模板（KPI/MTTR/事件彙總/ROI 假設透明）。
- **提出角色**：生產處長、軟體可靠度、無人查的面向 critic

### [major] 沒有 PDF 月報，匯出只有逐窗 CSV，處長要的合規月報缺口未補
- （與上一筆「匯出列印」部分重疊，此筆獨立列出 PDF 月報缺口的 blocker 級採購訴求）
- **影響**：全程式碼無任何 PDF 產生（無 reportlab/weasyprint），匯出僅 incidents_to_csv/timeline_to_csv 逐窗逐事件原始列非彙總月報；design guide §6/§7 明列 PDF 月報為處長剩餘 blocker。
- **evidence**：`src/health_index/deploy/demo.py:577-604`；`frontend/demo_app.py:961-975`；`docs/frontend_design_guide.md:117,131`
- **建議**：提供月報模板一鍵 PDF，或明確列入導入期交付。
- **提出角色**：生產處長

---

## 17. 可用性 / 新手引導 / 行動裝置

### [blocker] 沒有任何真聲音告警，紅燈只會閃不會響（夜班獨自監看核心缺口）
- **情境**：凌晨 3 點背對螢幕巡檢或打盹，製程開始飄移、首頁 banner 亮紅閃爍，但沒看螢幕，回座可能已過 30 分鐘。
- **影響**：全 UI 找不到任何 audio 元素或 JS 嗶聲，告警只靠 CSS 動畫 pg-flash（程式註解直接寫「告警閃示（聲音替代，作業員）」）；設計史自承 P0「無聲音→不戳不亮，三班現場不可用」；夜班最核心的「叫不叫人」判斷完全失效，飄移無人即時反應，正是這套系統要防的隱性事故會被漏掉。
- **evidence**：`frontend/demo_app.py:37-38,178`；`docs/frontend_design_guide.md:89,114`
- **建議**：加 `<audio>`/瀏覽器 Notification + 可選外部 alerting webhook；告警未 ACK 時持續鳴響。
- **提出角色**：現場作業員（凌晨3點夜班獨自監看）

### [major] 角色預設是「工程師」不是「作業員」，夜班/新手一進來滿屏術語（多角色）
- **情境**：夜班開機進系統預設停在工程師視圖，看到一堆 GSI/T²/SPE/p-value，30 秒內判斷不了該不該叫人；新手一進來就吃滿術語。
- **影響**：role-sel value 寫死 'engineer'，作業員必須自己知道右上角有個小 radio 要切；白話視圖（去術語）專為作業員做但預設不給他，等於白做；新手「3 秒測」失敗被勸退。
- **evidence**：`frontend/demo_app.py:86`
- **建議**：預設 value='operator' 或依登入身分決定；切換做得更顯眼；工程師術語加 tooltip。
- **提出角色**：現場作業員、新手使用者

### [major] 結果頁時間線本身不分角色，作業員仍看到 GSI/SPE/T² 術語（藏術語只藏在下鑽卡）
- **情境**：作業員從製程卡「查看結果」進健康指標頁，hover 紅點 tooltip 跳「SPE 0.83 GSI 1.2」，摘要寫「主因 xmeas07」，看不懂。
- **影響**：只有窗下鑽 _detail 依 role 切白話卡，結果頁主畫面 _run 完全不看 role：timeline hovertemplate 直接顯 SPE/GSI、worst_line 顯術語、③品質維度寫「X→Y 殘差超界」；藏術語只藏在下鑽卡，主畫面漏滿地，white-box SOP「藏術語乾淨」在主畫面破功。
- **evidence**：`frontend/demo_app.py:659,750-752,759-764,674-678`
- **建議**：_run 也吃 role-sel，operator 模式下 hover/摘要改白話、隱藏 SPE/GSI 數字。
- **提出角色**：現場作業員

### [major] 結果頁與首頁沒有 ACK/消音按鈕，無法停掉一直閃的紅燈（告警疲勞）
- **情境**：同一飄移持續半小時首頁一直紅閃，已看到也叫了人，想暫時消音/標記「已知處理中」卻沒地方按。
- **影響**：ACK 只存在事件頁的事件卡，首頁 banner 與結果頁完全沒有 ACK/snooze/silence；閃示無條件只要 plant_status=='alarm' 就閃，ACK 後也不停閃；已認領告警仍持續視覺轟炸→告警疲勞，作業員學會無視紅閃，下次真事故也不理。
- **evidence**：`frontend/demo_app.py:178`；`src/health_index/deploy/demo.py:708-711`
- **建議**：首頁/結果頁加 snooze/ACK；plant_status 區分「未認領告警」vs「處理中」，ack 後降級閃示。
- **提出角色**：現場作業員

### [major] 白話 SOP 把分機號碼當佔位字「分機填於 SOP」，真要叫人時沒電話/升級路徑（多角色）
- **情境**：紅燈確認可信，白話卡叫「依 SOP 通報工程師（分機填於 SOP）」，凌晨不知道打給誰。
- **影響**：hard-code 佔位提示，沒有任何欄位承載值班工程師聯絡方式/升級路徑，也沒連到 severity 決定「該不該半夜叫人」；SOP 最後一個動作（通報）斷在最關鍵處。
- **evidence**：`frontend/demo_app.py:827-828,837`
- **建議**：製程/區域設定加「值班升級聯絡」欄（如 tags 旁放 contacts.json），依 severity 顯示對應分機/Line 群，critical 才提示叫人；無則隱藏該句而非顯佔位。
- **提出角色**：現場作業員、現場工程師

### [major] 精靈「下一關」零驗證，可一路空點到建模/完成而毫無提示
- **情境**：第一次用直覺狂點「下一關」想先看全貌，或第②關沒選 golden、第①關只剩 1 個參數仍能進第④關。
- **影響**：_wstep 只做 min/max 步進，完全不檢查當前關必填項（golden 是否選、子集≥2、資料源是否載入成功）；新手只在按「建立模型」那一刻才收紅字，前三關點擊全空轉，靠「撞錯誤」反推流程。
- **evidence**：`frontend/demo_app.py:424-431,590`
- **建議**：btn-next 每關做前置檢查（golden 已選/子集≥2/資料源已載入），未過則 disable 或就地紅字。
- **提出角色**：新手使用者

### [major] golden RangeSlider 預設 [0,600] 寫死，未必落在乾淨基準段；「不動預設」可能直接撞 FPR FAIL（多角色）
- **情境**：新手第②關不動 slider 直接「下一關→建立模型」期待「預設就能用」；或資料集 n<600、建議基準段在後段。
- **影響**：layout 初始 golden-range value=[0,600]，_on_dataset 雖回填建議段但只在切 dataset 時觸發；_golden_preview prevent_initial_call=True 首次未動任何 input 不觸發→_build 退路落回 [0,600]；若選的連續區間跨非平穩尾段，驗收 FPR FAIL 物理擋存檔，使用者只看到「誤報率過高」不知是自己沒挑對段；n<600 時銜接全靠 callback 執行序。
- **evidence**：`frontend/demo_app.py:247,478-507,544,588,607-614`
- **建議**：_golden_preview 改非 prevent_initial_call，或 _build 用 golden_suggested 當退路不 hardcode 600；預設套用建議段並在 readout 標明。
- **提出角色**：生產製程工程師、新手使用者、軟體可靠度

### [major] 手機/窄螢幕只折疊網格，操作按鈕仍桌面尺寸難點按，多處表格/grid 溢出（多角色）
- **情境**：現場巡檢/處長外出用手機看盤，製程卡一排小按鈕（查看/更換/歷史/刪除）擠在一起，手指難點還易誤點刪除；歷史頁版本表、下鑽 mspc 表、ROI 卡橫向溢出。
- **影響**：RWD 只有一條 @media(max-width:640px) 把 pg-grid 改單欄；卡片固定 width 230px、mini_btn padding 小、事件 KPI tiles repeat(5,1fr)、寬表格 width:100% 在觸控不友善；slider/dropdown 未針對觸控放大；設計史承認手機僅「需實機點擊驗證」未做；檔頭自承「UI 視覺/點擊未在本環境渲染驗證」。
- **evidence**：`frontend/demo_app.py:8,36,134-136,157,62,883-884,1048`；`docs/frontend_design_guide.md:114-115`
- **建議**：觸控目標 ≥44px、按鈕換行堆疊、危險操作分離、表格 overflow-x、補多斷點；實機驗證事件頁/歷史頁/下鑽表格。
- **提出角色**：現場作業員、生產處長

### [major] 首屏空狀態文案要求新手先懂「製程 vs 監控模型」差異才知道按哪個
- **情境**：全新環境零製程第一次打開總覽。
- **影響**：空狀態給兩顆語意高度重疊的按鈕（btn-newproc/btn-new），「製程」「監控模型」「熱插拔」「佔名」都是內部術語無教學；多數新手只想「建一個能看的監控」應導向 btn-new，但兩顆並列且「新建製程」在左更顯眼→可能誤按建出一堆 placeholder 不知如何接模型。
- **evidence**：`frontend/demo_app.py:109-110,112-123,200-201`
- **建議**：空狀態只給一顆主 CTA（新建監控模型），「新建製程」降為次要/進階，或加一句「不確定就按這顆」。
- **提出角色**：新手使用者

### [major] 大量未解釋術語塞滿介面（GSI/T²/SPE/RBC/conformal/RI/MSPC/campaign/re-entry；註：RI 不在 live code——已被 CP 刻意取代，soft_sensor.py:3-6，且新精靈明定不得稱 RI），新手讀不懂
- **影響**：預設角色就是工程師，結果頁與 window-detail 直接灑出術語，雖有 operator 視圖會藏但預設不是它且切換入口小；golden 預覽圖軸名「偏離度(σ)」、catalog「campaign」「re-entry」都未在 UI 內解釋→3 秒測失敗。
- **evidence**：`frontend/demo_app.py:86,310-311,854-861`；`src/health_index/deploy/catalog.py`
- **建議**：預設角色設 operator；工程師術語加 tooltip/info 圖示；首次進結果頁給一句白話導讀。
- **提出角色**：新手使用者

### [minor] 沒有任何交接班/值班紀錄在監控盤，交接摘要藏在事件頁
- **情境**：早上 6 點交班給白班，要一句話講清楚夜裡發生什麼、現在什麼狀態、誰處理到哪。
- **影響**：唯一交接摘要在 events_body 需切到事件頁，且只有計數（open/ack/closed/誤報/MTTR）沒有時間軸式班別內發生序列與自由文字班誌；首頁/結果頁皆無交接入口。
- **evidence**：`frontend/demo_app.py:877-880`
- **建議**：首頁加交接卡（本班告警序列 + 自由班誌欄），切班時可匯出/簽核。
- **提出角色**：現場作業員

### [minor] 建模成功後仍需手動「下一關→查看健康指標」兩跳、兩個措辭的 CTA 指同一目的地
- **影響**：build-result 顯「按下一關查看健康指標」，完成關另有「查看健康指標→」按鈕，要先按下一關到第⑤關再按，多一跳措辭不一致。
- **evidence**：`frontend/demo_app.py:273-283,646`
- **建議**：建模成功後直接在 build-result 放「查看健康指標→」主按鈕，或自動跳第⑤關。
- **提出角色**：新手使用者

### [minor] 第①關建議用「自動挑乾淨段」最安全，但藏在第②關第三個 radio 且需多按一次「套用」
- **影響**：三模式 radio 預設停在 range，auto 是第三個選項；選 auto 還要再點「套用自動挑選」才會算，否則 spec='auto' 但 auto-runs 為空、預覽圖空白像壞掉；新手很可能切 auto 後直接下一關以為已選好。
- **evidence**：`frontend/demo_app.py:241,256-260,542-563,566-574`
- **建議**：預設模式設 auto 並進關時自動執行一次，或「套用自動挑選」改選 radio 即觸發。
- **提出角色**：新手使用者

### [minor] 錯誤訊息把後端 exception 原文直接吐給使用者（多處）
- **影響**：建模失敗/模擬失敗/載入歷史/詳細指標/資料集載入多處 except 直接 f'❌…：{e}' 把 Python 例外（含欄名清單、堆疊、joblib/registry 原文）塞進 UI，新手看到天書、不可行動。
- **evidence**：`frontend/demo_app.py:489,604,688,805,1028`
- **建議**：包友善訊息 + 「詳情」可展開原文；常見錯誤（golden 太短/資料源不可得）給具體修法。
- **提出角色**：新手使用者

### [minor] _build except 捕捉所有 Exception，FPR gate 與真正錯誤無法區分
- **影響**：把治理性 ValueError（可恢復，請改選）與系統性 RuntimeError（並發損壞，需重來）都顯成同一句紅字，使用者無從判斷該改輸入還是重試；FPR 過高是 saved=False 不走 except。
- **evidence**：`frontend/demo_app.py:594-604`
- **建議**：區分 ValueError（輸入問題，提示改選）與其他（系統錯誤，提示重試/聯絡）。
- **提出角色**：軟體可靠度

### [minor] _on_dataset 載入失敗時 feature-sel 清空但下游 _build 仍可被觸發，雙重失敗不鎖步
- **影響**：dataset_overview/preview 失敗回空值顯紅字但不阻止走到步驟4 按建模，_build 再撞同樣失敗；feature 空集合讓 features=None（全用）語意含糊。
- **evidence**：`frontend/demo_app.py:483-489,510-514`
- **建議**：資料載入失敗時 disable「下一關/建立模型」或在步驟1 即攔。
- **提出角色**：軟體可靠度

### [minor] 監控參數子集「至少 2 個」限制只在建模時/readout 提示，第①關 checklist 不阻擋；全選=全用語意不透明
- **影響**：feature-readout 顯「⚠至少需 2 個」、_build 也擋，但第①關「下一關」不擋，帶無效子集走過第②③關到第④關才被拒；全選與「None（全用）」等價邏輯對新手不透明。
- **evidence**：`frontend/demo_app.py:510-514,590-593`
- **建議**：<2 時 disable「下一關」；checklist 旁常駐說明全選即監控全部。
- **提出角色**：新手使用者

### [minor] 60s 自動刷新 + 自動開事件可能在新手不知情下產生告警事件
- （與 §4「_run 讀路徑寫事件」同根因，此筆從新手認知落差視角）
- **evidence**：`frontend/demo_app.py:77,701-711`
- **建議**：首次自動開案時在結果頁明示「已自動開立 N 件事件，可到事件頁處理」。
- **提出角色**：新手使用者

### [minor] _route/screen Store 多 callback 以 allow_duplicate 寫入，快速連點或同回合多鏈觸發路由競態
- **影響**：_open_model/_enter_wizard/_enter_history/_route/_build 都寫 screen，同回合兩鏈同觸發最終值不確定；pattern callback 在 registry 重繪後 n_clicks 重置可能誤觸發；偶發跳錯屏（想看結果卻進精靈）。
- **evidence**：`frontend/demo_app.py:370-379,382-411,446`
- **建議**：集中路由到單一 callback，或用 dcc.Location/明確 routing store 化解多寫者。
- **提出角色**：軟體可靠度

### [minor] pattern-matching 按鈕在 home-metrics 重繪後 n_clicks 歸零，tick/refresh 重繪可能誤觸發或丟失動作
- **影響**：_home_metrics 每次重建整個 children（含 open-model/build-cta/del-proc 按鈕），重繪後 component 重建讓既有 n_clicks 流失；「點了 A 卻因重繪丟失」導致動作沒反應；del-proc 無二次確認誤點即軟刪。
- **evidence**：`frontend/demo_app.py:156,170-202`
- **建議**：刪除加確認；總覽用 partial update 或穩定 key 避免全量重繪丟 n_clicks。
- **提出角色**：軟體可靠度

### [minor] _event_action 失敗被靜默 except 吞掉，使用者按關閉/認領無回饋
- （與 §8「持久化異常靜默吞掉」同根因，此筆聚焦事件操作無回饋）
- **evidence**：`frontend/demo_app.py:951-957`
- **建議**：捕捉後把錯誤訊息寫到 status 區塊 surface。
- **提出角色**：軟體可靠度

### [minor] 建模成功訊息只列前 6 個監控參數，10取7 時看不全且無 tooltip
- **evidence**：`frontend/demo_app.py:640-643`
- **建議**：用 title=完整清單 的 tooltip，或顯「監控 7 參數」可展開。
- **提出角色**：生產製程工程師

### [minor] CSV 匯出未指定編碼/BOM，含中文在 Excel 亂碼（Windows 環境）
- （與 §16「匯出 CSV 無 BOM」同根因，此筆從可用性視角）
- **evidence**：`src/health_index/deploy/demo.py:584-589`；`frontend/demo_app.py:961-975`
- **建議**：dcc.Download 加 utf-8-sig（BOM）。
- **提出角色**：軟體可靠度

---

## 18. 部署 / 持久化

### [minor] registry 與模型存於系統 temp，重開機資料全失，demo 評估期跨天會「全廠清空」（多角色）
- **情境**：處長花一週評估建了幾條製程、累積事件與稽核，機器重開或 temp 被清，registry.json/incidents.json/所有 .joblib 全消失。
- **影響**：_MODELS_DIR=gettempdir()/health_index_demo_models，incidents/registry/bundle 全放此；對「季度評估試點」評估資料不持久破壞處長對系統可靠度/稽核保存的觀感。
- **evidence**：`frontend/demo_app.py:25-27`；`docs/model_registry_design.md:101`
- **建議**：評估部署改用持久路徑（非 temp），說明正式版用 DB/受控檔案系統 + 備份。
- **提出角色**：生產處長、無人查的面向 critic（與 §8 temp 資安、§15 sklearn 漂移高度相關）

---

## 依嚴重度統計

| 嚴重度 | 數量 |
|---|---|
| blocker | 12 |
| major | 49 |
| minor | 66 |
| **合計（去重後）** | **127** |

> 原始 204 筆經合併「同一根因、不同角色」後得 127 筆獨立問題。最高頻重複根因：lifecycle 未接 UI（7+ 角色）、window 未存 bundle（4 角色）、無 auth/RBAC（多）、actor 可冒名/audit 可竄改（5+）、刪製程無確認（5）、_run 讀路徑寫事件（7）、健康燈灰態語意混淆（2）、60s tick 無快取（4）、降採樣告警落縫（3）。

## 依 area 分節統計（去重後）

| area | 數量 |
|---|---|
| 模型時效/生命週期 | 8 |
| 評分窗長/bundle 單一真相 | 4 |
| 驗收/acceptance | 11 |
| 事件/告警閉環 | 14 |
| ROI/KPI/MTTR | 3 |
| 總覽/banner/健康燈 | 5 |
| 治理/權限/稽核 | 10 |
| 資安/IT 整合 | 13 |
| 軟測量 Y/品質維度 | 11 |
| 偵測器/統計嚴謹度 | 13 |
| 結果下鑽/時間線 | 10 |
| 時間戳/wall-clock | 1 |
| 效能/擴展性 | 3 |
| 架構債/單一真相 | 3 |
| 測試覆蓋/文件/版本相容 | 5 |
| 無障礙/i18n/匯出列印 | 3 |
| 可用性/新手引導/行動 | 21 |
| 部署/持久化 | 1 |

## 最該先修的 blocker / major Top 10（2026-06 快照；#4 window 與 #8 lifecycle 已在 redteam_verified_issues.md 降級為 major 並修正後果描述——控制限/PCA basis 於 fit 時凍結、不受評分窗長影響，實害限事件時間對齊與口徑）

1. **[blocker] 全系統零認證/授權（§7）** — 採購硬否決項，任何人可刪製程/關事件/竄改稽核；IT 不放行。
2. **[blocker] 稽核 log 可竄改 + actor 可冒名（§7）** — 合規問責的根基，比沒稽核更危險（營造可信假象）。
3. **[blocker] joblib.load RCE + temp 共用目錄（§8）** — 同機任一使用者可放惡意 .joblib 取得 RCE，現實可達。
4. **[blocker] window 未存進 bundle（§2）** — 建模/驗收/燈號/時效用兩三種窗長，治理 gate 與盤面脫鉤，下游肇因/時間段全錯。
5. **[blocker] 驗收建「前半 golden」但部署「全 golden」（§3）** — 簽核依據量錯對象，PASS/FAIL 對上線模型不具統計效力。
6. **[blocker] 驗收 gate 完全不含 Y/品質維度（§3）** — 含品質飄移的模型照樣判 PASS 上線。
7. **[blocker] demo/registry 路徑永不建 dist_health（§9）** — 多維品質分布維度全程失效、假綠，AVM 軟測量核心價值缺席。
8. **[blocker] lifecycle.assess_model_currency 完全未接 UI（§1）** — 7+ 角色提出，基準老化偵測在產品面缺席。
9. **[blocker] 產品 UI 零測試覆蓋（§15）** — 唯一前端測試測的是已棄用 app，違反 Rule 9 與綠燈 DoD，所有改動 silently 壞掉。
10. **[blocker] 沒有真聲音告警，紅燈只閃不響（§17）** — 夜班「叫不叫人」判斷失效，正是系統要防的隱性事故會被漏。

> 補充：以下 major 雖未進 Top 10 但影響範圍極廣，建議緊接處理：FPR gate 圈平穩段 p-hacking（§3）、recall gate 只警告不擋（§3）、_run 讀路徑寫事件 CQS 違反（§4，7 角色）、健康燈灰態混淆使資料源掉線不變色（§6）、刪製程無二次確認（§7，5 角色）、incidents.json 非原子寫 + 無鎖（§8）、MTTR 時間軸混用算荒謬值（§5）、L5 DTW 批次維度死碼（§14）、sklearn 無上限升版後模型集體拒載（§15）。

## 下一步

-（2026-06 當時建議，已被取代）先封堵 blocker：auth/RBAC + 稽核不可竄改 + 模型目錄移出 temp（一組導入前置 IT gate）。→ 2026-07 定調：資安/RBAC/並發鎖標「PoC 後」（見 redteam_verified_issues.md）；現行優先序＝9 步新精靈管線 INC-1~INC-5（INC-1 已完成，5052b8a）與風險稽核開放缺口（SMTP 串接暫緩、G2/G3 X 歸因、G3 適用域、headless runner、數值護欄、TDD-3），見 docs/devlog/2026-07-03.md。
- window 凍進 bundle 並讓所有 score/overview/currency/驗收讀同一窗長（解一處連鎖修六處不一致）。
- 把 lifecycle 接上 UI 並統一 0.05/0.3/persistence_k 三套門檻口徑（時效治理閉環）。
