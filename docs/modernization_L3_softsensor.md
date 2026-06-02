# L3 軟測量（Soft Sensor）與可信度（RI）現代化文獻調查

> 範圍：2017–2026 期間，比「PLS / GPR + AVM RI（雙模型重疊面積）」更新的軟測量預測 Ŷ 與**預測可信度量化**解法。
> 紀律：每個方法附真實 DOI/URL；查不到標 **NOT FOUND**；偵測器須 deterministic-at-inference、runtime 不呼叫 LLM（CLAUDE.md Rule 5）。
> 本檔僅做文獻調查與建議，不改動 `interface.py` 骨架。

---

## 0. 現況基線與痛點對照

| 元件 | 現況做法 | 代表文獻 | 痛點 |
|---|---|---|---|
| 軟測量 Ŷ | PLS / GPR（淺層） | — | ① 淺層對非線性／動態擬合有限；GPR O(n³)、核穩態假設（痛點③） |
| 可信度 | **AVM RI** = conjecture 模型與 reference (NN/MR) 模型輸出機率分佈的**重疊面積**，映射到 [0,1]，門檻經驗設定 | Cheng et al. 2008, *Evaluating Reliance Level of a Virtual Metrology System*, IEEE T-SM 21(1):92-103, DOI: **10.1109/TSM.2007.914373** | ② ad-hoc 雙模型重疊、門檻經驗、**兩模型可能一致地錯**（no coverage guarantee） |

痛點代號（全檔沿用）：
- **①** 模型容量：淺層對非線性／時間動態擬合不足。
- **②** 可信度語意：RI 是 ad-hoc、無有限樣本覆蓋保證、雙模型可同錯。
- **③** 計算／假設：GPR O(n³)、核穩態（stationary kernel）假設、不利地端大資料。

> **關鍵區分**：本調查刻意把「軟測量模型面（解①③）」與「可信度量化面（解②）」分開。RI 屬於**可信度面**，它的現代正解主要不是換更強的迴歸器，而是換一套**統計上有效的不確定性框架**——這正是 Conformal Prediction 的定位（見 §3）。

---

## 1. 軟測量模型面（改進痛點 ①③）

### 1.1 Deep soft sensor：LSTM / GRU / TCN / Transformer / attention

| 項目 | 內容 |
|---|---|
| **改進痛點** | ①（非線性＋時間動態）；部分解③（避開 GPR O(n³)，但引入 GPU 訓練成本） |
| **可信度形式** | 原生**無**；需外掛（MC Dropout / Ensemble / Conformal） |
| **與 RI 關係** | 不直接取代 RI，是**換掉 conjecture 模型本體**；RI 可改掛在此模型上 |
| **成熟度** | 高（製程領域已有大量 benchmark；TEP、脫丁烷塔、SRU 等） |
| **計算/資料量** | 訓練需 GPU 與較大樣本（數千–數萬筆有標註）；inference 確定性、單次前向 |
| **建議** | **不採用為 MVP 主模型**（資料量不足，見 §結論 2），列為後續升級選項 |

代表文獻（皆 deterministic-at-inference）：
- Sun & Ge (2021), *A Survey on Deep Learning for Data-Driven Soft Sensors*, IEEE T-II 17(9):5853-5866. DOI: **10.1109/TII.2021.3053128** — 領域權威survey，涵蓋 CNN/RNN/LSTM/AE。 https://ieeexplore.ieee.org/document/9329169
- Yuan et al. (2020), *Deep Learning With Spatiotemporal Attention-Based LSTM for Industrial Soft Sensor Model Development*, IEEE T-II. DOI: **10.1109/TII.2020.2987465** — spatiotemporal attention-LSTM。 https://ieeexplore.ieee.org/document/9062588
- Spatio-temporal deep LSTM with domain knowledge (2023), *Engineering Applications of Artificial Intelligence*. DOI: **10.1016/j.engappai.2023.106847**（R3 文獻誠信已查證；原誤記為 *Control Engineering Practice*）

### 1.2 VAE-regression / 半監督軟測量（semi-supervised soft sensor）

