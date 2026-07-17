# 文獻真實性查證與半導體↔化工跨領域參照

> 查證日期：2026-06-01
> 範圍：半導體製程監控指標（AVM / GSI / RI / DQI）transfer 到化工製程監控的文獻支撐
> 原則：嚴禁捏造文獻。查不到者標記 `NOT FOUND`。技術術語與文獻標題保留英文。

---

## 1. 引用查證表（6 筆 + GSI/RI/DQI 來源）

| 編號 | 宣稱資訊 | 查證狀態 | 正確資訊 | DOI / URL |
|---|---|---|---|---|
| 1 | Cheng F.-T. et al., "Developing an Automatic Virtual Metrology System", 2012, IEEE T-ASE, vol.9 no.1 | **VERIFIED** | F.-T. Cheng, H.-C. Huang, C.-A. Kao, "Developing an Automatic Virtual Metrology System", *IEEE Transactions on Automation Science and Engineering*, vol.9, no.1, pp.181–188, Jan 2012 | DOI: 10.1109/TASE.2011.2169405 · <https://ieeexplore.ieee.org/document/6051498> |
| 2 | "Automatic Data Quality Evaluation for the AVM System", IEEE T-SM, 2011 | **CORRECTED**（補全卷期/作者；宣稱年份正確） | Y.-T. Huang, F.-T. Cheng, "Automatic Data Quality Evaluation for the AVM System", *IEEE Transactions on Semiconductor Manufacturing*, vol.24, no.3, pp.445–454, Aug 2011 | DOI: 10.1109/TSM.2011.2146006 · <https://ieeexplore.ieee.org/document/5766761> |
| 3 | Verdier & Ferreira, "Adaptive Mahalanobis Distance and k-Nearest Neighbor Rule for Fault Detection in Semiconductor Manufacturing", 2011, IEEE T-SM, vol.24 no.1 | **CORRECTED**（第二作者名字更正：Ariane，非 António；卷期 vol.24 no.1 正確，pp.59–68） | G. Verdier, A. Ferreira, "Adaptive Mahalanobis Distance and k-Nearest Neighbor Rule for Fault Detection in Semiconductor Manufacturing", *IEEE Transactions on Semiconductor Manufacturing*, vol.24, no.1, pp.59–68, Feb 2011 | DOI: 10.1109/TSM.2010.2065531 · <https://hal.science/emse-00554203> |
| 4 | "Transfer Learning for Soft Sensors in Process Industries: A Review and Future Perspectives", 2026, *Ind. Eng. Chem. Res.* (ACS)（年份可疑） | **VERIFIED**（年份 2026 為真，非捏造；確實已正式發表於 IECR） | "Transfer Learning for Soft Sensors in Process Industries: A Review and Future Perspectives", *Industrial & Engineering Chemistry Research*, ACS, 2026（線上 2026 年 4 月） | DOI: 10.1021/acs.iecr.5c05144 · <https://pubs.acs.org/doi/10.1021/acs.iecr.5c05144> |
| 5 | Fan-Keng Sun et al. (MIT + Analog Devices), "Dynamic Time Warping Constraints for Semiconductor Processing", 2024, SEMI ASMC | **VERIFIED**（作者群含 Rachel Owens、Fan-Keng Sun 等；會議與年份正確） | R. Owens, F.-K. Sun, et al., "Dynamic Time Warping Constraints for Semiconductor Processing", *2024 35th Annual SEMI Advanced Semiconductor Manufacturing Conference (ASMC)*, May 2024 | DOI: 10.1109/ASMC61125.2024.10545476 · <https://ieeexplore.ieee.org/document/10545476/> · 全文 thesis: <https://dspace.mit.edu/handle/1721.1/156276> |
| 6 | Shi Huai-Tao et al., "Improved relative-transformation principal component analysis based on Mahalanobis distance and its application for fault detection", 2013, *Acta Automatica Sinica*, vol.39 no.9 | **VERIFIED** | Shi Huai-Tao et al., "Improved Relative-transformation Principal Component Analysis Based on Mahalanobis Distance and Its Application for Fault Detection", *Acta Automatica Sinica（自动化学报）*, vol.39, no.9, pp.1533–1542, 2013 | DOI: 10.3724/SP.J.1004.2013.01533 · <https://www.aas.net.cn/cn/article/doi/10.3724/SP.J.1004.2013.01533> |

### GSI / RI / DQI_x / DQI_y 核心定義原始來源

