# L2 多變量製程監控現代化調查（2017–2026）

> 調查日期：2026-06-01
> 範圍：以「比經典線性 PCA→T²/SPE/GSI(Mahalanobis) 更新的多變量製程監控（L2）解法」為對象，調查現代候選方法。
> 原則：**嚴禁捏造**。每個方法的代表文獻附真實 DOI/URL；查不到標 `NOT FOUND`。技術術語保留英文。
> 對齊：方法歸類與 transfer 風險判斷沿用 `docs/literature_crossref.md` 的半導體↔化工跨域慣例；MSPC 公式分歧時優先採化工原生且更經驗證者（Rule 7）。

---

## 0. 現況與痛點（被取代/升級的對象）

本專案 L2 現用**線性 PCA** 導出三統計量：
- **T²**（Hotelling）：主元子空間（model subspace）內變異。
- **SPE / Q**（squared prediction error）：殘差子空間（residual subspace）。
- **GSI**（Global Similarity Index）：全空間 Mahalanobis-like 相似度（源自 Cheng et al. 2008，見 `literature_crossref.md`）。

已知四個痛點（後文以 ①②③④ 引用）：

| 編號 | 痛點 | 數學根因 |
|---|---|---|
| ① | 只抓**線性**相關 | PCA 用二階共變異矩陣，捕捉不到非線性 X 結構 |
| ② | 假設**近高斯** | T²/SPE 控制限由 F/χ² 分佈或常態假設推導 |
| ③ | **靜態模型**對時變製程失效 | 不含時間落後（lag）結構，無法表達自相關與動態 |
| ④ | 高度共線性下 **Mahalanobis 數值不穩** | 協方差矩陣近奇異，逆矩陣放大噪聲 |

> 與本專案目標的對齊點：我們要抓的是「每個感測器都在單變數規格內、但多變量關係已偏移」的**隱性飄移**，且要求**可解釋 + 明確控制限 + inference 端確定性（不呼叫 LLM）**。下文每個方法都針對這三項打分。

---

## 1. 現代候選方法逐項調查

> 欄位：核心改進（解了哪個痛點）｜可否導 T²/SPE 類統計量與控制限｜產業成熟度｜計算成本｜**建議（augment／replace／不採用）+ 理由**｜代表文獻 + DOI。

---

### 1.1 Kernel PCA（KPCA）

- **核心改進**：解 ①。透過 kernel trick（多為 RBF）將輸入映射至高維 feature space 再做 PCA，捕捉非線性相關。
- **可導統計量/控制限**：✅ 可。在 feature space 直接定義 T²、SPE 兩統計量；控制限傳統用高斯假設，但已知 feature space 多非高斯，現代多改用 **KDE（kernel density estimation）** 估控制限，較 Gaussian 假設更早偵測且減少誤報。
- **成熟度**：**有大量產業案例研究**（化工 benchmark TEP、廢水 BSM1 等）；屬經典深耕方法，文獻量大。
- **計算成本**：訓練需建 N×N kernel 矩陣（O(N²)~O(N³)）；**線上每個樣本須對全部 N 個訓練樣本算 kernel**，N 大時線上成本顯著，須降採樣/稀疏化。對應本專案 Rule 6 線上成本上限需注意。
- **建議：augment（條件性）**。若 TEP 上發現純線性 PCA 殘留漏抓的非線性飄移，KPCA 是**最小增量**的非線性升級（仍輸出 T²/SPE，可解釋、確定性）。風險：kernel 寬度 σ 與訓練集選擇敏感；線上成本隨 N 漲。
- **代表文獻**：Lee, Yoo, Choi, Vanrolleghem, Lee, "Nonlinear process monitoring using kernel principal component analysis", *Chemical Engineering Science*, vol.59, no.1, pp.223–234, 2004. DOI: 10.1016/j.ces.2003.09.012 · <https://www.sciencedirect.com/science/article/abs/pii/S0009250903004652>
  - KDE 控制限近作："Process Monitoring Using Kernel PCA and Kernel Density Estimation-Based SSGLR Method for Nonlinear Fault Detection", *Applied Sciences*, vol.12, no.6, 2981, 2022. DOI: 10.3390/app12062981 · <https://www.mdpi.com/2076-3417/12/6/2981>

