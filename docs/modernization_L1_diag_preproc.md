# L1 資料品質閘 / 肇因診斷 / 連續製程分段 / 時序對齊 — 現代化方案調查（2017–2026）

> 範圍：四個模組的現代替代方案文獻調查。每方法附真實 DOI/URL；查不到標 **NOT FOUND**。
> 偵測決策一律為**確定性數學**（Rule 5），以下方法均不在 runtime 呼叫 LLM。
> 術語保留 English；判讀以本檔為準，需交叉驗證者再回 `docs/literature_crossref.md`。

調查日期：2026-06-01

加註採用狀態：FastMCD（dqi_x.py）、RBC（mspc.py）、ruptures PELT（segment.py/features.py）、Sakoe-Chiba band DTW（batch_dtw.py）皆已建；iForest/BOCPD/soft-DTW/AE/causal 未建仍為候選；本檔部分宣稱經 redteam_reconciliation.md（C4/D7/D8）降級，見各節註

---

## 模組 1 — L1 資料品質閘（現況：DQI_x = PCA k 維 Euclidean 距離 + sanity check）

加註：現況已含 FastMCD robust 中心/協方差＋MCD-support 門檻＋median/MAD 標準化（本檔建議已採納並強化，dqi_x.py；M2, 2026-06-02）

**痛點**：純線性、Euclidean 對 masking/swamping 敏感、未含現代感測器故障偵測（黏滯、drift、bias、漏量程）。