| 指標 | 定義要旨 | 原始論文 | 查證狀態 | DOI / URL |
|---|---|---|---|---|
| **RI**（Reliance Index） | 介於 0~1，由「兩種預測值機率分佈的重疊面積」（VM 預測模型與參考模型的常態分佈重疊度）量化 VM 結果可信度；附 RI threshold | F.-T. Cheng, Y.-T. Chen, Y.-C. Su, D.-L. Zeng, "Evaluating Reliance Level of a Virtual Metrology System", *IEEE Transactions on Semiconductor Manufacturing*, vol.21, no.1, pp.92–103, Feb 2008 | **VERIFIED** | DOI: 10.1109/TSM.2007.914373 · <https://ieeexplore.ieee.org/document/4447298/> |
| **GSI**（Global Similarity Index） | Mahalanobis-like：評估「當前輸入製程資料」與「建模用全部歷史製程資料」的整體相似度（以標準化後的 Mahalanobis 距離為基礎）；同篇另定義 ISI（Individual Similarity Index） | 同上（Cheng et al. 2008, T-SM 21(1):92–103） | **VERIFIED** | DOI: 10.1109/TSM.2007.914373 · <https://ieeexplore.ieee.org/document/4447298/> |
| **DQI_x**（製程資料品質指標） | 以 PCA 抽取製程資料特徵，再用 Euclidean distance 整合為單一品質指標，評估製程輸入資料品質 | Y.-T. Huang, F.-T. Cheng, "Automatic Data Quality Evaluation for the AVM System", *IEEE T-SM*, vol.24, no.3, pp.445–454, 2011 | **VERIFIED** | DOI: 10.1109/TSM.2011.2146006 · <https://ieeexplore.ieee.org/document/5766761> |
| **DQI_y**（量測資料品質指標） | 以 ART2（Adaptive Resonance Theory 2）+ normalized variability 定義，評估量測（metrology）資料品質 | 同上（Huang & Cheng 2011, T-SM 24(3):445–454） | **VERIFIED** | DOI: 10.1109/TSM.2011.2146006 · <https://ieeexplore.ieee.org/document/5766761> |

> 註：RI 與 GSI 的「正典」原始定義出自 **Cheng et al. 2008（T-SM 21(1)）**；其後在 Cheng, Huang, Kao 2012（T-ASE 9(1)，引用編號 1）中整合進完整 AVM 系統架構。DQI_x / DQI_y 出自 Huang & Cheng 2011（T-SM 24(3)，引用編號 2）。

### Conformal / 現代 soft-sensor 補登（2026-07-17 CrossRef + 出版商 primary-source 二次查證）

> 來源：`conformal_cv.py` 的 **Barber 2021**（原標 NOT VERIFIED，CV+/jackknife+ 理論依據）+ `redteam_citations.md` §4b 五筆（2026-06-02 首查）。本輪逐筆重查 **CrossRef API**（`api.crossref.org/works/<doi>`，DOI 註冊權威）取回題名/卷期/作者/年；Barber 頁碼 CrossRef 未收錄 → 另經 **Project Euclid** 出版商頁確認 486–507。零捏造、零 NOT FOUND。

| 文獻 | 用途（本專案） | 查證狀態 | 正確書目 | DOI |
|---|---|---|---|---|
| **Barber, Candès, Ramdas & Tibshirani 2021** | CV+/jackknife+ 小 n 可信區間之理論依據（`detectors/conformal_cv.py`；worst-case 覆蓋 ≥1−2α 之出處） | **VERIFIED** | R. F. Barber, E. J. Candès, A. Ramdas, R. J. Tibshirani, "Predictive inference with the jackknife+", *The Annals of Statistics*, vol.49, no.1, pp.486–507, Feb 2021 | 10.1214/20-AOS1965 |
| Zhang, Zhou et al. 2025 | 工業時序 CP + 分佈偏移下的不確定度量化 | **VERIFIED** | R. Zhang et al., "Uncertainty Quantification Based on Conformal Prediction for Industrial Time Series With Distribution Shift", *IEEE Transactions on Industrial Informatics*, vol.21, no.5, pp.3676–3685, 2025 | 10.1109/TII.2025.3529920 |
| Wang et al. 2022 | Unified JITL 自適應 soft sensor（非線性/時變化工程序） | **VERIFIED** | P. Wang, Yin, Bai, Deng, Shao, "A unified just-in-time learning paradigm and its application to adaptive soft sensing for nonlinear and time-varying chemical process", *Chemical Engineering Science*, vol.258, art.117753, 2022 | 10.1016/j.ces.2022.117753 |
| Zhou et al. 2023 | 時空 deep LSTM soft sensor（嵌入領域知識） | **VERIFIED**（⚠️ 期刊為 *Eng. Appl. Artif. Intell.*，非 audit 誤植的 Control Eng. Pract.） | J.-Y. Zhou, Yang, Wang, Cao, "A soft sensor modeling framework embedded with domain knowledge based on spatio-temporal deep LSTM for process industry", *Engineering Applications of Artificial Intelligence*, vol.126, art.106847, 2023 | 10.1016/j.engappai.2023.106847 |
| Ji et al. 2024 | CVA 殘差統計 incipient 故障早偵測（動態程序） | **VERIFIED** | H. Ji, Hou, Shao, Zhang, "Incipient fault detection for dynamic processes with canonical variate residual statistics analysis", *Chemometrics and Intelligent Laboratory Systems*, vol.252, art.105189, 2024 | 10.1016/j.chemolab.2024.105189 |
| Guan et al. 2023 | 條件正規化流 MTS 異常偵測（⚠️ 通用 MTS，非 TEP/化工專屬 → 引用須標「題材匹配為類比」） | **VERIFIED** | S. Guan et al., "Conditional normalizing flow for multivariate time series anomaly detection", *ISA Transactions*, vol.143, pp.231–243, 2023 | 10.1016/j.isatra.2023.09.002 |