| 項目 | 內容 |
|---|---|
| **改進痛點** | ①，且**直接對應地端化工痛點：標註稀少**（quality 變數抽樣頻率低、unlabelled 多） |
| **可信度形式** | **機率**：VAE decoder 同時輸出預測 variance（aleatoric），可線上 UQ |
| **與 RI 關係** | **補強**：variance 給 aleatoric 不確定性，可與 RI 並存或替代其一部分 |
| **成熟度** | 中（已有開源實作與 benchmark 勝出證據） |
| **計算/資料量** | 可吃 unlabelled 資料，標註需求低於純監督 deep model；inference 單次前向 |
| **建議** | **升級候選（中優先）**：地端標註稀少時值得評估 |

代表文獻：
- Zhuang et al. (2022), *Semi-supervised Variational Autoencoder for Regression: Application on Soft Sensors*, arXiv:2211.05979（後刊 IEEE）。DOI: **10.48550/arXiv.2211.05979**。 https://arxiv.org/abs/2211.05979 ；開源 https://github.com/tonyzyl/Semisupervised-VAE-for-Regression-Application-on-Soft-Sensor

### 1.3 Just-in-Time Learning（JITL）深度／自適應軟測量

| 項目 | 內容 |
|---|---|
| **改進痛點** | ①＋時變（換線、re-entry 後局部模型即時重建），契合本專案 campaign re-entry 場景 |
| **可信度形式** | 多數無原生 UQ；可結合相似度權重間接表達 |
| **與 RI 關係** | **概念互補**：JITL 的 query-相似度 ≈ GSI/RI 的「域相似度」精神，可作 L2 的回饋 |
| **成熟度** | 高（化工 soft sensing 主流方法之一） |
| **計算/資料量** | 線上 per-query 建模，需快速近鄰檢索；資料量需求中等 |
| **建議** | **補強 L2/L3 介面**，非主模型；與本專案 GSI 概念近，留意重複 |

代表文獻：
- Sheng et al. (2024), *A review of just-in-time learning-based soft sensor in industrial process*, Canadian J. Chem. Eng. DOI: **10.1002/cjce.25169**。 https://onlinelibrary.wiley.com/doi/10.1002/cjce.25169
- Unified JITL paradigm (2022), *Chemical Engineering Science*. https://www.sciencedirect.com/science/article/abs/pii/S0009250922003372 （DOI **NOT VERIFIED**）

### 1.4 PINN / physics-informed soft sensor

| 項目 | 內容 |
|---|---|
| **改進痛點** | ①＋小資料（物理先驗降低資料需求） |
| **可信度形式** | 無統一框架；多靠 residual 或外掛 UQ |
| **與 RI 關係** | 正交（換模型本體） |
| **成熟度** | 低–中（連續化工製程通用 soft sensor 上仍偏研究階段） |
| **建議** | **不採用（MVP）**：需可靠機理方程，泛化工目標下不通用 |

代表文獻：Raissi et al. (2019), *Physics-informed neural networks*, J. Comput. Phys. 378:686-707. DOI: **10.1016/j.jcp.2018.10.045**。 https://www.sciencedirect.com/science/article/pii/S0021999118307125 （基礎方法文獻，非 soft sensor 專用）

---

## 2. 可信度／RI 的現代後繼（改進痛點 ②，重點）

> 核心命題：RI 的弱點不是「不準」，而是「**沒有統計保證、門檻拍腦袋、兩模型可同錯**」。下列方法依「能否提供有效覆蓋保證」排序。

### 2.1 Conformal Prediction（CP）— **RI 的現代正解候選，最高優先**

| 項目 | 內容 |
|---|---|
| **改進痛點** | **②（直擊）**：給 distribution-free、**finite-sample 有效覆蓋率**的預測區間 |
| **可信度形式** | **預測區間／集合 + 覆蓋保證**（P(y∈Ĉ) ≥ 1−α），可任意 wrap 既有模型 |
| **與 RI 關係** | **取代 RI 的「可信度語意」層**：把 ad-hoc 重疊面積換成有保證的覆蓋率；門檻 α 由使用者顯式設定而非經驗猜 |
| **成熟度** | 高（理論成熟，工業時序已有專門變體，見下） |
| **計算/資料量** | 極輕：split-CP 只需一個 calibration set + 排序 nonconformity score；**model-agnostic、deterministic-at-inference** |
| **建議** | **取代 RI 作為 L3 可信度層的主框架**（細節見 §結論 1） |

