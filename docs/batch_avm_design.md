# batch-AVM 設計：Golden 兩關卡 + 多機台/時間 + 小 n 可信度 + 隱性 Y 漂移監控

> 狀態：已過**獨立整合紅隊**（3 視角 go_with_fixes，wf_a8bb680b）+ DQIy 網路深查（wf_a39e9f45）。
> 本文為承載性設計的版本化真相；實作以 TDD 逐步落地（見 §10 順序與狀態）。
> 凡標 **NOT VERIFIED** 者須先過 `docs/literature_crossref.md` VERIFY 方可作已驗證引用（Rule 12）。

## 1. 範圍與定位
- **新增、可加性路徑**：每個生產批 P_i = 一筆 AVM 觀測；`X* = 每批[製程參數×統計指標]` 特徵向量、`Y` = 每批單一量測。
- 既有 **raw-X → GPR soft-sensor** 與五維判斷鏈（L1 DQI_x / L2 T²·SPE·GSI / L3 soft-sensor+CP / L4 漂移 / L5 DTW）**維持不動**（Rule 3）。
- `features.py` 的 `[param×stat]` 目前為 advisory、**結構性禁入偵測路徑**；新路徑是**獨立** pipeline，刻意把 X* 餵給映射模型，並須加結構測試確保它不回主 HealthIndex/score_timeline。

## 2. 資料模型（多機台 × 多時間）
- `machine_id`：加入 `interface.py` RESERVED（Option A，使用者確認）——**僅作產出源頭標記（provenance/選取）**，非偵測器輸入；additive、向後相容（現有資料集不用此名）。
- `config` 為 frozen → 新參一律新增 dataclass 欄位（additive），不可執行期改。
- `generate_fleet()`：新 registry builder（比照 `_build_tep_tp` fail-loud 慣例），以 `seed + 每機台系統偏移`（M-2）合成多機台；各機台各自起始日期（`timestamp` 已 datetime）。原 `generate()` 不動。

## 3. Golden 兩關卡「看圖選，不盲挑」
- **關卡1 Temporal**：單一參數在**批內製程時間 0–100%** 的多批折線疊圖；每批**統一取中間 X%** trim；中位/離群標示；CheckBox/List 勾選納入/剔除批次。
- **關卡2 Indicator**：每批 `[param×stat]` 在**批次生產時間（舊→新）**的 run 圖；一 (param×stat) 一張，10×8=80 小倍數；**惰性計算**（前端只顯示可選清單，按「轉換計算」後端算並回 % 進度）；預設展開 mean+std。
- ⚠ **紅線**：關卡2 為**逐變數邊際**圖，**無法顯示相關結構漂移**（部分漂移仍邊際可見，如變異顯於 *_std）。隱性多變量漂移由結果頁的 GSI/T²/SPE(對 X*) 負責，且**僅限保留 PCA 子空間(pca_var_explained=0.90)+SPE 殘差、且只見存活[param×stat]標量間的跨特徵共變異，非批內跨感測共變異（已被聚合丟棄）**。→ **聚合是綁定約束；批內 covert drift 仍歸 raw-X→L2 SPE；GPR-vs-PLS 是次要問題。**

## 4. 特徵 X*
- 統計集：現有 6（mean/std/min/max/range/median）+ `count` + `cv` + 自訂 hook。`count` 只走 DQIx/原生格，**不得**進 `segment_statistics` stats=（既有 guard 會 ValueError）。`cv=std/|mean|` 加 |mean| floor。
- **min/max/range（修訂：不再一律移除）**：極值統計會隨批點數 n 增長（E[max]~√(2 ln n)，**對數**依賴 → 對 n 變動極不敏感）。**連續製程、同產品、反應時間相近 → n 近似常數 → 偏差可忽略** → **保留為 X\* 特徵 + n 一致性閘**（`count`→DQIx 標記脫離常態批；跨機台/取樣率差/中止批 → 改 fixed-p 分位 p05/p95 + IQR 或排除）。
- **極值雙用途（MECE）**：(A) 製程漂移特徵——單點尖刺造成的極值是干擾；(B) **sensor 健康/資料品質**——劣化=尖刺/飽和/卡值/噪聲上升，正好顯於極值與變異。→ out-of-family 極值**同時**當 **DQIx/sensor-health 訊號**（檢查/更換感測器）。
- **resample**：X* 走**原生格**（mean/median 長度不變、count 先算餵 DQIx）；resample 僅**畫圖層**（疊圖中位/分位帶）；DTW/軌跡級預設不開（L5 離線）。