---

## 2. 五維度 半導體 ↔ 化工 對照表

| 維度 | 半導體錨點文獻（已驗證） | 化工原生對應文獻（已驗證） | 化工側 DOI / URL | transfer 註記（可轉 / 差異） |
|---|---|---|---|---|
| **1. AVM / 虛擬量測 → 化工 soft sensor** | Cheng, Huang, Kao 2012, *IEEE T-ASE* 9(1):181–188（AVM 系統）；Cheng et al. 2008 *T-SM* 21(1):92–103（RI/GSI） | Kadlec, Gabrys, Strandt, "Data-driven Soft Sensors in the Process Industry", *Computers & Chemical Engineering*, vol.33, no.4, pp.795–814, 2009 | DOI: 10.1016/j.compchemeng.2008.12.012 · <https://www.sciencedirect.com/science/article/abs/pii/S0098135409000076> | **可轉**：以易測製程量推估難測品質量的核心思路一致；RI/GSI 的「預測信賴度 + applicability domain」概念可直接映射至 soft sensor 的信賴度估計。**差異**：半導體為 wafer-to-wafer 離散批次、量測延遲大、recipe 切換頻繁；化工多為連續/慢時變，drift 形態與更新頻率不同。 |
| **2. Mahalanobis / T² → 化工 MSPC** | Verdier & Ferreira 2011, *IEEE T-SM* 24(1):59–68（adaptive Mahalanobis + kNN）；Shi et al. 2013 *Acta Automatica Sinica* 39(9)（Mahalanobis-RTPCA） | MacGregor & Kourti, "Statistical process control of multivariate processes", *Control Engineering Practice*, vol.3, no.3, pp.403–414, 1995；基準問題：Downs & Vogel, "A plant-wide industrial process control problem", *Computers & Chemical Engineering*, vol.17, no.3, pp.245–255, 1993（Tennessee Eastman） | MSPC: DOI 10.1016/0967-0661(95)00014-L · <https://www.sciencedirect.com/science/article/abs/pii/096706619500014L> · TE: DOI 10.1016/0098-1354(93)80018-I | **可轉**：Hotelling T² / Mahalanobis 距離為共通的多變量距離度量，GSI 本質上是 Mahalanobis-like 相似度，與化工 MSPC 的 T² 統計量同源。**差異**：Verdier 指出半導體變數常非高斯，故改用非參數 kNN；化工傳統 MSPC 多假設近似高斯並用 PCA 投影，需注意分佈假設落差。 |
| **3. KL / Wasserstein 分佈漂移 → 化工 domain adaptation / concept drift** | （半導體側 transfer/分佈對齊以引用 5 之 DTW + recipe constraint 為錨；分佈漂移概念上對應 GSI 偏移偵測） | Zhang, Yan, Ren, Cheng et al., "Dynamic transfer soft sensor for concept drift adaptation", *Journal of Process Control*, vol.123, pp.50–63, 2023；綜述見引用 4（IECR 2026 transfer learning review） | DOI: 10.1016/j.jprocont.2023.01.012 · <https://www.sciencedirect.com/science/article/abs/pii/S0959152423000203> | **可轉**：以分佈距離（KL / Wasserstein）量化 source↔target domain 偏移、觸發模型更新，與 GSI「當前 vs 歷史分佈相似度」邏輯同構。**差異**：半導體 drift 多由 recipe / chamber 切換造成階躍式 domain shift；化工 concept drift 多為連續慢時變（觸媒老化、季節），需動態（dynamic PLS）而非單次對齊。 |
| **4. DTW / 批次軌跡對齊 → 化工批次製程** | Owens, Sun et al. 2024, *SEMI ASMC*（DTW + recipe-step constraint 對齊製程訊號，引用 5） | Nomikos & MacGregor, "Monitoring batch processes using multiway principal component analysis", *AIChE Journal*, vol.40, no.8, pp.1361–1375, 1994；及 "Multivariate SPC Charts for Monitoring Batch Processes", *Technometrics*, vol.37, no.1, pp.41–59, 1995；對齊法：Nielsen, Carstensen, Smedsgaard, "Aligning of single and multiple wavelength chromatographic profiles … using correlation optimised warping (COW)", *Journal of Chromatography A*, vol.805, pp.17–35, 1998 | MPCA: DOI 10.1002/aic.690400809 · Technometrics: DOI 10.1080/00401706.1995.10485888 · COW: DOI 10.1016/S0021-9673(98)00021-1 · <https://www.sciencedirect.com/science/article/abs/pii/S0021967398000211> | **可轉**：批次/批號軌跡長度不一需時間對齊，DTW 與 COW 解同類問題；半導體 recipe-step constraint 對應化工的 batch phase/階段切點。**差異**：化工社群慣用 COW（限制較硬、保留積分面積）與 MPCA「軌跡展開」；半導體 DTW 約束來自 recipe step。對齊後皆接 MSPC/MPCA 監控。 |
| **5. PCA T² / SPE → 化工 MSPC 起源** | Shi et al. 2013（RTPCA + T²/SPE 故障偵測，引用 6） | Nomikos & MacGregor 1994/1995（同維度 4，MPCA 之 T² 與 SPE 控制限起源）；綜述：S. J. Qin, "Survey on data-driven industrial process monitoring and diagnosis", *Annual Reviews in Control*, vol.36, no.2, pp.220–234, 2012 | Qin: DOI 10.1016/j.arcontrol.2012.09.004 · <https://www.sciencedirect.com/science/article/abs/pii/S1367578812000399> | **可轉**：T²（模型內變異）與 SPE/Q（殘差空間）雙統計量為化工 MSPC 起源，半導體 FDC 直接沿用；Qin 綜述系統化整理偵測/診斷/可識別性。**差異**：化工 PCA 多在連續穩態或批次展開資料上建模；半導體須處理高維 trace、context（recipe/chamber）切換造成的多模態。 |