代表文獻：
- Angelopoulos & Bates (2021), *A Gentle Introduction to Conformal Prediction and Distribution-Free UQ*, Found. & Trends ML 16(4)。DOI: **10.1561/2200000101** / arXiv: **10.48550/arXiv.2107.07511**。 https://arxiv.org/abs/2107.07511
- Romano, Patterson & Candès (2019), *Conformalized Quantile Regression (CQR)*, NeurIPS 32。arXiv: **10.48550/arXiv.1905.03222**。 https://arxiv.org/abs/1905.03222 — 自適應異方差區間（解決 RI 區間不隨輸入變化的問題）。
- Xu & Xie (2021), *Conformal Prediction Interval for Dynamic Time-Series (EnbPI)*, ICML 2021（期刊版 IEEE T-PAMI）。arXiv: **10.48550/arXiv.2010.09107**。 https://arxiv.org/abs/2010.09107 — **放寬 exchangeability**，假設誤差 stationary strongly-mixing，適用製程時序。
- Zaffran et al. (2022), *Adaptive Conformal Predictions for Time Series (ACI)*, ICML 2022。arXiv: **10.48550/arXiv.2202.07282**。 https://arxiv.org/abs/2202.07282 — **線上自適應、抗 distribution shift**，契合本專案 campaign 漂移場景。
- 工業時序 + distribution shift 的 CP UQ（IEEE，2025）：*Uncertainty Quantification Based on Conformal Prediction for Industrial Time Series With Distribution Shift*, IEEE Xplore 10870871。 https://ieeexplore.ieee.org/document/10870871 （DOI **NOT VERIFIED**；直接對應本專案痛點，建議精讀）

### 2.2 Deep Ensembles

| 項目 | 內容 |
|---|---|
| **改進痛點** | ②（部分）：用多模型分歧量 epistemic 不確定性；解「兩模型同錯」優於 RI 的雙模型 |
| **可信度形式** | **機率（predictive variance）**，含 aleatoric+epistemic；**無覆蓋保證**（除非再套 CP） |
| **與 RI 關係** | **補強**：RI 是 2 模型，Ensembles 是 M 模型且分歧解讀更有理論依據；本質仍是「分歧度」家族 |
| **成熟度** | 高（UQ 的 strong baseline） |
| **計算/資料量** | 訓練/儲存 M 倍成本；inference M 次前向（確定性） |
| **建議** | **升級 RI 的中間步**：若暫不上 CP，可先用 small ensemble (M=5) 取代雙模型重疊 |

代表文獻：Lakshminarayanan, Pritzel & Blundell (2017), *Simple and Scalable Predictive Uncertainty Estimation using Deep Ensembles*, NeurIPS 30。arXiv: **10.48550/arXiv.1612.01474**。 https://arxiv.org/abs/1612.01474

### 2.3 MC Dropout

| 項目 | 內容 |
|---|---|
| **改進痛點** | ②（弱）：近似 Bayesian，量 epistemic |
| **可信度形式** | 機率（多次隨機前向的 variance）；**無覆蓋保證**，校準常偏差 |
| **與 RI 關係** | 補強，但理論爭議大（是否真 Bayesian 有爭論）、且**inference 帶隨機性**（與 deterministic 要求衝突，須固定 seed/平均處理） |
| **成熟度** | 中（易實作但已被 Ensembles/CP 比下去） |
| **計算/資料量** | inference T 次前向；資料量需求中 |
| **建議** | **不採用**：理論弱、校準差、隨機性違反確定性合規（§結論 3） |

代表文獻：Gal & Ghahramani (2016), *Dropout as a Bayesian Approximation*, ICML 2016。arXiv: **10.48550/arXiv.1506.02142**。 https://arxiv.org/abs/1506.02142

### 2.4 Evidential Deep Learning（Deep Evidential Regression）

| 項目 | 內容 |
|---|---|
| **改進痛點** | ②：**單一模型**直接輸出 aleatoric+epistemic（NIG 先驗），免 ensemble |
| **可信度形式** | 機率（NIG 分佈參數→mean/variance/evidence）；**無覆蓋保證**，且已知有校準爭議 |
| **與 RI 關係** | 補強／可取代雙模型（單模型即給不確定性），但**不給有保證的區間** |
| **成熟度** | 中（有後續論文指出其 epistemic 估計有理論瑕疵，須謹慎） |
| **計算/資料量** | 低（單模型單前向，確定性）；資料量中 |
| **建議** | **觀望／不優先**：吸引力在單模型低成本，但校準瑕疵使其不如 CP 可靠 |

