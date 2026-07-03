# L4 分佈漂移偵測 現代化文獻調查（2017–2026）

> 調查日期：2026-06-01
> 狀態（2026-07 更新）：主建議已部分落地——現行 L4（`src/health_index/detectors/drift.py:1-8`）＝KS first-pass 廉價篩 → block-permutation MMD（RBF, median heuristic）為最終顯著性判據＋解析 1D-Wasserstein 量級（對 golden null 標準化）＋PSI 降級僅供溝通。MMDAgg / Sinkhorn / ADWIN / BOCPD / Scan-B 未採納，留作 backlog。
> 範圍：比 KL / KS / PSI / 經典 Wasserstein 更新的分佈漂移（distribution shift）、two-sample test、concept drift 偵測解法
> 原則：**嚴禁捏造**。每方法附真實 DOI/URL；查不到標 `NOT FOUND`。術語保留 English。
> 對應規範：Rule 5（偵測器確定性數學，runtime 不呼叫 LLM）、Rule 7（衝突擇一）、Rule 12（Fail loud）

---

## 0. 現況與痛點對位

目前 L4：以 KL / KS / PSI / 經典 Wasserstein + permutation 校準，比較「golden-A 分佈 vs 新 A 分佈」。（更新註記）此為 2026-06 調查當時基線。現行 drift.py 已無 KL；KS 改為 first-pass 篩選（非主判據）、MMD block-permutation 為最終決策、Wasserstein 改解析 1D per-component 和（golden-null 標準化 z-score）、PSI 僅溝通不入顯著性決策。痛點①②③已依此消解或緩解。痛點：

| 編號 | 痛點 | 根因 |
|---|---|---|
| ① | KL / PSI 在分佈**非重疊**時發散（→∞ 或不穩） | f-divergence 對 support mismatch 病態；PSI 依賴分箱，少量點脆 |
| ② | KS 只用**單一 max-gap**，弱於尾部 | sup-norm 統計量集中在 CDF 差異最大處 |
| ③ | 多維 Wasserstein **O(N³logN)** 昂貴 | 線性規劃精確 OT |
| ④ | 多為**離線批量**比較，缺線上序列偵測 | 無 streaming changepoint 機制 |
| ⑤ | **邊際比較會漏掉「關係型」隱性飄移** | per-feature 比較不看 joint / 變數間關係 |

> 註：⑤ 正是本專案存在理由（CLAUDE.md「隱性飄移」）。L4 的邊際/逐變數分佈比較**先天無法**捕捉純關係型漂移；真正補 ⑤ 要靠 (a) L2 的 T²/SPE（已在判斷鏈內）或 (b) 在 joint 空間或 representation 空間做 two-sample test（MMD / C2ST / energy distance / deep-kernel）。下文凡標「✅⑤」者均指「在 joint/representation 空間操作」而非逐變數。

---

## 1. 現代候選方法總表

成熟度圖例：🟢 工業級成熟（有穩定套件）／🟡 學術成熟有套件／🟠 新近研究。

