# Red-Team 文獻引用查證報告（獨立對抗審查）

> 審查日期：2026-06-02 · 角色：學術文獻誠信獨立 red team（懷疑、不信任既有結論、逐筆親查）
> 狀態註記（2026-07）：本檔為 modernization 階段查證 ledger（歷史紀錄，勿改裁決本文）。§4a 必改已落地；§4b 五筆補登書目**尚未轉錄至 literature_crossref.md**（唯一引用真相）；後續文獻待辦（Barber 2021 VERIFY、DQIy DOI 已統一 2146006）改由 batch_avm_design.md §11 追蹤。
> 方法：以 **CrossRef API**（DOI 註冊權威）為第一優先，輔以 PMLR / JMLR / 出版商頁面 / arXiv 交叉比對。會議論文（PMLR/NeurIPS/JMLR）多無傳統 DOI，標明其權威識別碼（PMLR vol、JMLR vol、ACM 代理 DOI）。
> 紀律：嚴禁捏造。每筆給 VERIFIED / CORRECTED / NOT FOUND + 正確 DOI/URL。
> 對象：`modernization_map.md`、四份 `modernization_L*.md`、`literature_crossref.md`，並 audit-the-audit 審 `modernization_audit.md` 自身 F1–F3 事實主張。

---

## 1. 逐筆核對表

| 文獻 | 文件中宣稱 | 狀態 | 正確值 | DOI / URL |
|---|---|---|---|---|
| **RI / GSI（Cheng 2008）** | T-SM 21(1):92–103（crossref 檔）／L3 檔標 DOI `.914388` | **CORRECTED** | Cheng, Chen, Su, Zeng, *Evaluating Reliance Level of a Virtual Metrology System*, IEEE T-SM **21(1):92–103**, 2008。CrossRef 權威頁碼為 **92–103**（非 92–102） | **10.1109/TSM.2007.914373** · doc 4447298 |
| **DPCA（Ku 1995）** | Ku/Storer/Georgakis, Chemom. Intell. Lab. Syst. | **VERIFIED** | Ku, Storer, Georgakis, *Disturbance Detection and Isolation by Dynamic Principal Component Analysis*, CILS **30(1):179–196**, 1995 | **10.1016/0169-7439(95)00076-3** |
| **RBC（Alcala & Qin 2009）** | 宣稱 `10.1016/j.automatica.2009.02.027` | **VERIFIED** | Alcala & Qin, *Reconstruction-based contribution for process monitoring*, *Automatica* **45(7):1593–1600**, 2009 | **10.1016/j.automatica.2009.02.027** ✅ 宣稱正確 |
| **FastMCD（Rousseeuw & Van Driessen 1999）** | FastMCD 抗污染協方差 | **VERIFIED** | Rousseeuw & Van Driessen, *A Fast Algorithm for the Minimum Covariance Determinant Estimator*, *Technometrics* **41(3):212–223**, 1999 | **10.1080/00401706.1999.10485670** |
| **PELT（Killick 2012）** | ruptures/PELT | **VERIFIED** | Killick, Fearnhead, Eckley, *Optimal Detection of Changepoints with a Linear Computational Cost*, *JASA* **107(500):1590–1598**, 2012 | **10.1080/01621459.2012.737745** |
| **ruptures（Truong 2020）** | ruptures 套件論文 | **VERIFIED** | Truong, Oudre, Vayatis, *Selective review of offline change point detection methods*, *Signal Processing* **167:107299**, 2020 | **10.1016/j.sigpro.2019.107299** |
| **MMD（Gretton 2012）** | JMLR kernel two-sample | **VERIFIED** | Gretton, Borgwardt, Rasch, Schölkopf, Smola, *A Kernel Two-Sample Test*, **JMLR 13:723–773**, 2012 | 無傳統 DOI（JMLR open）；ACM 代理 **10.5555/2188385.2188410** · jmlr.org/papers/v13/gretton12a.html |
| **MMDAgg（Schrab 2023）** | MMDAgg 免調 bandwidth | **VERIFIED** | Schrab, Kim, Albert, Laurent, Guedj, Gretton, *MMD Aggregated Two-Sample Test*, **JMLR 24(194):1–81**, 2023 | 無傳統 DOI；ACM **10.5555/3648699.3648893** · jmlr.org/papers/v24/21-1289.html · arXiv 2110.15073 |
| **Sinkhorn（Genevay 2019）** | sample complexity / OT↔MMD 插值 | **VERIFIED** | Genevay, Chizat, Bach, Cuturi, Peyré, *Sample Complexity of Sinkhorn Divergences*, **PMLR 89:1574–1583**（AISTATS 2019） | 無傳統 DOI（PMLR）· proceedings.mlr.press/v89/genevay19a.html · arXiv 1810.02733 |
| **Conformal 專書（Vovk 2005）** | Vovk/Gammerman/Shafer 教科書 | **VERIFIED** | Vovk, Gammerman, Shafer, *Algorithmic Learning in a Random World*, Springer, 2005（1st ed.；ISBN-13 978-0-387-00152-4，eBook 978-0-387-25061-8） | **10.1007/b106715** |
| **Conformal 入門（Angelopoulos & Bates 2021）** | gentle intro tutorial | **VERIFIED** | Angelopoulos & Bates, *A Gentle Introduction to Conformal Prediction and Distribution-Free Uncertainty Quantification*, 2021 | arXiv **2107.07511**（後正式出版於 *Found. Trends ML*；引用 arXiv 即可） |
| **EnbPI（Xu & Xie 2021）** | 時序 CP / bootstrap ensemble | **VERIFIED** | Xu & Xie, *Conformal prediction interval for dynamic time-series*, **PMLR 139:11559–11569**（ICML 2021） | 無傳統 DOI（PMLR）· proceedings.mlr.press/v139/xu21h.html |
| **ACI（Zaffran 2022）** | 自適應時序 CP | **VERIFIED** | Zaffran, Féron, Goude, Josse, Dieuleveut, *Adaptive Conformal Predictions for Time Series*, **PMLR 162:25834–25866**（ICML 2022） | 無傳統 DOI（PMLR）· proceedings.mlr.press/v162/zaffran22a.html |
| **SFA（Shang 2015）** | 「分正常操作點變動 vs 動態異常」正中判準3 | **CORRECTED**（補全卷期/作者/DOI；docs 僅標「Shang 2015」） | Shang, Yang, Gao, Huang, Suykens, Huang, *Concurrent Monitoring of Operating Condition Deviations and Process Dynamics Anomalies with Slow Feature Analysis*, *AIChE J.* **61(11):3666–3682**, 2015 | **10.1002/aic.14888** |
| **CVA（Russell 2000）** | incipient 早偵測 | **VERIFIED** | Russell, Chiang, Braatz, *Fault detection in industrial processes using canonical variate analysis and dynamic principal component analysis*, CILS **51(1):81–93**, 2000 | **10.1016/S0169-7439(00)00058-7** |
| **Deep Ensembles（Lakshminarayanan 2017）** | 兩模型同錯的過渡 augment | **VERIFIED** | Lakshminarayanan, Pritzel, Blundell, *Simple and Scalable Predictive Uncertainty Estimation using Deep Ensembles*, **NeurIPS 30**, 2017 | 無傳統 DOI；ACM **10.5555/3295222.3295387** · arXiv 1612.01474 |