## 5. 映射模型（step 7）
- **GPR + PLS + split-CP，零新模型**（模型分析 wf_c8367a17 + 雙紅隊）。X* 高維共線 → **PLS 主力**（chemometrics、signed loadings/VIP 供 RBC；X-score T²/SPE 自帶域閘）；GPR 於高維需先 PLS/PCA 降維。off-support 由 T²/GSI 閘（A13）+ 原生變異確定性處理。RF/GBM/XGB/KRR/SVR/MLP 皆 SKIP（樹類 off-support 假性平靜、違反 DoD#2）。
- X* 的 GSI/T²/SPE 用**新偵測器實例 + `highdim.py` PCA-score 預投影**，不 route 過 live L1/L2 物件。

## 6. 小 n 可信度：CV+/jackknife+（✅ 已實作 TDD-0）
- `detectors/conformal_cv.py::CVPlusConformal`：K-fold leave-fold-out，每點 both fit both 校準；**自有門檻 `cv_plus_min_obs`（獨立於 `cp_min_calibration`=200）**；n_folds≥n → jackknife+。
- 覆蓋 worst-case **≥1−2α（0.80@α=0.1）**，實務常近 1−α；`coverage_floor` 誠實回報，**不**沿用 split-CP 的 ≥1−α（紅隊 A11/must-fix #2）。**非抗漂移**（re-entry 破 exchangeability 對兩者一視同仁；CV+ 只買小 n 可用性）。
- 確定性（折按 index 取模，無 RNG）；**不動** SoftSensor/PLSSoftSensor 的 split-CP 契約。

## 7. 隱性 Y 漂移監控（DQIy 網路深查裁決）
- **DQIy/ART2 不適用**：DQIy 是逐筆量測的**資料品質准入閘**（不是漂移偵測）；ART2 線上學習會**把慢漂移吸收進移動原型**、永不報警，且順序相依/噪聲敏感（違反 Rule 5）。→ **砍 ART2 DQIy**，只留 **DQIx 當 L1 資料品質閘**。
- **隱性 Y 漂移改用**（MECE，重用既有件）：
  - 緩慢 creep → **EWMA/CUSUM 監控殘差 e=y−ŷ**（漂移集中於殘差＝Rule 9 用於殘差）。⚠ G1 註記（2026-07-02 使用者裁決）：殘差經 ŷ 依賴 X，**不滿足 G1**「獨立於 X 與 Control-Limit 的純 Y-vs-歷史監控」；G1 另立獨立輕量模組（CUSUM/KS on raw Y），ground truth＝合成儀器漂移 adapter（TEP 的 Y=f(X) 結構上不可證）；G1×G3 同窗共發＝兩封信（優先規則）。
  - 離散 step（re-entry）→ change-point。
  - 分佈位移 → **L4 Wasserstein/KL（已有）**。
  - 有保證升級 → conformal martingale（接 split-CP）。
- 坑：化工殘差**高度自相關** → naive EWMA/CUSUM 過度報警 → 先 ARIMA 白化或自相關校正圖（Montgomery 查證）。**不要對監控殘差差分**（Kaneko&Funatsu Time-Difference 刻意抵消漂移，與暴露漂移相反）。

## 8. 池化 Golden 同質性護欄
- 多機台/時段 union 進單一 Golden 會**撐寬基準**→降隱性漂移靈敏度。
- 閘在 **build/acceptance 時**（比照 FPR/recall 治理，非 UI 浮動 banner）；**between-cell 置換檢定**（非 in-sample 自我參照 T²/SPE，後者必過）；**1-cell = 無操作 trivial pass**；**WARN 非硬擋** + 低檢定力註記（MMD 於 p≈80/少批 power 近零、bandwidth 固定 1.0）；提供分層模型替代。