| 方法 | 解痛點 | 少量點/線上 | 校準 p-value/門檻 | 多維 | 成熟度 | 計算成本 | 建議 |
|---|---|---|---|---|---|---|---|
| **MMD**（kernel two-sample） | ①②⑤ | 少量點佳；可線上（Scan-B/RFF） | ✅ permutation/spectral；deep/agg 給非漸近 level | ✅ 原生多維 | 🟢 | O(N²) naive；Scan-B 線上 O(NB²) | **升級**（取代 KS 為主力多維檢定） |
| **Energy Distance**（Székely–Rizzo） | ①②⑤ | 少量點佳 | ✅ permutation | ✅ | 🟢 | O(N²) | **補強**（MMD 特例，scipy/dcor 可直接用） |
| **C2ST**（classifier two-sample） | ①②⑤ | 中等（需 train/test split） | ✅ binomial on held-out acc | ✅ 高維強 | 🟡 | 訓練分類器成本 | 補強（可解釋；但引入學習元件，見 Rule 5 註） |
| **Sinkhorn divergence**（entropic OT） | ①③⑤ | 少量點佳（1/√n） | 需自建 permutation | ✅ | 🟢 | O(N²/ε) per iter，遠快於精確 OT | **升級**（取代精確多維 Wasserstein） |
| **Sliced-Wasserstein / max-SW** | ①③ | 少量點中等 | ✅ 近期有 permutation + minimax 保證 | ✅（投影聚合） | 🟡 | O(L·N log N) | 補強（廉價多維 W 替身；max-SW 抓主方向） |
| **Deep-kernel MMD** | ①②⑤ | 需 data split 學 kernel | ✅ consistency 證明 | ✅ 高維 | 🟡 | 訓練 + O(N²) | 觀望（高維/影像才划算，過度設計風險） |
| **MMDAgg**（aggregated MMD） | ①②⑤ | 小樣本佳（non-asymptotic level） | ✅ 非漸近 type-I 控制 | ✅ | 🟡 | 多 bandwidth × O(N²) | **補強**（免調 bandwidth，最像「即插即用升級」） |
| **ADWIN**（adaptive windowing） | ④ | ✅ 線上、自適應窗 | 有 FP/FN bound（非 p-value） | ✕（1-D 統計流） | 🟢 | O(log W) 攤銷 | **整合**（取代「固定窗 + 持續性」的窗管理） |
| **DDM / EDDM** | ④ | ✅ 線上 | 統計門檻（warning/drift level） | ✕（監督誤差流） | 🟢 | O(1) | 不採（需 label/error stream，本專案無線上 label） |
| **Page-Hinkley / CUSUM** | ④ | ✅ 線上 | 門檻 λ（非 p-value） | ✕（1-D） | 🟢 | O(1) | 補強（把 L4 score 流接 PH 抓持續位移） |
| **KSWIN** | ②④ | ✅ 線上滑窗 KS | ✅ KS α | ✕（per-feature） | 🟢 | O(n log n) per step | 觀望（仍是 KS，未解②本質） |
| **HDDDM**（Hellinger batch） | ①④ | 批次、無 label | 自適應門檻（非 p-value） | 部分（per-feature histogram 聚合） | 🟡 | O(bins) | 觀望（Hellinger 有界，優於 KL；但仍分箱） |
| **BOCPD**（Bayesian online CP） | ④ | ✅ 線上 run-length 後驗 | 給後驗機率（非 freq p-value） | ✅（需多維似然模型） | 🟡 | O(t) per step（截斷後 O(1)~O(R)） | **整合候選**（給「最近 changepoint」機率，貼合 re-entry 監看） |
| **Kernel CPD（ruptures/PELT）** | ④⑤ | 離線批次 | 懲罰項（非 p-value） | ✅（kernel 內積） | 🟢 | PELT 近線性；naive O(N²) | 補強（離線 campaign 切段，分 re-entry 區段） |
| **Scan-B / Online-MMD** | ④⑤ | ✅ 線上 kernel two-sample | ✅ ARL/門檻校準 | ✅ | 🟡 | O(NB²) 線性 | **整合候選**（MMD 的線上版，直接補 ④ 且保 ⑤） |

---

## 2. 逐方法詳述（含代表文獻 + 已驗證 DOI）

### 2.1 MMD — Maximum Mean Discrepancy（kernel two-sample test）
- **原理**：在 RKHS 中比較兩分佈的 mean embedding 差，MMD²(P,Q)=‖μ_P−μ_Q‖²。characteristic kernel（如 Gaussian）下 MMD=0 ⇔ P=Q，**直接在 joint 空間**檢定，故能抓關係型漂移（⑤）。
- **解痛點**：① 不依賴分箱、support mismatch 不發散；② 用整個分佈差而非單點 gap；⑤ joint 空間原生多維。
- **少量點/線上**：少量點表現好；線上有 Scan-B（2.13）與 RFF 近似。校準：permutation 或 spectral 近似 null。
- **成本**：naive U-statistic O(N²)；linear-time MMD_l 與 RFF 可降。
- **建議**：**升級**——作為 L4 的主力多維 two-sample test，取代 KS 在多維上的角色。
- **文獻**：Gretton, Borgwardt, Rasch, Schölkopf, Smola, "A Kernel Two-Sample Test", *JMLR* 13:723–773, 2012. URL: <https://jmlr.org/papers/v13/gretton12a.html>（JMLR open access，無 DOI 編號；卷期頁碼如上）