---

### 1.2 Dynamic PCA（DPCA）

- **核心改進**：解 ③。將時間落後變數（time-lagged，X_t, X_{t-1}, …, X_{t-l}）堆疊後再做 PCA，把自相關/動態納入模型。
- **可導統計量/控制限**：✅ 可，與 PCA 同樣輸出 T²、SPE，控制限推導不變（仍受 ② 高斯假設限制）。
- **成熟度**：**經典且廣用**；TEP 上的標準 baseline 之一。
- **計算成本**：**極低**。僅增加堆疊維度（lag 數 × 變數數），訓練/線上與 PCA 同數量級。
- **建議：augment（高優先）**。是對 PCA **最便宜**的升級，幾乎零額外依賴、零 LLM、確定性、控制限照舊。本專案連續製程（TEP）有強自相關，DPCA 直接補上 ③。風險：lag 階數 l 需選定（用 AR 殘差白化準則）。
- **代表文獻**：Ku, Storer, Georgakis, "Disturbance detection and isolation by dynamic principal component analysis", *Chemometrics and Intelligent Laboratory Systems*, vol.30, no.1, pp.179–196, 1995. DOI: 10.1016/0169-7439(95)00076-3 · <https://www.sciencedirect.com/science/article/abs/pii/0169743995000763>

---

### 1.3 Canonical Variate Analysis（CVA）

- **核心改進**：解 ③（也部分緩解 ④）。屬 subspace identification，從過去/未來 Hankel 矩陣間最大化相關，萃取狀態空間式的 canonical variates，對**動態製程**比 DPCA 更貼合系統理論。
- **可導統計量/控制限**：✅ 可，導出 **T²（狀態空間 Ts²/Te²）與 Q/SPE 類殘差統計量**，控制限可由 F/χ² 或經驗分位推。
- **成熟度**：**有產業案例（化工 benchmark）**；TEP 上多次被驗證「對 incipient（緩起）故障優於 DPCA/PCA」，正中本專案「隱性飄移」訴求。近年仍活躍（recursive/ensemble/kernel-CVA 變體 2023–2025）。
- **計算成本**：中。需 SVD on Hankel 矩陣；線上投影成本與 PCA 相當；recursive 版可線上更新。
- **建議：augment（高優先候選）**。在「動態 + incipient 飄移偵測」上，CVA 是化工原生、有控制限、確定性的成熟解，比 DPCA 更強，是本專案 re-entry 期隱性飄移偵測最對味的方法之一。風險：Hankel/lag 階數與 state order 需選定，實作較 DPCA 重。
- **代表文獻**：Russell, Chiang, Braatz, "Fault detection in industrial processes using canonical variate analysis and dynamic principal component analysis", *Chemometrics and Intelligent Laboratory Systems*, vol.51, no.1, pp.81–93, 2000. DOI: 10.1016/S0169-7439(00)00058-7 · <https://www.sciencedirect.com/science/article/abs/pii/S0169743900000587>
  - incipient 近作："Incipient fault detection for dynamic processes with canonical variate residual statistics analysis", *Chemometrics and Intelligent Laboratory Systems*, 2024. DOI: 10.1016/j.chemolab.2024.105165 · <https://www.sciencedirect.com/science/article/abs/pii/S0169743924001291>（DOI 待最終核對；以 ScienceDirect 頁面為準）

---

### 1.4 Slow Feature Analysis（SFA）

