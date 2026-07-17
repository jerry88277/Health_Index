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
4. **[x] 殘差 Y 漂移監控（G2 偵測線）**：`batch_avm/residual.py`——監控 e=y−ŷ vs 歷史殘差（DRY 復用 `YHistoryMonitor`）；分離「製程移動、映射完好→殘差安靜」vs「X→Y 斷裂→殘差漂移」；null 分級（優先 CV+ **out-of-fold 有號殘差** `cv_resid_signed_`，in-sample 偏窄則降級揭露 null_kind）；**域閘先行**（X* 離域批的殘差=外推誤差非漂移→不納入，A13 教訓，計數 n_off_domain）；**不差分**（Kaneko&Funatsu TD 抵消漂移）；未量測≠正常。6 WHY 測試綠。
4b. **[x] G1 純 Y-vs-歷史監控（獨立輕量模組）**：`y_history.py::YHistoryMonitor`——只吃 y（結構性 X-獨立，import 純度測試鎖）；CUSUM 層（robust median/MADσ 標準化＋**h 經驗校準於歷史 Y 自跑 CUSUM max(C±)×margin**，吸收 MADσ 抽樣誤差——RED 實測 σ 低估 11% 即讓平穩破固定 h）＋KS 滑窗層（3–5 筆、連續 g1_ks_persistence 窗顯著才報——滑動多重比較第一道治理）＋onset 估計（語意＝漂移超過 allowance k 的時點）。ground truth＝`adapters/instrument_drift.py` 合成儀器漂移（TEP 的 Y=f(X) 不可證 G1；刻意不走 ProcessDataset 契約）。6 WHY 測試綠、全套 501 passed。G1 為獨立告警通道（不融合主 HI；SMTP 串接暫緩）。
5. **[x] TDD-5/6（INC-3）X*→Ŷ + X* MSPC**：`batch_avm/mapping.py`——`fit_batch_model`（make_soft_sensor 路由 PLS 主力 + CVPlusConformal 可信帶）＋fresh `MSPCModel` on X*（highdim 預投影，reduced_/degraded_ 誠實 surface）；`score_batches`（yhat/CV+ 帶/T²/SPE/GSI/域旗標/RBC top——**僅未降維時歸因**，降維誠實 None）。8 WHY 測試綠、全套 471 passed。
6. **[x]（INC-4）skeleton + generate_fleet + 選取**：`interface.py` 加 `MACHINE_ID` 入 RESERVED（additive、選用、僅 provenance）；`tep.generate_fleet`（M-2 seed+每機台 σ 偏移=X 側儀器偏差、各自起始日期、registry 註冊 `tep_fleet`、fail-loud）；`batch_avm/selection.py`（machines_in_interval + cut_batches 固定時長 pseudo-batch、批內 Y 平均、尾批 min_frac 丟棄、frame_positions 溯源）。11 測試綠（含 e2e：fleet→選機台→切批→X*→品質→建模評分）、全套 482 passed。
6b. **[x] 池化同質性閘**：`batch_avm/homogeneity.py::golden_homogeneity_gate`——between-cell 置換檢定（MANOVA 型組間離差、labels 重排 B=perm_B、固定 seed；**非** in-sample 自我參照）；WARN-only + 指名差異最大特徵（σ 單位）；1-cell trivial pass；小 cell low_power 誠實標（非拒絕≠同質）。`fit_batch_model(cells=...)` 於 build 時跑、進 score summary 治理流。6 測試綠、全套 495 passed。
6c. [ ] TDD-7 殘餘：模型比較 CV harness（新模組，非 crossval.py）。
6d. **[x] G2/G3 X 歸因**：`batch_avm/attribution.py`——G2 `y_event_attribution`（敏感度×偏移 central-diff，PLS 精確 Σc=Δŷ、GPR 以 linearization_gap 誠實揭露；confidence gate：X* 離域→reliable=False）；G3 `domain_exit_attribution`（T² 完整分解 Σc=T² + SPE RBC、依超限來源取排名；降維誠實 available=False）；param 級聚合回答「哪個製程參數」。**precision@1 真值測試**（注入已知肇因、top-1 必中——只驗排序的測試會讓永遠指錯也綠燈）。7 測試綠、全套 508 passed。SPE-RBC（X-vs-X）與 G2（X→Y）明確分離（Rule 7）。
7. [ ] TDD-11 DQIy=DROP ART2、DQIx-only。
8. [ ] 非 code：Barber crossref VERIFY + DQIy DOI 衝突修正 + Gate2 紅線/step-9 改字 + dcc.Interval 進度基建。