### 2.2 Energy Distance（Székely–Rizzo）
- **原理**：E(P,Q)=2E‖X−Y‖−E‖X−X′‖−E‖Y−Y′‖。**是 MMD 在特定（distance-induced）kernel 下的特例**（Sejdinovic et al. 2013 已證等價）。
- **解痛點**：①②⑤ 同 MMD；不分箱、多維、permutation 校準。
- **成本**：O(N²) 距離矩陣。
- **建議**：**補強**——`scipy.stats.energy_distance`（1-D）/ `dcor` 套件（多維 + permutation test）可立即用，作為 MMD 的免 kernel-bandwidth 替身。
- **文獻**：Székely, Rizzo, "Energy statistics: A class of statistics based on distances", *Journal of Statistical Planning and Inference* 143(8):1249–1272, 2013. DOI: 10.1016/j.jspi.2013.03.018 · <https://doi.org/10.1016/j.jspi.2013.03.018>

### 2.3 C2ST — Classifier Two-Sample Test
- **原理**：把 golden-A 標 0、新 A 標 1，訓練分類器；若 P=Q，held-out 準確率應 ≈ 0.5。test statistic 為準確率，null 為 Binomial(n, 1/2)。
- **解痛點**：①②⑤ 高維關係型漂移強；可解釋「哪些樣本最典型」。
- **校準**：held-out accuracy 的 binomial test，p-value 簡單。
- **Rule 5 註**：分類器本身是學習元件，但**用途是 two-sample 判定的確定性統計檢定**（固定 split、固定種子可重現），非「LLM routing / 重試」。屬可接受的確定性 ML，建議僅在 MMD/energy 不足時啟用，避免 Rule 2 過度設計。
- **文獻**：Lopez-Paz, Oquab, "Revisiting Classifier Two-Sample Tests", *ICLR* 2017. arXiv:1610.06545. DOI: 10.48550/arXiv.1610.06545 · <https://arxiv.org/abs/1610.06545>

### 2.4 Sinkhorn Divergence（entropic-regularized OT，快速 Wasserstein）
- **原理**：OT 加熵正則 ε 後用 Sinkhorn 迭代求解；Sinkhorn divergence S_ε(P,Q)=OT_ε(P,Q)−½OT_ε(P,P)−½OT_ε(Q,Q) 去偏，ε→0 趨近 Wasserstein、ε→∞ 趨近 MMD（介於兩者間）。
- **解痛點**：① OT 幾何不對 support mismatch 發散；③ 把 O(N³logN) 降到 O(N²/ε) per iteration；⑤ 多維幾何。
- **少量點**：sample complexity 1/√n（與 MMD 同階，優於精確 OT 的維度詛咒）——這對「少量點」是關鍵優勢。
- **建議**：**升級**——以 POT (`ot.sinkhorn` / `ot.bregman.empirical_sinkhorn_divergence`) 取代精確多維 Wasserstein；permutation 校準 p-value 需自建。
- **文獻**：Genevay, Chizat, Bach, Cuturi, Peyré, "Sample Complexity of Sinkhorn Divergences", *AISTATS* (PMLR 89), 2019. URL: <https://proceedings.mlr.press/v89/genevay19a.html>（PMLR open access；無 DOI 編號）