- **核心改進**：解 ③，並提供 PCA 缺乏的關鍵能力——**區分「正常操作點變動（nominal operating condition change）」vs「真實動態異常（dynamics anomaly）」**。萃取「變化最慢」的潛變數，並監看其變化速度。
- **可導統計量/控制限**：✅ 可。除 T²/SPE 外，另定義**速度型統計量 S²、S_e²**（slow feature 的時間導數能量），控制限可由 χ² / KDE 推。
- **成熟度**：**有產業案例（化工、控制性能監控）**；2015 起在化工 MSPC 社群成熟，連續/批次皆有變體。
- **計算成本**：中低。廣義特徵值問題（generalised eigen），訓練一次；線上投影便宜、確定性。
- **建議：augment（高優先候選，與本專案目標高度契合）**。本專案核心痛點正是「換線/維修後 A 回歸時，要分辨『正常回歸』vs『殘留飄移』」——SFA 的「操作點變動 vs 動態異常」二分**正是這個問題的數學對應**。輸出有控制限、確定性、不需大量資料。風險：slow/fast 切分閾值需定；穩態純連續段速度訊號弱時靈敏度下降。
- **代表文獻**：Shang, Yang, Huang, Lyu, Zhou, Gao, "Concurrent monitoring of operating condition deviations and process dynamics anomalies with slow feature analysis", *AIChE Journal*, vol.61, no.11, pp.3666–3682, 2015. DOI: 10.1002/aic.14888 · <https://aiche.onlinelibrary.wiley.com/doi/10.1002/aic.14888>

---

### 1.5 ICA-based MSPC（Independent Component Analysis）

- **核心改進**：解 ②。用高階統計（非二階）萃取**統計獨立**的成分，不要求高斯，適合非高斯製程。
- **可導統計量/控制限**：✅ 可，導出 **I²、Ie²、SPE** 三統計量；因 IC 非高斯，控制限**須用 KDE**（非 F/χ²）。
- **成熟度**：**有產業案例**；化工 MSPC 經典分支（Lee 2004 起）。
- **計算成本**：中低。FastICA 訓練收斂快；線上投影便宜、確定性。
- **建議：augment（條件性）**。若 TEP 變數明顯非高斯導致 PCA-T² 誤報，ICA 是對 ② 的針對性升級且仍有控制限。但本專案痛點主軸是「線性關係偏移 + 動態」，非高斯非首要矛盾；優先序低於 DPCA/CVA/SFA。風險：IC 個數與排序不唯一；需 KDE 限。
- **代表文獻**：Lee, Yoo, Lee, "Statistical process monitoring with independent component analysis", *Journal of Process Control*, vol.14, no.5, pp.467–485, 2004. DOI: 10.1016/j.jprocont.2003.09.004 · <https://www.sciencedirect.com/science/article/abs/pii/S0959152403000994>

---

### 1.6 Probabilistic / Bayesian PCA（PPCA / BPCA）

- **核心改進**：緩解 ④（機率框架下不直接求協方差逆），並原生支援**缺值/雜訊建模**與多模態（mixture PPCA）。
- **可導統計量/控制限**：✅ 可。導出 likelihood-based 監控指標（如 **M²** 統計量），對線性高斯穩態製程在最大概似意義下最優；亦可退化回 T²/Q。
- **成熟度**：**有產業案例**；mixture/recursive PPCA 用於多模態與線上更新。
- **計算成本**：低～中。EM 訓練；線上評分便宜、確定性。
- **建議：augment（基礎設施型，條件性）**。價值主要在**缺值穩健 + 機率化控制限 + 多模態**，與本專案「campaign 切換造成多模態」相容。但對「隱性多變量飄移早偵測」本身的增益不如 CVA/SFA 直接。建議在資料缺值或多模態確實成為障礙時才引入。風險：仍假設高斯潛變數（對 ① 無幫助）。
- **代表文獻**：Kim, Lee, "Process monitoring based on probabilistic PCA", *Chemometrics and Intelligent Laboratory Systems*, vol.67, no.2, pp.109–123, 2003. DOI: 10.1016/S0169-7439(03)00063-7 · <https://www.sciencedirect.com/science/article/abs/pii/S0169743903000637>
  - 動態 Bayesian 變體："Two layered mixture Bayesian probabilistic PCA for dynamic process monitoring", *Journal of Process Control*, vol.57, pp.67–79, 2017. DOI: 10.1016/j.jprocont.2017.06.004 · <https://www.sciencedirect.com/science/article/abs/pii/S0959152417301221>

---

### 1.7 Autoencoder / Denoising-AE 重構式監控