## 11. NOT VERIFIED / crossref TODO（Rule 12）
- **[x] Barber, Candès, Ramdas & Tibshirani 2021「Predictive inference with the jackknife+」**（Ann. Statist. 49(1):486–507）：CV+/jackknife+ 的 ≥1−2α 底線來源——**已 VERIFY**（2026-07-17，CrossRef DOI 10.1214/20-AOS1965；頁碼經 Project Euclid 出版商頁確認），已轉錄 `literature_crossref.md` §1「Conformal 補登」，`conformal_cv.py` docstring 標記已改 VERIFIED。
- **DQIy DOI（已解，前述衝突為 stale）**：crossref `:26/27` 已統一為 `10.1109/TSM.2011.2146006`、狀態 VERIFIED、附 IEEE 連結，為權威。網路調查曾出現 `10.1109/TSM.2011.2154910`——與 VERIFIED 條目衝突，值得再確認一次，但不推翻 crossref。
- EWMA/CUSUM ARL（~10 vs ~44 子組）來自 JMP portal，非原始文獻；ART2 正典（Carpenter & Grossberg 1987, Applied Optics 26:4919-4930）；Kadlec 2011/2009、Kaneko&Funatsu TD、conformal martingale（J. Process Control 2025 DOI 尾碼 placeholder）——全待 VERIFY。
- **TEP 資料實地校正（更正先前「無 .mat」誤述）**：`data/tep/` 有 12 個真實 MMFDD-TEP `.mat`，`tep.generate()` 本環境可跑（實測 300 列/22 感測器/稀疏 Y）。**既有五維鏈**對「注入型」隱性飄移（打亂高相關 XMEAS 時序、保邊際破相關）已**實測**：單變數 univ≈0.04（盲）、HI drift 0.55 vs 乾淨 0.95（見 `adapters/tep.py` docstring）。誠實限制：9 個**真實 IDV 故障無一**重現「單變數盲/多變量抓」（故 covert drift＝注入刺激、明確標記非真實物理失效）。**尚未實測**：**新** batch-AVM 路徑（X\*=[param×stat]、殘差 EWMA/CUSUM、多機台 fleet）在 TEP 上的表現——X*=[param×stat] 轉換核心已建（`preprocess/batch_features.py`，INC-1）；映射模型／X* MSPC／殘差監控／fleet 尚未建，端到端仍未在 TEP 實測（非資料限制；資料在，建好即可測）。

## 12. 待建基礎建設
- **[x]（INC-5）** Gate2「%進度轉換」已落地：`frontend/batch_wizard.py` thread + `dcc.Interval` 輪詢 + 模組級 job-state（token 入 dcc.Store）；9 步精靈掛入 demo_app `scr-batchwiz`（與 5 步精靈並存，驗證後汰換）。callback 皆薄殼包純函數（tests/test_batch_wizard.py）；UI 視覺未渲染驗證（NOT VERIFIED-visual，比照 demo_app 慣例）。