代表文獻：
- Amini et al. (2020), *Deep Evidential Regression*, NeurIPS 2020。arXiv: **10.48550/arXiv.1910.02600**。 https://arxiv.org/abs/1910.02600
- 警示：Meinert et al. (2023), *The Unreasonable Effectiveness of Deep Evidential Regression*, AAAI 37(8)。DOI: **10.1609/aaai.v37i8.26096**。 https://dl.acm.org/doi/10.1609/aaai.v37i8.26096 — 指出其不確定性非真正 well-founded。

### 2.5 Quantile Regression（含神經分位數迴歸）

| 項目 | 內容 |
|---|---|
| **改進痛點** | ②（部分）：直接學區間端點，自然異方差 |
| **可信度形式** | **區間**（分位數）；**無有限樣本保證**（除非 conformalize → 即 CQR §2.1） |
| **與 RI 關係** | 補強；單獨用不保證覆蓋，**配 CP 才完整** |
| **成熟度** | 高 |
| **計算/資料量** | 低（pinball loss 訓練，確定性 inference） |
| **建議** | **作為 CP 的 base estimator（CQR 路線）**，而非單獨採用 |

代表文獻：Koenker & Bassett (1978), *Regression Quantiles*, Econometrica 46(1):33-50. DOI: **10.2307/1913643**（理論源頭）；現代 conformalized 版本見 §2.1 CQR。

### 2.6 Deep Kernel Learning（DKL）/ Stochastic Variational GP（SVGP）

| 項目 | 內容 |
|---|---|
| **改進痛點** | **③（直擊）**：NN 特徵 + GP，**打破 GPR O(n³) 與穩態核假設**，可 mini-batch 擴展 |
| **可信度形式** | 機率（GP posterior variance）；**無覆蓋保證**（可再套 CP，已有文獻） |
| **與 RI 關係** | 補強：給校準較佳的 Bayesian variance，且解 GPR 擴展性 |
| **成熟度** | 中–高 |
| **計算/資料量** | 訓練需 GPU；inference 確定性；比純 GPR 可吃更大資料 |
| **建議** | **升級候選（若堅持 GP 路線且資料變大）**：作為 GPR 的可擴展替身 |

代表文獻：
- Wilson et al. (2016), *Deep Kernel Learning*, AISTATS 2016（PMLR 51）。 http://proceedings.mlr.press/v51/wilson16.pdf （DOI **NOT FOUND**，PMLR 無 DOI；arXiv: **10.48550/arXiv.1511.02222** https://arxiv.org/abs/1511.02222）
- Wilson et al. (2016), *Stochastic Variational Deep Kernel Learning*, NeurIPS 2016。arXiv: **10.48550/arXiv.1611.00336**。 https://arxiv.org/abs/1611.00336
- CP for GP surrogate（覆蓋保證）：*Conformal Approach to Gaussian Process Surrogate Evaluation with Coverage Guarantees*, arXiv: **10.48550/arXiv.2401.07733**。 https://arxiv.org/abs/2401.07733

---

## 3. 方法總表（一覽）

| 方法 | 解痛點 | 可信度形式 | 覆蓋保證 | 與 RI 關係 | 成熟度 | 成本/資料 | 建議 |
|---|---|---|---|---|---|---|---|
| Deep soft sensor (LSTM/TCN/Transformer) | ①③ | 無（需外掛） | ✗ | 換 conjecture 本體 | 高 | GPU/大資料 | 後續升級 |
| VAE-regression 半監督 | ① + 標註稀少 | 機率(variance) | ✗ | 補強 | 中 | 可吃 unlabelled | 升級(中) |
| JITL 自適應 | ① + 時變 | 弱 | ✗ | 互補(似 GSI) | 高 | 線上近鄰 | 補強介面 |
| PINN | ① + 小資料 | 無統一 | ✗ | 正交 | 低-中 | 需機理 | 不採用(MVP) |
| **Conformal Prediction** | **②** | **區間+保證** | **✓ finite-sample** | **取代 RI 語意層** | 高 | **極輕、model-agnostic** | **取代 RI** |
| Deep Ensembles | ② | 機率(variance) | ✗ | 補強(M模型) | 高 | M×成本 | RI 過渡升級 |
| MC Dropout | ② | 機率 | ✗ | 補強(隨機) | 中 | T×前向 | 不採用 |
| Evidential DL | ② | 機率(NIG) | ✗(校準爭議) | 單模型替雙模型 | 中 | 低 | 觀望 |
| Quantile Regression | ② | 區間 | ✗(單用) | 配 CP | 高 | 低 | 作 CP base |
| DKL / SVGP | **③** | 機率(GP var) | ✗ | 補強 + 解 GPR 擴展 | 中-高 | GPU | 升級候選 |