- **核心改進**：解 ①（深層非線性重構），無需 kernel 選擇。以重構誤差作為殘差監控核心。
- **可導統計量/控制限**：⚠️ 部分。**SPE 直接對應重構誤差**（殘差空間），可保留；T² 可在 bottleneck latent 上構造，但 latent 分佈無解析形式，控制限多須 KDE/經驗分位。
- **成熟度**：**研究為主、少量產業 PoC**；TEP/化工有大量論文但商用案例少。
- **計算成本**：高（訓練需 GPU 與**大量正常資料**）；線上推論便宜且**確定性**（前向傳播無隨機性）。
- **建議：不採用（現階段）/ 最多列為遠期 augment**。違反 Simplicity（Rule 2）：相對 KPCA/CVA 增加大量訓練資料與調參負擔，控制限與可解釋性反而退化。本專案 golden-A 正常資料量可能有限，深層 AE 易過擬合。inference 確定性 ✅ 但訓練成本不划算。
- **代表文獻**：Yu, Zhang, "A review on autoencoder based representation learning for fault detection and diagnosis in industrial processes", *Chemometrics and Intelligent Laboratory Systems*, vol.231, 104711, 2022. DOI: 10.1016/j.chemolab.2022.104711 · <https://www.sciencedirect.com/science/article/pii/S0169743922002222>

---

### 1.8 Variational Autoencoder（VAE）製程監控

- **核心改進**：解 ① + 部分 ②。生成式機率框架，latent 空間經 KL 正則趨近高斯，**便於在 latent 上構造可用解析控制限的統計量**（如 H² 用 χ²）。
- **可導統計量/控制限**：✅（相對其他深度法較好）。可導 negative variational score / H² 等指標，控制限用 χ² 或 KDE。
- **成熟度**：**研究為主**；TEP 上有完整對照研究（static/dynamic/LSTM/GRU-VAE）。
- **計算成本**：高（訓練需 GPU + 大量資料）；**注意：VAE 推論含採樣，須固定為取後驗均值才確定性**，否則違反本專案 runtime 確定性要求。
- **建議：不採用（現階段）**。理由同 AE：對本專案規模過重、需大量資料；且採樣若不固定會引入非確定性。若未來資料充足且非線性確認是主要漏抓源，再評估。
- **代表文獻**：Lee, Kwak, Han, Kim, Yoon, "Process monitoring using variational autoencoder for high-dimensional nonlinear processes", *Engineering Applications of Artificial Intelligence*, vol.83, pp.13–27, 2019. DOI: 10.1016/j.engappai.2019.04.013 · <https://www.sciencedirect.com/science/article/abs/pii/S0952197619300983>
  - 比較研究："Fault Detection and Diagnosis in Industrial Processes with Variational Autoencoder: A Comprehensive Study", *Sensors*, vol.22, no.1, 227, 2022. DOI: 10.3390/s22010227 · <https://www.mdpi.com/1424-8220/22/1/227>

---

### 1.9 Deep SVDD / Deep One-Class

- **核心改進**：解 ①。深層特徵空間中學一個**最小包覆超球**，到球心距離即異常分數，純 one-class（只需正常資料）。
- **可導統計量/控制限**：⚠️ 弱。輸出單一距離分數（類似單一 GSI），**不自然分解出 T²/SPE 雙統計量**；閾值靠正常分數經驗分位，無解析控制限。**可解釋性差**（無 model/residual 分解、貢獻圖較難）。
- **成熟度**：**研究為主**；TEP 有 ensemble DeSVDD 等變體。
- **計算成本**：高（訓練 GPU + 大量正常資料）；線上推論確定性。
- **建議：不採用**。與本專案「需可解釋 + 雙統計量 + 控制限」訴求衝突（輸出退化為單一分數），且訓練重。對「隱性飄移早偵測」無證據優於 CVA/SFA。
- **代表文獻**：Ruff et al., "Deep One-Class Classification", *Proceedings of the 35th ICML, PMLR* 80:4393–4402, 2018. URL: <https://proceedings.mlr.press/v80/ruff18a.html>（會議論文，PMLR 無 DOI）
  - 化工變體："Nonlinear Chemical Process Fault Diagnosis Using Ensemble Deep Support Vector Data Description", *Sensors*, vol.20, no.16, 4599, 2020. DOI: 10.3390/s20164599 · <https://pmc.ncbi.nlm.nih.gov/articles/PMC7472344/>

---

### 1.10 GAN-based monitoring