---

## 3. 開源化工資料集清單

| 名稱 | 形態（連續/批次） | 下載 URL | 授權 | 取得方式註記 |
|---|---|---|---|---|
| **Tennessee Eastman Process — Additional Simulation Data for Anomaly Detection（Rieth et al. 2017）** | 連續（含 20 種 fault + fault-free） | <https://dataverse.harvard.edu/dataset.xhtml?persistentId=doi:10.7910/DVN/6C3JR1> | Harvard Dataverse（CC0 公共領域，依 Dataverse 預設）；請以頁面實際標示為準 | DOI 10.7910/DVN/6C3JR1。每種 fault 含 500 runs（不同 random seed），分 fault-free(0) 與 fault 1–20；R/RData 格式。底層模型源自 Downs & Vogel 1993。 |
| **tep2py（Python 介面）** | 連續（產生 TEP 模擬資料） | <https://github.com/camaramm/tep2py> | 見 repo LICENSE | 包裹原始 Fortran（Braatz group）程式，需用 f2py 由原始碼編譯；產生帶 disturbance 的 TEP 資料表。 |
| **pyTEP（互動式模擬 API）** | 連續 | <https://github.com/ccreinartz11/pytep> | 見 repo LICENSE | 需安裝 MATLAB Engine for Python（需授權 MATLAB/Simulink）+ Python 3.7；支援互動式情境設定。論文：SoftwareX 2022, DOI 10.1016/j.softx.2022.101053。 |
| **IndPenSim — Industrial-scale Penicillin Fermentation（Goldrick et al.）** | 批次（fed-batch fermentation） | 官方：<http://www.industrialpenicillinsimulation.com> · Mendeley Data：<https://data.mendeley.com/datasets/npt257bjxn/1> · 模擬器 MATLAB：<https://www.mathworks.com/matlabcentral/fileexchange/49041> | Mendeley Data（CC BY 4.0，依頁面標示）；MATLAB File Exchange 依其 BSD 條款 | 100 批 × 完整製程 + Raman 光譜（約 2.5 GB）；batch 1–30 recipe 驅動、31–60 操作員、61–90 APC+Raman、91–100 含 fault。基準論文見下。 |
| **UCI Gas Sensor Array Drift（Vergara et al. 2012）— B2 真實集 adapter** | 離散量測（time-ordered batches；感測器跨 batch 老化 = concept/sensor drift） | <https://archive.ics.uci.edu/dataset/224/gas+sensor+array+drift+dataset> | CC BY 4.0（依頁面標示） | 128 features=16 sensor×8；6 氣體；10 batch 跨 36 月，明確時間漂移結構。論文 DOI 10.1016/j.snb.2012.01.074；資料集 DOI 10.24432/C5RP6W。**已於 `continuous_datasets_survey.md` §資料集表（★3）查證**——本表為單一入口指標，不重複 stamp。 |