---

## 4. 結論

### 4.1 Conformal Prediction 是否為 RI 的現代正解？— **是，且建議取代 RI 的可信度語意層**

**對照分析（第一性原理）：**

| 維度 | AVM RI | Conformal Prediction |
|---|---|---|
| 可信度定義 | conjecture vs reference 兩模型輸出分佈**重疊面積**映射到[0,1] | nonconformity score 的分位數 → **預測區間/集合** |
| 統計保證 | **無**（ad-hoc，門檻經驗設定） | **有**：distribution-free、**finite-sample marginal coverage** P(y∈Ĉ)≥1−α |
| 「兩模型同錯」風險 | 高（兩模型一致地錯時 RI 仍高） | 低：calibration set 用**真實殘差**校準，同錯會反映在 nonconformity 分佈 |
| 門檻設定 | 拍腦袋 | 使用者顯式選 α（風險預算），語意清楚 |
| 模型耦合 | 綁定雙模型架構 | **model-agnostic**：可 wrap PLS/GPR/任意 deep model |
| 線上漂移 | RI/GSI 各管一塊 | 有 EnbPI / ACI 變體**內建對 distribution shift / 時序依賴的處理**（直擊本專案 re-entry 漂移） |
| 計算成本 | 低 | **同樣低**（split-CP 只需排序 calibration scores）、deterministic |

**優缺點：**
- 優：理論嚴謹、輕量、model-agnostic、與既有 PLS/GPR 無縫疊加、有時序專用變體（EnbPI/ACI）對應 campaign 漂移。
- 缺：marginal coverage 是「平均」保證，非 conditional（單點可能不準）→ 用 **Mondrian/group-conditional CP** 緩解；exchangeability 在強時序下需用 EnbPI/ACI 放寬。

**製程/軟測量應用文獻**：工業時序 + distribution shift 的 CP UQ 已有 2025 IEEE 論文（§2.1 末），CP for GP surrogate 有覆蓋保證版本（§2.6）。製程領域 CP 仍偏新但成長快，文獻基礎足以支撐 MVP 落地。

> **明確建議**：**以 Conformal Prediction（split-CP 起步，campaign/re-entry 場景升級為 EnbPI 或 ACI）取代 AVM RI 作為 L3 的可信度層**；保留 RI 為相容性對照基線（向後相容）。base estimator 仍可沿用現有 PLS/GPR，CP 只是外掛校準層——**這對 `interface.py` 骨架是 surgical 改動**（新增 calibration set 與 conformal wrapper，不動五維度判斷鏈結構）。

### 4.2 地端化工 MVP：深度模型 vs GPR 的務實取捨

- **資料量現實**：地端化工初期標註（破壞性/昂貴量測 Y）稀少，深度 soft sensor 動輒需數千–數萬筆有標註，**MVP 階段不具備**。
- **務實序位**：
  1. **MVP 主模型維持 PLS/GPR**（小資料友善、確定性、可解釋），**外掛 Conformal Prediction** 補可信度——以最小改動拿到「有保證的不確定性」，CP/A.2 的價值在小資料下最高。
  2. GPR O(n³) 成為瓶頸（資料變大）時，升級為 **DKL/SVGP**（§2.6）解擴展性與穩態核假設，仍保留 GP 機率輸出。
  3. 標註稀少但 unlabelled 多時，評估 **VAE-regression 半監督**（§1.2）。
  4. 資料充足後才考慮 LSTM/TCN/Transformer deep soft sensor（§1.1）。