- **核心改進**：解 ①。以對抗式生成器學正常資料分佈，用判別分數/重構殘差偵測異常（多為 BiGAN/AnoGAN 系）。
- **可導統計量/控制限**：❌ 弱。異常分數非標準 T²/SPE；無解析控制限；可解釋性差。
- **成熟度**：**研究為主**；TEP 有 BiGAN PoC，主賣點是 test-time 較其他 GAN 快。
- **計算成本**：**最高**（GAN 訓練不穩定、需大量資料與調參）；本身有 mode collapse 風險。
- **建議：不採用**。訓練不穩 + 無控制限 + 不可解釋，三項全部踩本專案紅線，CP 值最低。
- **代表文獻**：Yang, Feng, et al., "Generative Adversarial Network Based Anomaly Detection on the Benchmark Tennessee Eastman Process", *2019 ICCA*, IEEE, 2019. DOI: 10.1109/ICCA.2019.8813415 · <https://ieeexplore.ieee.org/document/8813415/>

---

### 1.11 Graph Neural Network（感測器拓樸/關係）

- **核心改進**：解 ① + 顯式建模**感測器間關係結構**（鄰接矩陣可學）。對「多變量關係偏移」這類隱性飄移，理論上能精準定位是哪組變數關係變了（GDN 有 per-sensor 偏差分數，可做根因定位）。
- **可導統計量/控制限**：⚠️ 部分。GDN 用 forecasting 偏差（predicted vs actual）做 graph deviation score，**有 per-sensor 異常分數（近似可解釋）**，但非 T²/SPE，閾值靠經驗分位。
- **成熟度**：**研究為主**（SWaT/WADI 水處理 benchmark 為主；TEP 上有 trainable-adjacency GNN 故障診斷論文）。化工連續製程的產業案例仍少。
- **計算成本**：高（訓練 GPU + 大量資料）；線上推論確定性。
- **建議：不採用（現階段）/ 列為遠期觀察**。概念上最貼「多變量關係偏移」與「根因定位」，但成熟度與資料需求不符 Simplicity；本專案先用 CVA/SFA 達標後，若需感測器級根因定位再評估 GDN。
- **代表文獻**：Deng, Hooi, "Graph Neural Network-Based Anomaly Detection in Multivariate Time Series", *Proceedings of the AAAI Conference on Artificial Intelligence*, vol.35, no.5, pp.4027–4035, 2021. DOI: 10.1609/aaai.v35i5.16523 · <https://ojs.aaai.org/index.php/AAAI/article/view/16523>
  - TEP 應用："Graph Neural Networks with Trainable Adjacency Matrices for Fault Diagnosis on Multivariate Sensor Data", arXiv:2210.11164, 2022. URL: <https://arxiv.org/abs/2210.11164>（DOI: NOT FOUND — arXiv preprint，後續期刊版未查得）

---

### 1.12 Transformer / Attention 多變量時序異常偵測

- **核心改進**：解 ① + ③。self-attention 同時建模**跨變數關聯**與**長程時間依賴**；Anomaly Transformer 用 association discrepancy 作為可區分準則。
- **可導統計量/控制限**：❌ 弱。異常分數來自 attention 統計或預測殘差，非 T²/SPE；無解析控制限；可解釋性中等（attention 可視化但非製程語意）。
- **成熟度**：**研究為主**（SMD/SWaT/MSL 等 IT/水處理 benchmark）；化工連續製程產業案例少。
- **計算成本**：高（訓練 GPU + 大量資料；attention O(n²) 序列長度成本）；推論確定性。
- **建議：不採用（現階段）**。對本專案而言過重、需大量資料、無控制限。Transformer 的長程依賴優勢在本專案的穩態連續段價值有限（CVA/SFA 已覆蓋動態）。
- **代表文獻**：Xu, Wu, Wang, Long, "Anomaly Transformer: Time Series Anomaly Detection with Association Discrepancy", *ICLR 2022 (Spotlight)*. arXiv:2110.02642 · <https://openreview.net/forum?id=LzQQ89U1qm_>（會議論文，DOI: NOT FOUND — OpenReview/arXiv 無 DOI）

---

### 1.13 Normalizing Flows 密度式監控