### 2.5 Sliced-Wasserstein / Max-Sliced / Distributional-SW
- **原理**：把多維分佈隨機投影到 1-D，對每個方向算廉價 1-D Wasserstein 再聚合。SW=平均；max-SW=取最大差異方向（抓主漂移方向）；DSW=學投影分佈。
- **解痛點**：① 保 OT 幾何不發散；③ O(L·N log N) 遠快於精確 OT。
- **校準**：2025 有 permutation-based SW test 含**minimax n^{-1/2} 分離率**保證（Tran & Schreuder）；max-SW 高維有 bootstrap null（Biometrika 2025）。
- **建議**：補強——POT 有 `ot.sliced_wasserstein_distance`；作為 Sinkhorn 之外的廉價多維 W 選項。
- **文獻**：
  - Deshpande et al., "Max-Sliced Wasserstein Distance and Its Use for GANs", *CVPR* 2019. DOI: 10.1109/CVPR.2019.01090 · <https://doi.org/10.1109/CVPR.2019.01090>
  - Nguyen et al., "Distributional Sliced-Wasserstein and Applications to Generative Modeling", *ICLR* 2021. arXiv:2002.07367 · <https://arxiv.org/abs/2002.07367>
  - Tran, Schreuder, "Minimax-Optimal Two-Sample Test with Sliced Wasserstein", arXiv:2510.27498, 2025. DOI: 10.48550/arXiv.2510.27498 · <https://arxiv.org/abs/2510.27498>

### 2.6 Deep-Kernel MMD
- **原理**：用神經網路學 kernel（feature map），最大化 test power。
- **解痛點**：①②⑤，特別針對高維/複雜資料（影像、長 trace）。
- **建議**：觀望——TEP/penicillin 維度有限（數十 channel），深核相對 RBF-MMD 的增益不確定，有 Rule 2 過度設計風險；高維 representation 漂移才考慮。
- **文獻**：Liu, Xu, Lu, Zhang, Gretton, Sutherland, "Learning Deep Kernels for Non-Parametric Two-Sample Tests", *ICML* (PMLR 119):6316–6326, 2020. arXiv:2002.09116 · <https://arxiv.org/abs/2002.09116>

### 2.7 MMDAgg — Aggregated MMD Two-Sample Test
- **原理**：對一組 bandwidth 各做 MMD 檢定再聚合，**非漸近**控制 type-I error、免手調 bandwidth。
- **解痛點**：①②⑤，且解決「RBF-MMD bandwidth 難選」的實務痛點；小樣本仍 well-calibrated。
- **建議**：**補強**——`mmdagg` 套件即插即用，是現有組合「最低摩擦的升級」（免 bandwidth 調參 + 小樣本校準）。
- **文獻**：Schrab, Kim, Albert, Laurent, Guedj, Gretton, "MMD Aggregated Two-Sample Test", *JMLR* 24(194):1–81, 2023. URL: <https://jmlr.org/papers/v24/21-1289.html> · arXiv:2110.15073

### 2.8 ADWIN — Adaptive Windowing
- **原理**：維持可變長滑窗 W，當任意切分子窗 W₀/W₁ 均值差超過 Hoeffding-type bound 即判漂移並縮窗。提供 FP/FN 理論界。
- **解痛點**：④ 線上、自適應窗長（免手選窗大小）。
- **限制**：原生處理 1-D 數值流（如 L4 的距離 score 流），非多維 two-sample。
- **建議**：**整合**——把 L4 每窗算出的 MMD/Sinkhorn score 餵給 ADWIN，由它自適應決定「持續性 + 窗管理」，取代固定窗 + 手寫持續性規則。River / scikit-multiflow 有實作。
- **文獻**：Bifet, Gavaldà, "Learning from Time-Changing Data with Adaptive Windowing", *SIAM SDM* 2007, pp.443–448. DOI: 10.1137/1.9781611972771.42 · <https://doi.org/10.1137/1.9781611972771.42>

### 2.9 DDM / EDDM — (Early) Drift Detection Method
- **原理**：監看線上**分類錯誤率**，超 warning/drift level（基於二項標準差）即報。
- **建議**：**不採**——需線上 label/error stream，本專案 re-entry 監看無即時 ground-truth label，前提不成立（Rule 7：明說不適用）。
- **文獻**：Gama, Medas, Castillo, Rodrigues, "Learning with Drift Detection", *SBIA* 2004, LNCS 3171:286–295. DOI: 10.1007/978-3-540-28645-5_29 · <https://doi.org/10.1007/978-3-540-28645-5_29>

