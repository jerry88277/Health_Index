# 判斷鏈現代化升級地圖（5W1H × MECE）

> 日期 2026-06-01 · 合成自 `modernization_L2_multivariate.md`、`modernization_L3_softsensor.md`、`modernization_L4_drift.md`、`modernization_L1_diag_preproc.md`
> 目的：把「AVM(2008)/KS(1933)/KL(1951)/PSI/Wasserstein 等經典」逐模組對照近年(2017–2026)更新解法，定 **replace / augment / 不採用** 與導入時機。
> 紀律：偵測器 deterministic-at-inference、不呼叫 LLM（Rule 5）；不為求新而過度設計（Rule 2）；五維度骨架穩定，只升級領域層（Rule 3）。

> ⚠️ **v0.2 對帳註（必讀）**：本檔部分用語經三方紅隊判定**過度宣稱**，已被 `redteam_reconciliation.md` §4「淨設計」取代——**衝突一律以 reconciliation 為準**。具體：①「DPCA 零增量/零成本」→ 維度膨脹 p→p(l+1)，需 n≥10·p(l+1) gate；②「RBC 嚴格消 smearing」→ 僅消單故障，多方向殘留；③「MMD 取代 KS 主判據」→ KS 保留為廉價 1D first-pass，成本分層；④「Sinkhorn 1/√n 保幾何兼得」→ 率對固定 ε 成立但常數隨 ε→0 與維度爆炸，與保幾何 trade-off；⑤「EnbPI/ACI 覆蓋保證」→ 非穩態/無線上標籤下保證失效，不宣稱；⑥可信度：CP 已取代 RI 的可信度語意（有標籤區間，soft_sensor.py:3-6；live code 無 RI）；無標籤時刻由 GSI/ICAD 擔綱（CP 無輸出）——H1 原意「CP 不整碗涵蓋無標籤場景」保留。另：全鏈需 FWER 控制、power 下限用 TEP 模擬非均值公式（紅隊 N1/N2）。

---

## 1. 5W1H 框架
- **What**：哪個模組被升級。
- **Why**：解了哪個第一性原理痛點（經典方法的數學根因）。
- **What's new**：現代替代方案。
- **Who/Where**：哪個領域/文獻驗證過、成熟度。
- **When**：建議導入的階段（Phase 1 MVP / 2 / 3）。
- **How**：取代(replace)／補強(augment)，以及對骨架的改動幅度。

## 2. MECE 升級總表