- **核心改進**：解 ① + ②。可逆變換把複雜分佈映到簡單基底分佈，給出**精確 log-likelihood**，可作密度式異常分數（不必假設高斯）。
- **可導統計量/控制限**：⚠️ 部分。以 negative log-likelihood 為分數，閾值由正常資料分位定；非 T²/SPE，但**密度分數本身有機率語意**，比 GAN/AE 略好。
- **成熟度**：**研究為主**，且現有工業案例多偏**影像/視覺檢測**（surface defect），製程多變量時序的成熟應用少；conditional NF for MTS anomaly 為新興。
- **計算成本**：高（訓練 GPU + 大量資料；flow 層數多時推論成本中高）；推論確定性。
- **建議：不採用（現階段）**。製程時序領域證據薄、資料需求大；密度監控的價值 KDE-based KPCA/ICA 已能以更輕方式提供。
- **代表文獻**：Dinh, Sohl-Dickstein, Bengio, "Density estimation using Real NVP", *ICLR 2017*. arXiv:1605.08803 · <https://arxiv.org/abs/1605.08803>（方法奠基，DOI: NOT FOUND — 會議論文）
  - 時序應用："Conditional normalizing flow for multivariate time series anomaly detection", *ISA Transactions*, 2023. DOI: 10.1016/j.isatra.2023.09.004 · <https://www.sciencedirect.com/science/article/abs/pii/S0019057823004020>（DOI 以 ScienceDirect 頁面為準）

---

## 2. 彙整對照表

| 方法 | 解的痛點 | T²/SPE 控制限 | 成熟度 | 計算成本(線上) | inference 確定性 | 需大量訓練資料 | 建議 |
|---|---|---|---|---|---|---|---|
| **DPCA** | ③ | ✅ 沿用 | 商用/廣用 | 極低 | ✅ | 否 | **augment（高優先）** |
| **CVA** | ③④ | ✅ 雙統計量 | 產業案例 | 中 | ✅ | 否 | **augment（高優先）** |
| **SFA** | ③（+正常變動 vs 異常區分） | ✅ +速度統計量 | 產業案例 | 中低 | ✅ | 否 | **augment（高優先，最契合）** |
| KPCA | ① | ✅（須 KDE 限） | 產業案例 | 中高(N²) | ✅ | 中 | augment（條件性） |
| ICA-MSPC | ② | ✅（須 KDE 限） | 產業案例 | 中低 | ✅ | 中 | augment（條件性） |
| PPCA/BPCA | ④（+缺值/多模態） | ✅ likelihood | 產業案例 | 低中 | ✅ | 中 | augment（基礎設施型） |
| Autoencoder | ① | ⚠️ SPE only | 研究/PoC | 低(推論) | ✅ | **是** | 不採用（現階段） |
| VAE | ①② | ✅ 較佳 | 研究 | 高(訓練) | ⚠️ 須固定採樣 | **是** | 不採用（現階段） |
| Deep SVDD | ① | ❌ 單分數 | 研究 | 高(訓練) | ✅ | **是** | 不採用 |
| GAN | ① | ❌ | 研究 | 最高 | ⚠️ | **是** | 不採用 |
| GNN(GDN) | ①+關係結構 | ⚠️ per-sensor | 研究 | 高(訓練) | ✅ | **是** | 不採用（遠期觀察） |
| Transformer | ①③ | ❌ | 研究 | 高 | ✅ | **是** | 不採用（現階段） |
| Normalizing Flows | ①② | ⚠️ 密度分數 | 研究(偏視覺) | 高 | ✅ | **是** | 不採用（現階段） |

---

## 3. 結論

### 3.1 最值得納入的 2–3 個（連續化工 + 隱性多變量飄移 + 可解釋 + 控制限）

按「對本專案目標的契合度 × 成熟度 × Simplicity」排序：