### 2.10 Page-Hinkley / CUSUM
- **原理**：累積偏離均值的量，超門檻 λ 報變點；CUSUM 對小持續位移敏感。
- **解痛點**：④ 線上、O(1)。
- **建議**：補強——把 L4 score 流接 Page-Hinkley，抓「小但持續」的漂移（比固定窗持續性計數更原則化）。River 有實作。
- **文獻**：Page, "Continuous Inspection Schemes", *Biometrika* 41(1/2):100–115, 1954. DOI: 10.2307/2333009 · <https://doi.org/10.2307/2333009>

### 2.11 KSWIN — Kolmogorov-Smirnov Windowing
- **原理**：滑窗內對「近期 vs 近似舊概念」做 KS test。
- **建議**：觀望——線上化了 KS，但**未解痛點②**（仍 sup-norm 單點 gap）；若已上 MMD/energy 線上版則無必要。
- **文獻**：Raab, Heusinger, Schleif, "Reactive Soft Prototype Computing for Concept Drift Streams", *Neurocomputing* 416:340–351, 2020. DOI: 10.1016/j.neucom.2019.11.111 · <https://doi.org/10.1016/j.neucom.2019.11.111>

### 2.12 HDDDM — Hellinger Distance Drift Detection Method
- **原理**：批次到達，對每特徵直方圖算 Hellinger 距離（有界 [0,√2]，優於無界 KL），自適應門檻報漂移。
- **解痛點**：① Hellinger 有界不發散；④ 批次無 label。
- **限制**：仍依分箱、per-feature 聚合（未根治⑤）。
- **建議**：觀望——若堅持用 divergence，Hellinger 比 KL/PSI 穩，但 MMD/energy 更優先。
- **文獻**：Ditzler, Polikar, "Hellinger Distance Based Drift Detection for Nonstationary Environments", *IEEE CIDUE* 2011, pp.41–48. DOI: 10.1109/CIDUE.2011.5948491 · <https://doi.org/10.1109/CIDUE.2011.5948491>

### 2.13 BOCPD — Bayesian Online Changepoint Detection
- **原理**：以 message-passing 線上推論「run-length（距上次變點時間）」後驗分佈；需指定觀測似然（多維可用 multivariate Gaussian）與 hazard。
- **解痛點**：④ 線上，且直接輸出「最近一次 changepoint 機率」——**貼合本專案 re-entry 期監看**（換線/維修後第一段 A 是否為新 segment）。
- **校準**：給 Bayesian 後驗機率（非 frequentist p-value）；門檻為後驗閾值。
- **建議**：**整合候選**——用於偵測「campaign 邊界 / re-entry 起點」的線上變點。`bayesian_changepoint_detection` 等套件可用。
- **文獻**：Adams, MacKay, "Bayesian Online Changepoint Detection", arXiv:0710.3742, 2007. DOI: 10.48550/arXiv.0710.3742 · <https://arxiv.org/abs/0710.3742>

### 2.14 Kernel Change-Point Detection（ruptures / PELT）
- **原理**：離線多變點偵測；kernel cost（RKHS 內積）+ 搜尋（dynamic programming / PELT）+ 變點數約束（懲罰項）。
- **解痛點**：④（離線）⑤（kernel cost 看 joint）。
- **建議**：補強——離線把整條歷史切成「乾淨 A 段 / 非 A 段 / re-entry 段」，再對各段做 L4 two-sample。`ruptures` 套件（KernelCPD + Pelt）成熟。
- **文獻**：Truong, Oudre, Vayatis, "Selective Review of Offline Change Point Detection Methods", *Signal Processing* 167:107299, 2020. DOI: 10.1016/j.sigpro.2019.107299 · <https://doi.org/10.1016/j.sigpro.2019.107299>