| 模組 | 經典（被升級對象）| 現代升級 | Why（痛點）| How | 成熟度 | 確定性 | 階段 |
|---|---|---|---|---|---|---|---|
| **L1 資料品質** | sample covariance | **FastMCD**（抗污染協方差）| 少數離群毒化 Σ | replace 估計器（介面不變）| 統計成熟 | ✅ | **P1** |
| L1 | DQI_x 線性閘 | **Isolation Forest** | 線性閘漏非線性異常 | augment（並聯）| 成熟 | ✅ | P2 |
| **診斷** | MSPC contribution plot | **RBC**（Reconstruction-Based Contribution）| smearing 抹糊、最大貢獻者未必真兇 | **replace**（封閉解、共用 PCA）| 成熟(Alcala&Qin 2009)| ✅ | **P1** |
| 診斷 | — | ISI 當「關係型飄移分類器」| ISI 對隱性飄移單看是盲的 | augment（與 RBC 併判）| — | ✅ | P1 |
| **L2 多變量** | 靜態 PCA | **DPCA**（時間落後）| 連續製程自相關/動態(③)| augment 基線（零增量）| 廣用 | ✅ | **P1** |
| L2 | PCA | **SFA**（Slow Feature）| 無法分「正常變動 vs 動態異常」| augment（最契合判準3）| 產業案例 | ✅ | **P2** |
| L2 | PCA/DPCA | **CVA**（Canonical Variate）| incipient 隱性飄移早偵測(③④)| augment（A/B 比較）| 產業案例 | ✅ | P2 |
| L2 | — | KPCA/ICA/PPCA | 非線性①/非高斯②/缺值多模態 | 條件性 augment | 成熟 | ✅ | P3（按需）|
| **L3 軟測量** | PLS/GPR | 維持 PLS/GPR（base）| 地端標註稀少，深度模型過重 | 不動 base | — | ✅ | P1 |
| L3 | GPR O(n³) | **DKL/SVGP** | GPR 擴展性/穩態核 | replace（資料變大時）| 中高 | ✅ | P3 |
| **可信度** | **AVM RI** | **Conformal Prediction**（split-CP→EnbPI/ACI）| RI ad-hoc、無覆蓋保證、雙模型可同錯(②)| replace：CP 已刻意取代 RI（soft_sensor.py:3-6），live code 無 RI，RI 僅存 literature_crossref.md 作文獻對照；UI/新精靈 step-9 不得稱 RI（改 GSI / CP-band(可信度)）| 理論成熟 | ✅ | P1(split，已建 M4)→小 n 已建 CV+/jackknife+（detectors/conformal_cv.py，2026-07-02，誠實覆蓋 ≥1−2α=0.80@α0.1、自有門檻 cv_plus_min_obs）→P2(EnbPI/ACI，不宣稱保證，soft_sensor.py:13)。另註 P1 整體落地：FastMCD/RBC/ruptures/split-CP/MMD 已建（M0–M10）；DPCA 僅預留 config.x_lag_order 未接線；L5 band-DTW 已建（batch_dtw.py）|
| 可信度 | RI 雙模型 | Deep Ensembles | 兩模型同錯 | 過渡 augment | 成熟 | ✅ | P2（按需）|
| **L4 漂移** | KS（單 max-gap, 1D）| **MMD / MMDAgg**（kernel two-sample）| 多維、捕捉關係型漂移、不發散(①②⑤)| **replace 主判據**（出 p-value）| 成熟(Gretton)| ✅ | **P1** |
| L4 | 精確多維 Wasserstein O(N³logN)| **Sinkhorn divergence**（熵正則 OT）| 降到 O(N²/ε)、保 OT 幾何、少量點友善(①③)| replace 量級指標（未實作；as-built 以解析 1D-Wasserstein 出量級，drift.py）| 成熟(Genevay)| ✅ | 未實作（留待真需多維 OT 幾何）|
| L4 | KL | Energy Distance | KL 發散/非對稱 | 免 kernel 替身 | 成熟 | ✅ | P2 |
| L4 | 離線批量比較 | **ADWIN + BOCPD + ruptures** | 缺線上序列偵測(④)| augment（接 score 流）| 成熟 | ✅ | P2 |
| **分段** | 手刻 SSD + transition 規則 | **ruptures(PELT)** + rbf-kernel CPD + BOCPD | window 無通解、規則啟發 | **replace**（門檻塌縮為單一 penalty）| 成熟 | ✅ | **P1** |
| **對齊(L5,批次)** | 裸 DTW O(n²) | **Sakoe-Chiba band / FastDTW**；soft-DTW(離線模板)| O(n²)、病態映射 | augment | 成熟 | ✅ | P3（批次才需）|

## 3. 5W1H 重點詳述（四個最關鍵升級）

### ① 可信度：RI → Conformal Prediction
- **Why**：RI 是兩模型輸出分佈重疊面積，**無有限樣本覆蓋保證、門檻經驗、兩模型可一致地錯**。
- **What's new**：CP 用 calibration set 的 nonconformity 分位給出**有保證**的預測區間 $P(y\in\hat C)\ge 1-\alpha$；時序/漂移用 EnbPI、ACI。
- **Who/Where**：Angelopoulos&Bates 2021 教程；工業時序+distribution shift 已有 2025 IEEE 應用（DOI 待補）。
- **How**：base estimator 仍 PLS/GPR，CP 只是**外掛校準層**——對骨架 surgical（加 calibration set + wrapper）。RI 已被 CP 刻意取代（soft_sensor.py:3-6，live code 無 RI），僅存 literature_crossref.md 作文獻對照。
- **When**：P1 上 split-CP；P2 升 EnbPI/ACI 對應 re-entry 漂移。

### ② L4：KS → MMD，精確 Wasserstein → Sinkhorn
- **Why**：KS 只用單一 max-gap、1D、弱尾部；精確多維 Wasserstein O(N³logN)。
- **What's new**：MMD 在 RKHS 比全分佈、**多維原生、捕捉關係型隱性飄移、不發散**，permutation 校準可沿用；Sinkhorn 把 OT 降到 O(N²/ε) 且保幾何、對少量點 sample complexity 1/√n。
- **分工（Rule 7，不混成單一公式）**：**MMD 出 p-value（是否相異）、解析 1D-Wasserstein 出可解釋距離（漂移多大，as-built drift.py；Sinkhorn 未實作）、PSI 供人看嚴重度帶**。
- **When**：P1 即可換主判據與量級指標。