1. **SFA（Slow Feature Analysis）— 最契合**。它原生回答本專案的核心問題：「換線/維修後 A 回歸時，是『正常操作點變動』還是『殘留動態飄移』」。提供 T²/SPE + 速度型統計量 S²/S_e²，有控制限、確定性、不需大量資料。直接強化成功判準第 3 條（區分乾淨回歸 vs 殘留飄移）。
2. **CVA（Canonical Variate Analysis）**。化工原生、文獻反覆驗證對 **incipient（緩起/隱性）故障**早於 PCA/DPCA，正中「隱性飄移早偵測」（成功判準第 2 條）。輸出雙統計量 + 控制限，確定性。
3. **DPCA（Dynamic PCA）— 最低成本起手**。對現有 PCA 幾乎零增量即補上動態（③），可作為 L2 的即時升級基線；建議先上 DPCA 當 baseline，再用 SFA/CVA 比較增益。

> 三者皆為 **deterministic-at-inference、有解析或 KDE 控制限、可導 T²/SPE 類統計量、不需深度學習級資料量**，完全相容本專案 Rule 2/5/6/11。

### 3.2 雖新但對本專案過重/不成熟（違反 Simplicity）

- **VAE / Autoencoder / Deep SVDD / GAN / GNN / Transformer / Normalizing Flows** 全部**需大量訓練資料 + GPU + 調參**，多數**無解析控制限、可解釋性弱**（GAN/Transformer/Deep SVDD 尤甚），且化工連續製程的**產業成熟證據薄**（多在水處理/IT/視覺 benchmark）。本專案 golden-A 正常資料量有限、要求可解釋與控制限，這些方法 CP 值低、踩 Rule 2/7 紅線。
- 其中 **GNN（GDN）** 概念上最貼「多變量關係偏移 + 感測器級根因定位」，列為**遠期觀察**：待 CVA/SFA 達標、且確實需要感測器級根因定位時再評估。

### 3.3 確定性合規標記（Rule 5：runtime 不呼叫 LLM）

| 類別 | 方法 | 說明 |
|---|---|---|
| **Deterministic-at-inference（推論端純數學，✅ 直接合規）** | DPCA, CVA, SFA, KPCA, ICA-MSPC, PPCA/BPCA, Autoencoder, Deep SVDD, GNN, Transformer | 推論皆為矩陣投影/前向傳播，無隨機性、無 LLM。其中**前 6 個（DPCA/CVA/SFA/KPCA/ICA/PPCA）額外不需大量訓練資料**，是本專案首選區。 |
| **需固定隨機性才合規** | VAE, GAN, Normalizing Flows | VAE/GAN 推論含採樣，須固定為「取後驗均值/固定 latent」才確定性；NF 本身確定性但常與生成式採樣混用，需確認推論路徑。 |
| **需大量訓練資料（不利本專案）** | Autoencoder, VAE, Deep SVDD, GAN, GNN, Transformer, Normalizing Flows | 深度法皆需大量正常資料；本專案 golden-A 資料量受限，過擬合風險高。 |

> 全部 13 個方法的**偵測決策本身都是確定性數學**，無一需要在 runtime 呼叫 LLM；差異在「採樣是否需固定」與「資料量需求」兩軸。本專案最終採用區（SFA/CVA/DPCA）在兩軸上皆乾淨。

---

## 4. 待核對項（誠實標記，未捏造）

- §1.3 CVA incipient 近作（2024）與 §1.13 NF 時序應用（2023）的 DOI 以 ScienceDirect 頁面顯示為準，未逐位元核對 CrossRef，標為「以頁面為準」。
- §1.11 TEP-GNN（arXiv:2210.11164）與 §1.12 Anomaly Transformer、§1.13 Real NVP 為會議/preprint，**無 DOI（標 NOT FOUND）**，僅附 arXiv/OpenReview URL。
- 其餘已驗證 DOI（KPCA Lee 2004、DPCA Ku 1995、CVA Russell 2000、SFA Shang 2015、ICA Lee 2004、PPCA Kim&Lee 2003、Deep SVDD Ruff 2018、GDN Deng&Hooi 2021、GAN Yang 2019）均經 WebSearch 交叉確認作者/卷期/年份。

### 下一步

- 建議先在 TEP 上把 **DPCA** 接成 L2 baseline（最低成本補 ③），再加 **SFA**、**CVA** 做 A/B 比較，以成功判準第 2、3 條為驗證目標。
- 把本檔三個首選方法的 DOI 補登進 `docs/literature_crossref.md` 維度 5（PCA→MSPC）的延伸列，維持單一真相。