| 名稱 | 解了哪個痛點 | 相對現有優勢 | 成熟度 | 計算成本 | 建議 | 代表文獻 + DOI |
|---|---|---|---|---|---|---|
| **Robust covariance / FastMCD** | Euclidean/sample-cov 被離群點污染 → baseline 估計失真 | 以 robust Mahalanobis 取代 sample Mahalanobis，抗 masking；affine equivariant；可直接餵 T²/SPE | 高（成熟統計，sklearn `MinCovDet`） | FastMCD 近線性於 n，重算頻率低（離線擬合 baseline） | **補強**：把 L1 baseline 的 cov 估計換成 MCD，立即抗污染，介面不變 | Hubert et al., *WIREs Comp Stat* 2018, DOI [10.1002/wics.1421](https://doi.org/10.1002/wics.1421)；FastMCD: Rousseeuw & Van Driessen, *Technometrics* 1999, DOI [10.1080/00401706.1999.10485670](https://doi.org/10.1080/00401706.1999.10485670) |
| **Isolation Forest (iForest)** | 線性閘對非線性、局部稠密異常失明 | 非參數、非線性、不需密度估計；O(n) 訓練、低記憶體；天然 anomaly score 可校準成 0–1 | 高（sklearn `IsolationForest`，工業案例多） | 訓練 O(t·ψ·logψ)（子採樣 ψ），打分 O(logψ) — 線上極輕 | **補強**：作為 DQI_x 的非線性 second-opinion，與 robust-Mahalanobis 取 max | Liu, Ting & Zhou, *IEEE ICDM* 2008, DOI [10.1109/ICDM.2008.17](https://doi.org/10.1109/ICDM.2008.17)；期刊版 *ACM TKDD* 2012, DOI [10.1145/2133360.2133363](https://doi.org/10.1145/2133360.2133363) |
| **Autoencoder / VAE 重構式感測器驗證** | 線性 PCA 殘差抓不到非線性 X 結構；單感測器故障難定位 | 非線性重構，殘差即 deep-SPE；VAE 給機率殘差與 deep reconstruction-based contribution | 中高（TEP benchmark 多，但需訓練/調參、可解釋性較弱） | 訓練重（GPU 佳），推論 O(forward) 中等；與「確定性 runtime」相容（權重凍結後純前饋） | **補強（選配）**：作為 L1 進階非線性閘，但須權衡訓練成本與 Rule 2 簡單性；先上 MCD+iForest，AE 留作 v2 | Zhu, Jiang & Liu, *Sensors* 2022, 22(1):227, DOI [10.3390/s22010227](https://doi.org/10.3390/s22010227) |

**模組 1 小結**：MCD（取代受污染的 cov）+ iForest（非線性 second-opinion）是低成本高回報；AE/VAE 是高回報但成本與可解釋性需評估，列為 v2。

---

## 模組 2 — 肇因診斷（現況：MSPC contribution plot / AVM ISI）

**痛點**：contribution plot 有 **smearing**（相關性使正常變數的 contribution 被抹高，甚至超過真故障變數）；ISI 純單變數，對隱性多變量飄移失明。

| 名稱 | 解了哪個痛點 | 相對現有優勢 | 成熟度 | 計算成本 | 建議 | 代表文獻 + DOI |
|---|---|---|---|---|---|---|
| **Reconstruction-Based Contribution (RBC)** | 直接針對 contribution 的 smearing | 沿每變數方向重構監測指標、取消故障量；理論保證**單變數大故障下必正確定位**（傳統 contribution 無此保證） | 高（化工原生、被廣泛延伸；公式封閉解） | 封閉解，O(m) per 變數，極輕；與現有 PCA/T²/SPE 共用模型 | **取代**：以 RBC 直接取代原始 contribution plot，幾乎零額外成本、嚴格更優 | Alcala & Qin, *Automatica* 2009, 45(7):1593–1600, DOI [10.1016/j.automatica.2009.02.027](https://doi.org/10.1016/j.automatica.2009.02.027) |
| **多維 RBC + Bayesian 嚴重度分級** | 單方向 RBC 對多變數/微小故障力有未逮 | 多維重構同時取消多變數，配 Bayesian decision 給嚴重度等級 | 中高 | 多維重構成本隨候選方向組合上升，可剪枝 | **補強**：作為 RBC 的進階模式，處理多變數隱性飄移 | Multivariate/minor fault diagnosis with severity, *Control Eng. Practice* 2021, [ScienceDirect S0959152421000184](https://www.sciencedirect.com/science/article/abs/pii/S0959152421000184)（精確 DOI **NOT FOUND**，以 PII 為準） |
| **SHAP / feature attribution 用於製程監控** | contribution 對非線性模型不適用；需模型無關歸因 | 模型無關（含 AE/tree）、博弈論一致性；TreeSHAP 高效；可做根因特徵排序 | 中（製程領域案例增加中，但屬解釋而非偵測，須防誤當因果） | KernelSHAP 昂貴；TreeSHAP 對樹模型多項式時間 | **補強**：僅在用非線性偵測器（AE/IF）時做歸因；**不可取代** RBC 的線性嚴格保證 | Combining SHAP and Causal Analysis, arXiv 2025, [arXiv:2510.23817](https://arxiv.org/abs/2510.23817) |
| **Causal discovery 根因（Granger / transfer entropy）** | contribution/SHAP 是相關非因果，無法定位**傳播源頭** | 給變數間因果方向 → 區分「根因」與「被波及」；明確緩解 smearing 的因果版 | 中（化工 root-cause 文獻成熟，但需穩態/足夠樣本，非穩態挑戰大） | Granger 廉價易自動化；transfer entropy 較貴；需 campaign 級資料窗 | **補強（L4/campaign 層）**：在偵測到飄移後做離線根因排序，非線上即時 | Granger-causality RCD, *Ind. Eng. Chem. Res.* 2018, DOI [10.1021/acs.iecr.8b00697](https://doi.org/10.1021/acs.iecr.8b00697)；MTCD 多感測因果, *Control Eng. Practice* 2022, [ScienceDirect S0959152422002293](https://www.sciencedirect.com/science/article/abs/pii/S0959152422002293)（精確 DOI **NOT FOUND**） |

**模組 2 小結**：**RBC 直接取代原始 contribution** 是本次最明確的「零成本嚴格升級」。SHAP/causal 為補強層，分別服務非線性偵測器與 campaign 級根因，不取代 RBC。

---

## 模組 3 — 連續製程分段（現況：SSD 穩態偵測 + grade transition 規則）

**痛點**：window 長度無通解、規則啟發式、門檻手刻、不可移植。

| 名稱 | 解了哪個痛點 | 相對現有優勢 | 成熟度 | 計算成本 | 建議 | 代表文獻 + DOI |
|---|---|---|---|---|---|---|
| **ruptures / PELT** | 手刻 window + 啟發式規則 | 把分段化為「懲罰化最佳分割」優化問題；PELT 給**精確 O(n) 線性時間**解；統一 cost model（mean/var/linear/rbf） | 高（純 Python，依賴 numpy/scipy；review 涵蓋 140+ 法） | PELT 近線性；Binseg/Window 更輕；離線批次友善 | **取代**：以 ruptures(PELT) 取代手刻 SSD + grade transition，修正：PELT 只給邊界，穩態判定仍需 ramp/std 準則（features.py），實為 penalty＋穩態準則兩組超參（reconciliation D8「未真消手刻規則」）；penalty 以 TEP 掃描定值（config.ssd_penalty） | ruptures 套件: Truong, Oudre & Vayatis, [arXiv:1801.00826](https://arxiv.org/abs/1801.00826)；綜述: *Signal Processing* 2020, 167:107299, DOI [10.1016/j.sigpro.2019.107299](https://doi.org/10.1016/j.sigpro.2019.107299) |
| **Kernel change-point (KCP / rbf cost)** | 線性/均值-變異數 cost 抓不到分佈形狀改變 | RKHS 嵌入，characteristic kernel 偵測**任意分佈變化**；ruptures 內建 `model="rbf"` | 中高（理論一致性已證；penalty 選擇需調） | kernel Gram 矩陣 O(n²)，大窗需降採樣 | **補強**：對「均值不變但相關結構變」的隱性 grade transition，用 rbf cost | Garreau & Arlot, *Electron. J. Statist.* 2018, DOI [10.1214/18-EJS1513](https://doi.org/10.1214/18-EJS1513)；Arlot, Celisse & Harchaoui, *JMLR* 2019, [JMLR v20/16-155](https://jmlr.org/papers/v20/16-155.html) |
| **Bayesian Online CPD (BOCPD)** | 離線分段無法即時偵測 re-entry 切換點 | **線上**遞迴、exact、不需預設 regime 數；run-length 機率可當切換置信度 | 高（演算法成熟，多開源實作） | 每步 O(t)（可截斷 run-length 成 O(1) 攤銷）；線上極輕 | **補強**：作為線上 re-entry 切換偵測（campaign 邊界即時化），與離線 ruptures 互補 | Adams & MacKay, 2007, [arXiv:0710.3742](https://arxiv.org/abs/0710.3742) |

**模組 3 小結**：**ruptures(PELT) 取代手刻 SSD** 是低成本高回報。rbf-kernel cost 處理隱性分佈漂移；BOCPD 補上線上 re-entry 偵測。

---

## 模組 4 — 時序對齊（現況：X→Y delay 估計；批次軌跡 DTW）

**痛點**：DTW **O(n²)**、不可微（無法接入梯度學習）、病態映射（singularity / 過度 warp）。

| 名稱 | 解了哪個痛點 | 相對現有優勢 | 成熟度 | 計算成本 | 建議 | 代表文獻 + DOI |
|---|---|---|---|---|---|---|
| **FastDTW + Sakoe-Chiba band** | O(n²) 成本、過度 warp | 多解析度遞迴投影 → **近線性 O(n)**；band 約束抑制病態映射 | 高（多語言實作；經典） | 線上路徑 O(n·radius)，符合 Rule 6 線上成本上限 | **取代/補強**：批次軌跡 DTW 改用 band-constrained / FastDTW；屬約束版，數學仍確定性 | Salvador & Chan, *Intelligent Data Analysis* 2007, 11(5):561–580, DOI [10.3233/IDA-2007-11508](https://doi.org/10.3233/IDA-2007-11508)（Sakoe-Chiba 原典: Sakoe & Chiba, *IEEE TASSP* 1978, DOI [10.1109/TASSP.1978.1163055](https://doi.org/10.1109/TASSP.1978.1163055)） |
| **soft-DTW（可微 DTW）** | DTW 的 min 不可微，無法做平均/聚類/梯度對齊 | (min,+) → (+,×) soft-min，**處處可微**；可算 DTW barycenter（軌跡平均模板）；值與梯度皆 O(n²) | 高（開源 `soft-dtw`、`tslearn`） | 仍 O(n²)（含 band 可降）；建模/離線 barycenter 用途為主 | **補強**：用於建構 golden-A **軌跡平均模板**與 DTW-barycenter，再用 band-DTW 對齊；對齊決策仍確定性 | Cuturi & Blondel, *ICML* 2017, [arXiv:1703.01541](https://arxiv.org/abs/1703.01541) / [PMLR v70](https://proceedings.mlr.press/v70/cuturi17a.html) |
| **現代 time-delay estimation（dynamic sliding window / DCNN）** | 靜態 X→Y delay 假設；非線性時變延遲 | 動態滑窗/網路抽取時變 delay；MTCD 的 temporal registration network 同時做對齊+因果 | 中（工業案例增加，但需訓練；可退化為純滑窗互相關的確定性版） | 滑窗互相關廉價；DCNN 訓練重、推論中等 | **補強（選配）**：時變 delay 時用滑窗互相關（確定性）；DCNN 版列 v2 並評估 Rule 5 合規 | NeuroTD, *bioRxiv* 2024, DOI [10.1101/2024.10.28.620662](https://doi.org/10.1101/2024.10.28.620662)；SyncNet, [arXiv:2203.14639](https://arxiv.org/abs/2203.14639) |

**模組 4 小結**：**band-constrained / FastDTW 取代裸 DTW** 解 O(n²) 與病態映射，低成本高回報。soft-DTW 用於離線 golden-A 模板平均（不進線上決策）；neural TDE 列選配。

---

## 結論

### 1. 各模組最值得納入的 1–2 個現代方法
| 模組 | 首選（必納） | 次選（補強） |
|---|---|---|
| L1 資料品質閘 | **FastMCD robust covariance**（抗污染 baseline） | **Isolation Forest**（非線性 second-opinion） |
| 肇因診斷 | **RBC**（取代 contribution，消 smearing） | causal/Granger 根因（campaign 層離線） |
| 連續製程分段 | **ruptures(PELT)**（取代手刻 SSD） | rbf-kernel CPD + **BOCPD**（線上 re-entry） |
| 時序對齊 | **band-constrained / FastDTW**（解 O(n²)） | **soft-DTW**（離線 golden-A 模板平均） |

### 2. 低成本高回報（可立即換）清單
| 換什麼 | 換成 | 為何低成本高回報 |
|---|---|---|
| 原始 MSPC contribution plot | **RBC** (Alcala & Qin 2009) | 封閉解 O(m)、共用現有 PCA 模型；理論保證單變數故障必正確、降級：消**單故障** smearing；多方向漂移並存時 RBC 自身仍殘留 smearing（reconciliation C4/H3——「嚴格消 smearing」為假），RBC 為「定位非因果」（mspc.py docstring 已按此實作註記） |
| 手刻 SSD + grade transition 規則 | **ruptures(PELT)** | 純 Python/numpy、PELT 近線性；門檻塌縮成單一 penalty 超參，消除 window 長度啟發式 |
| sample covariance（L1 baseline） | **FastMCD** (sklearn `MinCovDet`) | 一行替換、近線性、抗 masking；T²/SPE 介面不變 |
| 裸 O(n²) DTW | **Sakoe-Chiba band / FastDTW** | 近線性、抑制病態映射；符合 Rule 6 線上成本上限 |

> 以上四項皆**介面相容、確定性、可即插**，建議優先落地。iForest、BOCPD、soft-DTW 為第二波，AE/VAE、causal-discovery、neural-TDE 列 v2 並先評估 Rule 2（簡單性）與 Rule 5（確定性）合規。

### 3. 確定性合規標記
| 方法 | runtime 確定性 | 說明 |
|---|---|---|
| FastMCD / Mahalanobis | ✅ 確定性 | 修正：FastMCD 含隨機子集抽樣，須鎖 random_state＋顯式 support_fraction 才可重現（reconciliation D7；config.py:22,25 已如此治理）；且 p≫n 時 MinCovDet 靜默不穩（需 n>2p 或 PCA-score 預降維，highdim.py；B2 於 p=128 實測） |
| Isolation Forest | ✅ 確定性 | 訓練後森林凍結，打分為確定性遍歷 |
| RBC / 多維 RBC | ✅ 確定性 | 線性代數閉式 |
| ruptures PELT / kernel CPD | ✅ 確定性 | 動態規劃最佳化 |
| BOCPD | ✅ 確定性 | 貝氏遞迴閉式（指數族） |
| FastDTW / band-DTW / soft-DTW | ✅ 確定性 | DP；soft-DTW 僅離線建模用 |
| AE / VAE | ⚠️ 條件式 | 權重凍結後純前饋為確定性；**訓練**含隨機性，須固定 seed 並版本化權重 |
| SHAP | ⚠️ 條件式 | TreeSHAP 確定性；KernelSHAP 採樣須固定 seed |
| Granger / transfer entropy | ✅ 確定性 | 統計檢定閉式 |
| neural TDE（DCNN） | ⚠️ 條件式 | 訓練含隨機；滑窗互相關退化版為確定性 |

> ⚠️ 條件式者若納入，須固定 seed + 凍結並版本化權重，且**僅用於歸因/建模，不做線上偵測 routing**（Rule 5）。

---

## 待清理 / NOT FOUND
- 多維 RBC + Bayesian severity（*Control Eng. Practice* 2021, PII S0959152421000184）精確 DOI **NOT FOUND**，僅得 ScienceDirect PII。
- MTCD 多感測因果（*Control Eng. Practice* 2022, PII S0959152422002293）精確 DOI **NOT FOUND**，僅得 PII。
- 上述兩筆納入前須回 `docs/literature_crossref.md` 補正式 DOI 後逐筆查證。