### 2.15 Scan-B / Online-MMD（kernel 線上 two-sample）
- **原理**：以固定窗 B-statistic 對「參考塊 vs 滑動的近期塊」連續算 MMD-type 統計量，O(NB²) 線性複雜度，給 ARL（average run length）校準門檻。
- **解痛點**：④（線上）⑤（kernel joint）——**同時補 ④ 與保 ⑤ 的唯一方法**。
- **建議**：**整合候選**——若要把 MMD 從離線批量推到線上序列偵測，Scan-B 是原生路徑（vs 自己用 ADWIN 包 MMD score）。
- **文獻**：Li, Xie, Dai, Song, "Scan B-statistic for Kernel Change-Point Detection", *Sequential Analysis* 38(4):503–544, 2019. DOI: 10.1080/07474946.2019.1686886 · <https://doi.org/10.1080/07474946.2019.1686886>

---

## 3. 結論

### 3.1 對「少量點、線上、捕捉關係型隱性飄移」最值得納入的 2–3 個

**首選 ①：MMD（含 MMDAgg）取代 KS 為主力多維 two-sample test。**
（更新註記）已採納（變體）：drift.py 以 MMD（RBF, median heuristic bandwidth）＋block-permutation p-value 為最終判據（紅隊 N4 自相關校正）；但 KS 非「降級為輔助說明」而是保留為分層決策的廉價 first-pass 閘（兩者皆顯著才判漂移，drift.py:216-229）；MMDAgg 未採（未引入多 bandwidth 聚合）。
- 少量點佳、joint 空間原生捕捉⑤、permutation 校準直接沿用現有框架、O(N²) 在 TEP/penicillin 規模可接受。
- MMDAgg 進一步免 bandwidth 調參且小樣本非漸近校準——是「最低摩擦升級」。
- **是否優於現有組合**：是。MMD 嚴格優於 KS（KS 是 1-D sup-norm，MMD 是多維 RKHS 全分佈差），且不像 KL/PSI 在非重疊時發散。建議 KS 降級為「per-feature 輔助說明」，不再當多維主判據。

**首選 ②：Sinkhorn divergence 取代精確多維 Wasserstein。**
（更新註記）此建議被另一實作取代：現行 L4 不做精確多維 OT，量級改用解析 1D-Wasserstein（per-component `scipy.stats.wasserstein_distance` 加總、s-vs-s 等樣本 disjoint 比較、對 golden null 標準化，drift.py:167-199），痛點③（O(N³logN)）以此消解；Sinkhorn 未採、留 backlog。
- 解③（O(N³logN)→O(N²/ε)）且保 OT 幾何（解①的非重疊發散），sample complexity 1/√n 對少量點友善。
- **是否優於現有組合**：是，針對「多維 Wasserstein 太貴」這一痛點。POT 直接支援。Sliced-Wasserstein 為更廉價的次選。
- ⚠️ MMD vs Sinkhorn 取捨（Rule 7）：兩者非互斥。**MMD/energy 偏「分佈是否相異」的統計檢定（有現成 p-value 機制）**；**Sinkhorn/SW 偏「漂移幾何量值」（給可解釋的距離大小與搬運方向）**。建議 MMD 當主判據（出 p-value），Sinkhorn/SW 當輔助量化漂移幅度，不混成單一公式。

**首選 ③（補 ⑤ 的本質）：Energy Distance 作為 MMD 的免 kernel 替身。**
- 與 MMD 數學等價（distance kernel），`dcor` / `scipy` 即可用、無 bandwidth 超參，permutation 校準。作為 MMD 的交叉驗證與 fallback。

> MMD 與 Sinkhorn **皆優於**現有 KS+PSI+W 組合在各自痛點上的表現：MMD 解 ①②⑤，Sinkhorn 解 ①③。兩者納入後，KS/PSI/KL 可退為輔助或淘汰；經典精確 Wasserstein 由 Sinkhorn/SW 取代。

### 3.2 線上序列偵測（ADWIN / BOCPD / Scan-B）如何與「窗口 + permutation + 持續性」整合