## 13. 開發 backlog（loop 追蹤，狀態驅動）
每次迭代：讀本清單 → 挑最上面的 `[ ]` → TDD 完成 → 標 `[x]` → 綠燈 commit。
1. [x] 數值護欄：mspc L2 fail-loud（非有限→raise）+ 條件數 surface + RBC 退化自消證明鎖（風險稽核 rank-9）——`detectors/mspc.py`：非有限輸入 raise、fit 條件數>1e10 警告、RBC 退化欄（Ctilde_jj<1e-8）顯式歸零+errstate。深究：rank-9 的「除≈0→garbage-first」對正確投影**數學自消**（Ctilde_jj→0⟺整列→0⟺resid→0），仍加 fail-loud 防數值雜訊。4 測試綠、全套 518 passed（cabcb57 後）。
2. [x] UI 整合：把 G1/殘差/新歸因（attribution）接進 9 步精靈第 9 關——`frontend/batch_wizard.py`：下鑽細節舊 rbc_top→新 G2（哪個參數推動 Ŷ，離域 gate）+G3（哪個參數推出域）；第 9 關摘要卡加殘差漂移(G2)+Y-vs-歷史(G1)；`_MODELS` 存 golden(X*,y)、新增 attribute_batch/monitor_y_channel 純函數。8 精靈測試綠、app 200、全套 519 passed。
3. [x] 正式 G3 AD：leverage/hat-matrix + 宣告 Ŷ 有效範圍（取代 T²/SPE 代理）——`batch_avm/applicability.py`：`ApplicabilityDomain`（標準化特徵空間 pinv Gram、QSAR 限 3(rank+1)/n）+ 宣告 Ŷ 範圍 [y_min,y_max]（golden y±5%）；兩**正交**訊號 G3=leverage 超限 OR Ŷ 出範圍，歸因走 leverage 逐特徵貢獻→param。關鍵：Ŷ-範圍是 **T²/SPE 完全偵測不到的響應空間外推**（X 在合理域內卻預測到訓練 Y 範圍外）；p≥n 時 lev_limit>1 誠實標 `leverage_informative=False`（此時 Ŷ-範圍 carry）。fit 時 golden y 範圍退化→raise（不假評），mapping 包 try/except→ad_=None。wire：`fit_batch_model` 建 `model.ad_`、`score_batches` 每批帶 g3_ad_alarm/leverage/yhat_in_range/g3_ad_top/g3_ad_reason + summary["applicability"]；精靈第 9 關下鑽 G3 改用正式 AD。7 AD 測試 + 8 精靈綠、全套綠。
4. [x] 多產線總覽畫面（北極星）＋點線進即時記錄/告警史/模型資訊——`frontend/fleet.py`（新呈現殼）+ demo_app 掛載 6 處（import/scr-fleet 佔位/nav-fleet 鈕/`_route`/`_show_screen`/register）。**方案 B**（使用者拍板）：一線＝一既有監控點(process/dataset)，per-line 健康沿用 `demo.assets_overview` 三態燈（零資料層改動、不碰被隔離的 batch_avm）；點線就地展開三部分——①線上即時記錄（`score_timeline` 離線逐窗健康折線，marker 依 persisted_alarm 上色）②告警歷史（`IncidentStore.list(product)`，每筆下鑽 top_cause＝偏移的 X 參數/Y 量測）③模型建立資訊（`model_history` 版本/驗收/稽核）。純資料函數 `fleet_overview`/`line_detail_data`/`realtime_figure` 可測（line-scoped、不串線）。真逐 machine_id rollup 留作後續 backlog（語意待拍板）。8 fleet WHY 測試綠、server 開機 GET/ 200 且 _dash-layout 含 scr-fleet/nav-fleet、註冊無衝突；互動點擊渲染 NOT VERIFIED-visual（此環境瀏覽器無法驅動 Dash clientside，與既有 nav 一致）。
5. [x] CV harness：nested/repeated CV 模型比較 + conformal coverage（新模組，非 crossval.py）——`validation/cv_harness.py`：`repeated_kfold_score`（out-of-fold，無洩漏）／`compare_models`（GPR vs PLS 擇優）／`conformal_coverage`（外層 K-fold held-out 稽核 CV+ 帶，底線誠實 1−2α 非 1−α）／`nested_cv_selection`（無偏估選擇程序，不被 in-sample 完美的過擬合模型騙）。與 crossval.py 分工（後者＝主 HealthIndex AC-1/2/3 驗收）。**獨立紅隊（3 視角）抓到並修**：舊版 `repeats` 用 offset 旋轉只重命名 fold 標籤、分割不變＝no-op（rmse_std 恆 0、n_eval 虛增 ×repeats）；改為確定性乘法雜湊排列產生**真不同折分割**（無 RNG，Rule 5），rmse_std 變真實「對折分配敏感度」、n_eval 回歸 distinct 點數 n。裁決建議「刪 repeats」，改採「讓 repeats 真的有效」以忠實交付 backlog 的 repeated CV。7 WHY 測試綠（含 no-op 回歸鎖）、全套綠。
6. [x] Barber 2021 + redteam_citations §4b 5 筆 DOI 入 literature_crossref.md——6 筆逐筆**重查 CrossRef primary source**（非憑既有 ledger）：Barber 2021（10.1214/20-AOS1965，頁碼 486–507 經 Project Euclid 確認）+ Zhang&Zhou 2025（10.1109/TII.2025.3529920，補全卷期 21(5):3676–3685）+ Wang 2022（10.1016/j.ces.2022.117753）+ Zhou 2023（10.1016/j.engappai.2023.106847，期刊 EAAI 非 audit 誤植 CEP）+ Ji 2024（10.1016/j.chemolab.2024.105189）+ Guan 2023（10.1016/j.isatra.2023.09.002，通用 MTS→標類比）。轉錄至 `literature_crossref.md` §1「Conformal 補登」；`conformal_cv.py`/`redteam_citations.md` §11 標記同步更新。零捏造、零 NOT FOUND。
7. [x] 即時 headless runner（batch-AVM 排程跑、save/load state）——`batch_avm/runner.py`：`poll_batches` 純函式 + `BatchRunnerState`（cursor + n_alarms）+ save/load_state，**比照 `deploy/runner.py` 的 D2 決策**（純函式 + 外部排程器驅動、非 daemon，Windows 排程/cron 皆可）。冪等於 cursor（重入只處理新到齊批，不重複告警／未來不重複觸發 SMTP）、resume-safe（存/載後從斷點續跑，與一次跑完 allclose 等價）。範圍到 X*→Ŷ + 正式 G3 AD（每批帶 yhat/band/anomaly/g3_ad_alarm/g3_ad_top/rbc_top）；Y 側 G1/G2 與批內 4h 生命週期屬 #9。隔離：只依 batch_avm.mapping，不 import 主 HealthIndex/deploy（isolation test 綠）。6 WHY 測試綠（冪等/訊號/resume/首啟/便利/確定性）、全套綠。
8. [x] G1×G3 同窗共發：兩封信 + 優先規則——`src/health_index/notify.py`：`compose_notifications`（純 payload 組裝，SMTP 傳輸 deferred）。鎖定決策落地：G1（實際 Y 偏離歷史，獨立於 X/Ŷ）與 G3（Ŷ 越適用域，可信度警訊）**同窗共發→兩封獨立信、不合併**（Rule 7 正交不平均）；優先 `PRECEDENCE` G1(1)>G2(2)>G3(3)——G1 已確認真實偏離 actionable、G3 為 Ŷ 預測不可信警訊；G2 併入 G1 那封的 X 歸因 cause。兩封 `co_fired` 交叉引用見全貌。不 import 偵測器（純組裝、不破隔離）。7 WHY 測試綠（兩封不合併/優先/交叉引用/G1帶G2歸因/G3指名越域參數/只一觸發不生幻影/確定性）、全套綠。
9. [ ] 批次生命週期 runtime（10min 起監 X→2h Ŷ_middle→4h Ŷ_final→出 Y 查 G1）
10. [ ] 殘差自相關 ARIMA 白化
11. [ ] mindmap v3（架構圖更新至 batch-AVM）
（**暫緩，不在 loop**：SMTP 串接、每目標驗收指標、跨線多重比較/FPR——使用者定調；UI 視覺實跑——環境無法渲染。）