### IndPenSim 相關基準論文（已驗證）

- Goldrick, S., Ştefan, A., Lovett, D., Montague, G., Lennox, B., "The development of an industrial-scale fed-batch fermentation simulation", *Journal of Biotechnology*, vol.193, pp.70–82, 2015. DOI: 10.1016/j.jbiotec.2014.10.029 · <https://www.sciencedirect.com/science/article/abs/pii/S0168165614009377>
- Goldrick, S., et al., "Modern day monitoring and control challenges outlined on an industrial-scale benchmark fermentation process", *Computers & Chemical Engineering*, 2019. <https://www.sciencedirect.com/science/article/pii/S0098135418305106>

---

## 4. 風險旗標（NOT FOUND / 可疑 / 需注意）

| 項目 | 旗標等級 | 說明與處置 |
|---|---|---|
| 引用 4「IECR 2026」年份 | ✅ 已澄清（非風險） | 初判「2026 年份可疑」，經查 **確為真實已發表**（DOI 10.1021/acs.iecr.5c05144），非捏造。今天日期 2026-06-01，論文 2026-04 線上，時序合理。 |
| 引用 3 第二作者姓名 | ⚠️ 已修正 | 部分二手來源誤植為「António Ferreira」，正確為 **Ariane Ferreira**。引用時務必更正。 |
| 引用 2 卷期 | ⚠️ 已修正 | 原引用僅寫「2011」，正確為 **vol.24, no.3, pp.445–454**；勿與引用 3（同年同刊但 no.1）混淆。 |
| 引用 5 作者順序 | ⚠️ 需注意 | 原報告以「Fan-Keng Sun 等」為首，實際 IEEE 版第一作者為 **Rachel Owens**（MIT thesis 亦由 Owens 撰）；Sun 為共同作者。引用時建議列 "Owens, Sun, et al."。 |
| DTW 論文 DOI vs thesis | ℹ️ 說明 | 同一成果有兩種形態：IEEE ASMC 會議論文（DOI 10.1109/ASMC61125.2024.10545476）與 MIT thesis（dspace 全文）。正式引用用前者，取全文用後者。 |
| 維度 3 半導體側錨點 | ℹ️ 說明 | KL/Wasserstein 分佈漂移在「半導體 AVM 原始論文」中並非以該名詞出現；其對應概念為 GSI 的分佈相似度偏移。跨領域對照時這是「概念映射」而非「同名方法直接移植」，撰寫正文時應明確標註此為類比。 |
| 授權標示 | ⚠️ 需於下載時確認 | 各資料集/repo 授權以**下載頁面當下實際標示**為準；本表所列為查證時的常見標示，正式使用（尤其商用）前請逐一核對 LICENSE / 資料集 terms。 |

---

### 查證方法說明

- 全部 6 筆引用 + RI/GSI/DQI 來源 + B 部分 5 維度化工文獻 + 2 類資料集，均經 WebSearch 交叉比對（IEEE Xplore / ScienceDirect / ACS / AIChE / HAL / Harvard Dataverse / 官方 simulator 站台 / GitHub）。
- 凡同時取得 DOI 與卷期/頁碼者標 VERIFIED；卷期或作者需更正者標 CORRECTED 並附正確值。
- 無任何一筆需標 NOT FOUND —— 6 筆引用全部為真實存在文獻（含初判可疑的 IECR 2026 review）。