## 9. DQIx 資料品質閘
- 保留 DQIx（PCA + Euclidean，Huang & Cheng 2011），建模前顯示；DQIy(ART2) 砍除（見 §7）。

## 10. TDD 順序與狀態
1. **[x] TDD-0 CP 小 n**：`conformal_cv.py` CV+/jackknife+（自有門檻、誠實 ≥1−2α）；6 測試綠、全套 445 passed。
1b. **[x] INC-1 批次疊圖 + [param×stat] 指標轉換**：`preprocess/batch_features.py`（batch_temporal_overlay／batch_indicator_matrix；resample 僅畫圖層、count 原生格餵 DQIx、cv |mean| floor）；6 WHY 測試綠、全套 451 passed（5052b8a，2026-07-03）。
2. **[x] TDD-3 結構隔離測試**：`tests/test_batch_avm_isolation.py`——主路徑（score_timeline/window_detail/health.py）原始碼＋子行程 import graph 雙重鎖 batch-AVM token；batch_features/conformal_cv 以 AST 驗 import 純度（不誤傷 docstring 散文）。
2b. **[x] INC-2 建模前資料品質視圖**：`batch_avm/quality.py::batch_quality_view`——X 側 fresh DQIxGate on X*（不碰 live L1）＋批長 n 一致性閘；Y 側**確定性准入閘**（存在性/robust 界限 median±k·MAD/卡值 run）取代已砍 ART2 DQIy；「Y 未量測」≠「Y 正常」明確分離；`y_enough_for_mapping` 綁 cv_plus_min_obs。12 測試綠、全套 463 passed。
3. [ ] TDD-4 n 一致性/長度測試 → min/max/range + n-guard + fixed-p fallback；極值→DQIx sensor-health。
4. [ ] TDD-殘差 Y 漂移監控（EWMA/CUSUM on e=y−ŷ，自相關感知、不差分）——偏 G2 支援線，非 G1。
4b. **[x] G1 純 Y-vs-歷史監控（獨立輕量模組）**：`y_history.py::YHistoryMonitor`——只吃 y（結構性 X-獨立，import 純度測試鎖）；CUSUM 層（robust median/MADσ 標準化＋**h 經驗校準於歷史 Y 自跑 CUSUM max(C±)×margin**，吸收 MADσ 抽樣誤差——RED 實測 σ 低估 11% 即讓平穩破固定 h）＋KS 滑窗層（3–5 筆、連續 g1_ks_persistence 窗顯著才報——滑動多重比較第一道治理）＋onset 估計（語意＝漂移超過 allowance k 的時點）。ground truth＝`adapters/instrument_drift.py` 合成儀器漂移（TEP 的 Y=f(X) 不可證 G1；刻意不走 ProcessDataset 契約）。6 WHY 測試綠、全套 501 passed。G1 為獨立告警通道（不融合主 HI；SMTP 串接暫緩）。
5. **[x] TDD-5/6（INC-3）X*→Ŷ + X* MSPC**：`batch_avm/mapping.py`——`fit_batch_model`（make_soft_sensor 路由 PLS 主力 + CVPlusConformal 可信帶）＋fresh `MSPCModel` on X*（highdim 預投影，reduced_/degraded_ 誠實 surface）；`score_batches`（yhat/CV+ 帶/T²/SPE/GSI/域旗標/RBC top——**僅未降維時歸因**，降維誠實 None）。8 WHY 測試綠、全套 471 passed。
6. **[x]（INC-4）skeleton + generate_fleet + 選取**：`interface.py` 加 `MACHINE_ID` 入 RESERVED（additive、選用、僅 provenance）；`tep.generate_fleet`（M-2 seed+每機台 σ 偏移=X 側儀器偏差、各自起始日期、registry 註冊 `tep_fleet`、fail-loud）；`batch_avm/selection.py`（machines_in_interval + cut_batches 固定時長 pseudo-batch、批內 Y 平均、尾批 min_frac 丟棄、frame_positions 溯源）。11 測試綠（含 e2e：fleet→選機台→切批→X*→品質→建模評分）、全套 482 passed。
6b. **[x] 池化同質性閘**：`batch_avm/homogeneity.py::golden_homogeneity_gate`——between-cell 置換檢定（MANOVA 型組間離差、labels 重排 B=perm_B、固定 seed；**非** in-sample 自我參照）；WARN-only + 指名差異最大特徵（σ 單位）；1-cell trivial pass；小 cell low_power 誠實標（非拒絕≠同質）。`fit_batch_model(cells=...)` 於 build 時跑、進 score summary 治理流。6 測試綠、全套 495 passed。
6c. [ ] TDD-7 殘餘：模型比較 CV harness（新模組，非 crossval.py）。
6d. **[x] G2/G3 X 歸因**：`batch_avm/attribution.py`——G2 `y_event_attribution`（敏感度×偏移 central-diff，PLS 精確 Σc=Δŷ、GPR 以 linearization_gap 誠實揭露；confidence gate：X* 離域→reliable=False）；G3 `domain_exit_attribution`（T² 完整分解 Σc=T² + SPE RBC、依超限來源取排名；降維誠實 available=False）；param 級聚合回答「哪個製程參數」。**precision@1 真值測試**（注入已知肇因、top-1 必中——只驗排序的測試會讓永遠指錯也綠燈）。7 測試綠、全套 508 passed。SPE-RBC（X-vs-X）與 G2（X→Y）明確分離（Rule 7）。
7. [ ] TDD-11 DQIy=DROP ART2、DQIx-only。
8. [ ] 非 code：Barber crossref VERIFY + DQIy DOI 衝突修正 + Gate2 紅線/step-9 改字 + dcc.Interval 進度基建。