---

## 2. Audit-the-Audit：F1–F3 裁決

### F1 — RI 正確 DOI ✅（audit 結論正確，但需釘死一個殘留點）
- **裁決**：✅ audit F1 結論「以 `10.1109/TSM.2007.914373` 為準、L3 的 `.914388` 錯誤」**完全正確**。
- **親查 CrossRef 鐵證**：
  - `10.1109/TSM.2007.914373` → **正是** "Evaluating Reliance Level of a Virtual Metrology System"，Cheng/Chen/Su/Zeng，T-SM 21(1):92–103, 2008。
  - `10.1109/TSM.2007.914388` → **是完全不同的論文**：Yoon & Shen, *A Multiagent-Based Decision-Making System for Semiconductor Wafer Fabrication With Hard Temporal Constraints*, T-SM **21(1):83–91**。故 L3 檔的 `.914388` 不只是「打錯一碼」，它指向真實但無關的他人論文 → **必改**。
- **頁碼定讞**：audit 把「92-102 vs 92-103」列為待核。**CrossRef 權威值＝92–103**（`literature_crossref.md` 已採此值，正確）。部分二手檢索顯示 92–102，**不可採**——以 CrossRef 註冊 metadata 為準，**最終答案 92–103**。

### F2 — Genevay 2019 Sinkhorn sample complexity ✅
- **裁決**：✅ 出處與年份正確。論文確為 Genevay/Chizat/Bach/Cuturi/Peyré, *Sample Complexity of Sinkhorn Divergences*, AISTATS 2019 = **PMLR 89:1574–1583**，arXiv 1810.02733。
- **補強（audit 未寫全的書目細節）**：PMLR 無傳統 DOI；正式引用用 PMLR vol/page 或 arXiv id。audit 對「1/√n 僅大 ε 成立、與保幾何為 trade-off」的技術修正與原論文「SD 在 OT(n^−1/d)↔MMD(n^−1/2) 間插值」一致，**技術論述無誤**。

### F3 — Sejdinovic 2013 Energy = MMD ✅
- **裁決**：✅ 全部正確。Sejdinovic, Sriperumbudur, Gretton, Fukumizu, *Equivalence of distance-based and RKHS-based statistics in hypothesis testing*, *Ann. Statist.* **41(5):2263–2291**, 2013，DOI **10.1214/13-AOS1140**。卷期、頁碼、DOI 與 audit 宣稱**逐項吻合**。「energy distance 是 distance-kernel 的 MMD 特例」之論斷有原論文支撐 → audit 把 Energy Distance 併入/移出 L4 的決策**事實基礎成立**。

> **三項裁決小結**：audit 的 F1–F3 事實主張**全部站得住**（F1 ✅ F2 ✅ F3 ✅）。F1 額外確認了 `.914388` 是「指向他人真實論文」的危險錯引，且頁碼定讞 92–103。