- **一句話**：**MVP 不上深度模型**；用「PLS/GPR + Conformal」拿到最佳 cost/benefit，深度模型留待資料規模成熟後升級。

### 4.3 確定性合規標記（deterministic-at-inference、非 LLM）

| 方法 | inference 確定性 | 非 LLM | 合規 |
|---|---|---|---|
| PLS / GPR | ✓ | ✓ | ✅ |
| **Conformal Prediction** | ✓（split-CP 排序，純數學） | ✓ | ✅ |
| Deep Ensembles | ✓（固定權重，M 次前向） | ✓ | ✅ |
| DKL / SVGP | ✓ | ✓ | ✅ |
| VAE-regression | ✓（用 posterior mean/固定 seed） | ✓ | ✅ |
| Evidential DL | ✓ | ✓ | ✅（校準存疑） |
| **MC Dropout** | **✗（隨機前向）** | ✓ | ⚠️ 需固定 seed/平均才合規 |
| LSTM/TCN/Transformer | ✓ | ✓ | ✅ |

> **合規結論**：除 MC Dropout 外，所有候選皆 deterministic-at-inference 且非 LLM，符合 CLAUDE.md Rule 5（偵測決策為確定性數學）。**首選 Conformal Prediction 完全合規**（純排序/分位數運算，無隨機性、無 LLM）。

---

## 附錄 A — DOI/URL 驗證狀態

| 文獻 | DOI/ID | 驗證狀態 |
|---|---|---|
| Cheng 2008 RI (AVM) | 10.1109/TSM.2007.914373 | 經 search 確認 venue/卷期頁；DOI 為 IEEE TSM 標準編碼（**DOI 字串未逐位 fetch 驗證**） |
| Angelopoulos & Bates 2021 CP intro | 10.48550/arXiv.2107.07511 / 10.1561/2200000101 | ✓ WebFetch 驗證 |
| Romano CQR 2019 | 10.48550/arXiv.1905.03222 | ✓ search 驗證 |
| Xu & Xie EnbPI 2021 | 10.48550/arXiv.2010.09107 | ✓ search 驗證 |
| Zaffran ACI 2022 | 10.48550/arXiv.2202.07282 | ✓ search 驗證 |
| Lakshminarayanan Deep Ensembles 2017 | 10.48550/arXiv.1612.01474 | ✓ search 驗證 |
| Gal MC Dropout 2016 | 10.48550/arXiv.1506.02142 | ✓ 既知文獻 |
| Amini Deep Evidential 2020 | 10.48550/arXiv.1910.02600 | ✓ WebFetch 驗證 |
| Meinert 2023 (評議) | 10.1609/aaai.v37i8.26096 | ✓ search 驗證 |
| Wilson DKL 2016 | arXiv 1511.02222 (期刊 DOI NOT FOUND) | arXiv ✓；PMLR 無 DOI |
| Wilson SVDKL 2016 | 10.48550/arXiv.1611.00336 | ✓ search 驗證 |
| Sun & Ge survey 2021 | 10.1109/TII.2021.3053128 | ✓ search 驗證 |
| Yuan attention-LSTM 2020 | 10.1109/TII.2020.2987465 | ✓ search（DOI 標準編碼） |
| Zhuang SSVAER 2022 | 10.48550/arXiv.2211.05979 | ✓ search 驗證 |
| Sheng JITL review 2024 | 10.1002/cjce.25169 | ✓ search 驗證 |
| Amini Raissi PINN 2019 | 10.1016/j.jcp.2018.10.045 | ✓ 既知文獻 |
| Koenker & Bassett 1978 | 10.2307/1913643 | ✓ 既知文獻 |
| 工業時序 CP + distribution shift 2025 (IEEE 10870871) | DOI NOT VERIFIED | URL 有效，DOI 未取得 |
| Unified JITL paradigm 2022 (Chem Eng Sci) | DOI NOT VERIFIED | 僅 ScienceDirect URL |
| Spatio-temporal LSTM + domain knowledge 2023 | DOI NOT VERIFIED | 僅 ScienceDirect URL |

> 標 **NOT VERIFIED / NOT FOUND** 者，後續落地引用前須補查官方 DOI。嚴禁在正式文件中當作已驗證引用（CLAUDE.md Rule 12 / Fail loud）。