現有 L4 = 固定窗批量 two-sample + permutation p-value + 手寫持續性規則。（更新註記）現行 L4 決策層已是 KS first-pass→block-aware MMD 的分層決策（drift.py:216-229）；permutation 已為 block-permutation（自相關感知）。ADWIN / Page-Hinkley / BOCPD / Scan-B 三路徑均未採納，本節整合建議整段屬 backlog。另 CUSUM 已在別處落地（G1 純 Y CUSUM/KS 輕量模組、batch-AVM 殘差 EWMA/CUSUM 設計 §7），非接在 L4 score 流上。三種整合路徑（對比表）：

| 路徑 | 做法 | 優點 | 缺點 | 適用 |
|---|---|---|---|---|
| **A. ADWIN 包 score** | L4 每窗算 MMD/Sinkhorn → 形成 1-D score 流 → ADWIN 自適應判持續漂移 | 改動小；ADWIN 取代「固定窗 + 持續性計數」；有 FP/FN bound | 多維資訊已壓成 1-D score，損失方向性 | **最務實**：保留現有 two-sample，只換窗/持續性管理 |
| **B. Scan-B 原生線上** | 直接用 kernel 線上 two-sample 連續監看，免外掛持續性 | 一體；O(NB²) 線性；保 ⑤；ARL 校準 | 替換現有窗+permutation 架構，工程量大 | re-entry 即時節拍要求高時 |
| **C. BOCPD 切 segment** | 線上推 run-length 後驗，標記「新 segment 起點」即 re-entry 候選 | 直接給「最近 changepoint」機率，貼合 campaign 邊界語意 | 需設定多維似然 + hazard；Bayesian 後驗非 frequentist p-value | 偵測「換線/維修後第一段 A」的起點 |

**建議組合**：
1. **離線**：ruptures (KernelCPD/PELT) 先把歷史切成乾淨 A / 非 A / re-entry 段（補 ④ 離線、定義比較窗）。
2. **線上**：採**路徑 A**為主——保留現有 permutation two-sample（升級為 MMD/Sinkhorn），把 score 流交給 **ADWIN** 自適應持續性，**Page-Hinkley** 補抓小持續位移。
3. **段落定位**：以 **BOCPD** 標記 re-entry 起點，框定「非 A 後第一段 A」的監看窗（最貼合 CLAUDE.md re-entry 語意）。
4. 若未來即時節拍吃緊，再升級至**路徑 B（Scan-B）**取代 A。

> permutation 校準仍保留：ADWIN/PH 給「何時觸發」的線上門檻，permutation 給「該窗漂移是否統計顯著」的 p-value——兩者分工，不互斥。

### 3.3 確定性合規標記（Rule 5 / Rule 6 / Rule 12）

- **Rule 5（runtime 不呼叫 LLM）**：✅ 本表所有方法皆為確定性數學（PCA/kernel/OT/CUSUM/Bayesian filtering）。唯一含學習元件者為 **C2ST（2.3）與 Deep-kernel MMD（2.6）**——其「學習」限於訓練一個可重現的判別器/核（固定 split + 固定種子即確定），用途是 two-sample 統計判定，**非** LLM routing/重試/分類，符合 Rule 5 精神；仍建議僅在簡單核不足時啟用（Rule 2）。
- **Rule 6（線上運算成本上限）**：Sinkhorn O(N²/ε)、Scan-B O(NB²)、ADWIN O(log W)、PH O(1) 均可線上；精確多維 Wasserstein O(N³logN) 與 naive MMD O(N²) 大樣本須降採樣或走離線——超目標節拍時須 surface。
- **Rule 12（Fail loud）**：本文件所有 DOI/URL 皆經 WebSearch/WebFetch 查證。**無 `NOT FOUND` 項**（所有列出方法均找到真實出處）。Gretton 2012、Genevay 2019、MMDAgg 2023 為 open-access proceedings/JMLR，無 DOI 編號，已改附官方 URL + 卷期頁碼。