---

## 3. 仍 NOT FOUND 清單

**無。** audit 殘留 NOT VERIFIED 五筆**全數補到正式 DOI**（見 §4），會議無 DOI 者（TEP-GNN、Anomaly Transformer、Real NVP、Deep SVDD、DKL）本就以 arXiv/PMLR 識別，非「查不到」。本輪所有受查文獻皆確認**真實存在**，零捏造、零 NOT FOUND。

---

## 4. 雙方都引錯 / 未驗證卻當已驗證 / 殘留補登

### 4a. 確認的引用錯誤（須回填修正）

| 位置 | 錯誤 | 正確 | 嚴重度 |
|---|---|---|---|
| `modernization_L3_softsensor.md` | RI DOI 標 `10.1109/TSM.2007.914388` | `10.1109/TSM.2007.914373`（`.914388` 是 Yoon & Shen 他人論文） | 🔴 必改（已被 audit/map 點名，本輪鐵證確認）→ ✅ 已修：modernization_L3_softsensor.md 已改為 .914373（devlog 2026-06-02，commit 72a4173） |

### 4b. audit 殘留 NOT VERIFIED → 本輪補到正式 DOI（含一處 audit 自身的事實錯誤）

| audit 殘留項 | 補登正確書目 | DOI | 備註 |
|---|---|---|---|
| 工業時序 CP 2025（IEEE 10870871） | Zhang & Zhou, *Uncertainty Quantification Based on Conformal Prediction for Industrial Time Series With Distribution Shift*, **IEEE T-II**, 2025 | **10.1109/TII.2025.3529920** | ✅ 補登 |
| Unified JITL 2022 | Wang, Yin, Bai, Deng, Shao, *A unified just-in-time learning paradigm…*, *Chem. Eng. Sci.* **258:117753**, 2022 | **10.1016/j.ces.2022.117753** | ✅ 補登 |
| Spatio-temporal LSTM 2023 | Zhou, Yang, Wang, Cao, *A soft sensor modeling framework embedded with domain knowledge based on spatio-temporal deep LSTM for process industry*, **Eng. Appl. Artif. Intell. 126:106847**, 2023 | **10.1016/j.engappai.2023.106847** | ⚠️ **audit 把期刊誤記為 Control Eng. Pract.**；實為 **Engineering Applications of Artificial Intelligence** |
| CVA incipient 2024 | Ji, Hou, Shao, Zhang, *Incipient fault detection for dynamic processes with canonical variate residual statistics analysis*, *Chemom. Intell. Lab. Syst.* **252:105189**, 2024 | **10.1016/j.chemolab.2024.105189** | ✅ 補登 |
| NF 時序 2023（ISA Trans.） | Guan et al., *Conditional normalizing flow for multivariate time series anomaly detection*, *ISA Trans.* **143:231–243**, 2023 | **10.1016/j.isatra.2023.09.002** | ✅ 補登；⚠️ 為通用 MTS 異常偵測（非 TEP/化工專屬），引用時須標「題材匹配為類比」 |

### 4c. 未驗證卻被當已驗證 / 需注意的細節

- **audit 期刊誤植（Spatio-temporal LSTM）**：audit 在殘留清單把該文歸 *Control Eng. Pract.*，CrossRef 確認實為 *Eng. Appl. Artif. Intell.*。屬 audit 自身**未驗證即標註**的瑕疵，已於 §4b 更正。
- **頁碼二手分歧（RI）**：92–102（部分檢索）vs 92–103（CrossRef）。`literature_crossref.md` 採 92–103 正確；任何文件若出現 92–102 應統一為 **92–103**。
- **SFA 在 docs 僅標「Shang 2015」**：屬欠完整書目而非錯引；本輪補全為 AIChE J. 61(11):3666–3682, DOI 10.1002/aic.14888。另存在易混淆同作者群 2016 *J. Process Control* 39:21–34（control-performance 主題）——**引用時務必確認用的是 2015 AIChE 那篇**（才對應「操作點變動 vs 動態異常」論述）。
- **會議論文 DOI 期待值**：MMD/MMDAgg/EnbPI/ACI/Sinkhorn/Deep Ensembles 皆無傳統 Crossref DOI；切勿為求「有 DOI」而硬編造，沿用 PMLR/JMLR vol-page 或 arXiv id 即合規。

---

### 查證方法說明
- DOI 真偽一律以 **CrossRef API**（`api.crossref.org/works/<doi>`）回傳 metadata 為準；IEEE Xplore 直連回 HTTP 418，改走 CrossRef + 出版商鏡像。
- 對「一碼之差」的 DOI（`.914373` vs `.914388`）採**雙向查證**：不僅確認正解指向目標論文，也確認誤值指向「哪一篇他人論文」，以排除「同論文兩個 DOI」的可能。
- 凡同時取得 DOI＋卷期＋頁碼者標 VERIFIED；需補/更正書目欄位者標 CORRECTED。本輪無 NOT FOUND。