## 11. NOT VERIFIED / crossref TODO（Rule 12）
- **Barber, Candès, Ramdas & Tibshirani 2021「Predictive inference with the jackknife+」**（Ann. Statist. 49(1):486–507）：CV+/jackknife+ 的 ≥1−2α 底線來源——**不在 crossref**，須 VERIFY 後方可作已驗證引用。
- **DQIy DOI（已解，前述衝突為 stale）**：crossref `:26/27` 已統一為 `10.1109/TSM.2011.2146006`、狀態 VERIFIED、附 IEEE 連結，為權威。網路調查曾出現 `10.1109/TSM.2011.2154910`——與 VERIFIED 條目衝突，值得再確認一次，但不推翻 crossref。
- EWMA/CUSUM ARL（~10 vs ~44 子組）來自 JMP portal，非原始文獻；ART2 正典（Carpenter & Grossberg 1987, Applied Optics 26:4919-4930）；Kadlec 2011/2009、Kaneko&Funatsu TD、conformal martingale（J. Process Control 2025 DOI 尾碼 placeholder）——全待 VERIFY。
- **TEP 資料實地校正（更正先前「無 .mat」誤述）**：`data/tep/` 有 12 個真實 MMFDD-TEP `.mat`，`tep.generate()` 本環境可跑（實測 300 列/22 感測器/稀疏 Y）。**既有五維鏈**對「注入型」隱性飄移（打亂高相關 XMEAS 時序、保邊際破相關）已**實測**：單變數 univ≈0.04（盲）、HI drift 0.55 vs 乾淨 0.95（見 `adapters/tep.py` docstring）。誠實限制：9 個**真實 IDV 故障無一**重現「單變數盲/多變量抓」（故 covert drift＝注入刺激、明確標記非真實物理失效）。**尚未實測**：**新** batch-AVM 路徑（X\*=[param×stat]、殘差 EWMA/CUSUM、多機台 fleet）在 TEP 上的表現——X*=[param×stat] 轉換核心已建（`preprocess/batch_features.py`，INC-1）；映射模型／X* MSPC／殘差監控／fleet 尚未建，端到端仍未在 TEP 實測（非資料限制；資料在，建好即可測）。

## 12. 待建基礎建設
- **[x]（INC-5）** Gate2「%進度轉換」已落地：`frontend/batch_wizard.py` thread + `dcc.Interval` 輪詢 + 模組級 job-state（token 入 dcc.Store）；9 步精靈掛入 demo_app `scr-batchwiz`（與 5 步精靈並存，驗證後汰換）。callback 皆薄殼包純函數（tests/test_batch_wizard.py）；UI 視覺未渲染驗證（NOT VERIFIED-visual，比照 demo_app 慣例）。