### ③ 診斷：contribution → RBC（＋ISI 當關係型分類器）
- **Why**：原始 contribution 有 smearing，最大貢獻者未必真兇。
- **What's new**：RBC 封閉解、理論保證單變數故障必正確定位、嚴格消 smearing；共用現有 PCA 模型、O(m) 零額外依賴。
- **How**：直接 replace；ISI 不丟，用其「低」確認飄移屬**關係型隱性**（RBC 高 + ISI 低 = 純多變量飄移）。
- **When**：P1（零成本高回報）。

### ④ L2：PCA → DPCA(P1) → SFA/CVA(P2)
- **Why**：靜態 PCA 不含動態(③)，且分不出「正常操作點變動 vs 殘留動態飄移」。
- **What's new**：DPCA 零增量補動態；**SFA 原生分『正常變動 vs 動態異常』正中成功判準3**；CVA 對 incipient 飄移早於 PCA/DPCA。
- **How**：皆 augment、仍導 T²/SPE 類統計量與控制限、確定性、不需深度資料量。
- **When**：P1 先 DPCA 當 baseline；P2 用 SFA/CVA A/B 比較增益。

## 4. 分階段採用 roadmap（Rule 2：先低成本高回報）

| 階段 | 納入項 | 性質 |
|---|---|---|
| **Phase 1（MVP，即插/低成本、全確定性）** | DPCA、RBC、FastMCD、ruptures(PELT)、**Conformal split-CP**、MMD（主判據，KS 為廉價 1D first-pass）＋解析 1D-Wasserstein（量級，as-built drift.py；無 ε 超參）；Sinkhorn 未實作、留待真需多維 OT 幾何（reconciliation §4、D4 降級階梯）| 介面相容、無需深度資料、立即提升 |
| **Phase 2（MVP 綠燈後）** | SFA、CVA（vs DPCA A/B）、EnbPI/ACI（CP 時序版）、ADWIN+BOCPD（線上）、Isolation Forest、Energy Distance | 增益驗證、線上化 |
| **Phase 3（資料規模成熟 / v2）** | DKL·SVGP、VAE 半監督、KPCA/ICA/PPCA（按需）、GNN（遠期觀察）、soft-DTW（批次）| 資料變大才划算 |

> 深度法（VAE/GAN/Deep SVDD/GNN/Transformer/NF）一致判 **MVP 不採用**：需大量資料、無解析控制限、可解釋性弱、化工連續製程產業證據薄，踩 Rule 2。

## 5. 對現有文件/判斷鏈的影響（已於 2026-06-02 v0.2 回填，commit 72a4173；本節保留為當時清單）
- `functional_design.md`：L2 加 DPCA 基線、診斷改 RBC、L4 改 MMD+Sinkhorn panel、L3 可信度改 CP wrapper、前處理改 ruptures。
- `requirements_spec.md`：FR-5（contribution→RBC）、FR-6（RI→CP）、FR-7（drift→MMD/Sinkhorn）、FR-2（SSD→ruptures）更新。
- `development_plan.md`：里程碑 M2–M6 的方法選型更新；新增「Phase 標記」。
- **骨架不動**：五維度判斷鏈與 `interface.py` 契約維持（Rule 3）；以上皆領域層替換。

## 6. 風險與待補（Rule 12）
- **DOI 衝突**：L3 檔 Cheng 2008 RI 標 `10.1109/TSM.2007.914388`，與已查證 `literature_crossref.md` 的 `10.1109/TSM.2007.914373` 衝突 → 以 .914373 為準——已修（2026-06-02）：modernization_L3_softsensor.md:14 現標 .914373；.914388 經 redteam_citations.md 證實為 Yoon & Shen 他人論文（危險錯引），頁碼定讞 92–103。
- **NOT VERIFIED 待補正式 DOI**：工業時序 CP 2025(IEEE 10870871)、Unified JITL 2022、Spatio-temporal LSTM 2023、CVA incipient 2024、NF 時序 2023、TEP-GNN/Anomaly Transformer/Real NVP（會議無 DOI）。落地引用前須補查（嚴禁當已驗證引用）。5 筆正式 DOI 已由 redteam_citations.md 查得（含 Spatio-temporal LSTM 期刊更正為 Eng. Appl. Artif. Intell. 126:106847）；惟 literature_crossref.md（唯一引用真相）尚未補登（grep 驗證無此 5 筆）→ 引用前仍須先入 crossref。
- **CP 的 marginal vs conditional**：split-CP 是平均覆蓋，單點可能不準 → 需要時用 Mondrian/group-conditional CP。
- **超參數**：DPCA lag、ruptures penalty、MMD bandwidth、CP α、SSD/Sinkhorn ε 皆需在 TEP 上以 ground-truth 掃描定值，版本化、不硬編。
