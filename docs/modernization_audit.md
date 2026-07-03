# 現代化建議審核報告（對抗式自我審查）

> 日期 2026-06-01 · 對象：`modernization_map.md` 及四份 `modernization_*.md` 的建議
> 方法：兩輪對抗審核（找漏洞→修正→再審修正本身），事實項以 WebSearch 查證 primary source
> 紀律：Rule 12（Fail loud，殘留不確定一律標記）；本報告為後續回填三份設計文件的權威依據

> ⚠️ **狀態標頭（後補）**：本檔已被 `redteam_reconciliation.md`（2026-06-02 三方對帳）取代為權威——三方判定本檔 6/11 條「修對一半」（F2,F3,H1,H3,H7,H8），H7 實為 ❌；衝突一律以 reconciliation §4 淨設計為準。本檔保留為歷史審核紀錄，內文不回改。

---

## A. 事實查證修正（已驗證 primary source）

| # | 原建議的問題 | 查證結果 | 修正 | 來源 |
|---|---|---|---|---|
| **F1** | RI DOI：L3 檔寫 `10.1109/TSM.2007.914388` | Cheng, Chen, Su, Zeng 2008, *Evaluating Reliance Level of a Virtual Metrology System*, IEEE T-SM **21(1):92–102**, doc 4447298 | 以 `literature_crossref.md` 已驗證的 **`10.1109/TSM.2007.914373`** 為準；L3 的 `.914388` **錯誤**，待修。頁碼 92-102 vs 92-103 待最終核〔後補註記：頁碼定讞 **92–103**（reconciliation F1、crossref/avm_metrics 一致，不再掛待核）；「L3 檔待修」已修（L3 檔現標 `.914373`）；且 `.914388` 經 R3 證實指向 Yoon & Shen 他人論文〕 | IEEE doc 4447298 |
| **F2** | Sinkhorn「sample complexity 1/√n、對少量點友善」 | Genevay 2019：Sinkhorn divergence **隨正則 ε 在 OT(n^−1/d) ↔ MMD(n^−1/2) 間插值**；計算 OT O(n³logn)、SD O(n²)、MMD O(n²) | ⚠️ **重大修正**：1/√n 僅在**大 ε**成立，而大 ε **犧牲 OT 幾何保真**。少量點友善與保幾何是 **trade-off**，文件不可只講前者 | Genevay et al. 2019, AISTATS (PMLR 89) |
| **F3** | Energy Distance＝「免 kernel 的 MMD 替身」 | Sejdinovic 2013：energy distance **就是**用 distance-kernel 的 MMD（兩者等價） | Energy distance **非獨立第三家**，是 MMD 的特定 kernel 選擇 → 從 L4 候選**移除/併入 MMD** | Sejdinovic et al. 2013, *Ann. Stat.* 41(5):2263–2291, DOI 10.1214/13-AOS1140 |

## B. 概念漏洞修正（第一性原理）

| # | 漏洞 | 修正方案 | 嚴重度 |
|---|---|---|---|
| **H1** | **CP 需有標籤 calibration set，但本專案前提 Y 稀少**；CP 的 marginal coverage 在**單點最弱**，而 RI 正用於逐 run 單點信任；對**無標籤時刻 CP 無輸出** | **CP 不整碗取代 RI**。輸入域相似度（GSI/T²/SFA）保留為**無標籤可信度**；CP 僅在**有 lab Y 時**校準預測區間。改述：「CP 補強預測區間段；輸入域可信度仍由 GSI 擔綱」 | 🔴 關鍵 |
| **H2** | **「因為新就換」是謬誤**；經典 KS/PCA/Wasserstein 的可解釋＋解析控制限是真優勢；Phase-1「即插就換」有 fashion-driven 風險 | 改**證據驅動**：經典當 baseline 先跑，現代升級在 **TEP ground-truth A/B**，**證明改善成功判準才採用**。標題改「modernization **candidates**」 | 🔴 方法論 |
| **H3** | RBC「保證單變數故障必正確定位」——但本專案是**多變量關係**飄移，非單感測器故障 | RBC 可診斷性保證**僅限單感測器故障**；關係型飄移根因是一**組**變數，無乾淨保證。RBC 仍消 smearing（保留），「RBC高+ISI低」是**啟發式非定理** | 🟡 |
| **H4** | MMD「嚴格優於 KS」 | 過度宣稱。MMD 需 bandwidth（差核→低檢定力）→ 用 **MMDAgg** 免調參。正確：MMD 對**多維/關係型**漂移較佳（KS 僅 1D），非全面碾壓 | 🟡 |
| **H5** | DPCA「零成本」 | 堆疊 l 階 lag 使維度 p→p(l+1)，**惡化 n≫p 與痛點④奇異性**；非免費，需更多資料/正則，lag 階數要選 | 🟡 |
| **H6** | SFA「正中判準3」 | SFA 分「靜態操作點變動 vs 動態異常」，**助益**判準3，但「乾淨回歸 vs 殘留飄移」最終仍需 **L2/L4 對 golden-A 基準比較**收尾；SFA 是補強非完整解 | 🟢 |
| **H7** | Phase-1「全確定性」 | permutation（MMD/KS）、CP ensemble（EnbPI bootstrap）**僅固定 seed 才確定性**；split-CP/Sinkhorn/RBC/DPCA 本身確定性。須標固定 RNG seed 才合 Rule 5〔後補註記：對帳升級為 🔴/❌（C6）：固定 seed＝reproducibility≠statistical determinism≠type-I 控制（近門檻 p-value ±% 抖動、Pmin=1/(B+1)）；後續已以 FWER 單一決策點處置（health.py Holm，B3 [verified]）〕 | 🟢 |
| **H8** | L4 內部矛盾：上輪 KS+PSI+W ensemble，現代化又 KS→MMD、W→Sinkhorn | **收斂最終 L4**：MMD/MMDAgg（顯著性 p-value）＋ Sinkhorn（量級，含 ε 取捨）＋ PSI（嚴重度帶/溝通，少量點低權重），於 PCA 分數空間，permutation 校準＋持續性。**KS 退場**（被 MMD 1D 特例涵蓋）〔後補註記：對帳推翻（C7：KS(sup-CDF)≠1D MMD，「涵蓋」數學上錯）；as-built KS 保留為廉價 1D first-pass、觸發才升 MMD（drift.py 分層決策）〕 | 🟡 |

## C. 審核後的「淨設計結論」（修正後 Phase-1）

| 模組 | 審核後決策 |
|---|---|
| L1 資料品質 | FastMCD 抗污染協方差（replace 估計器）+ sanity check；Isolation Forest 列 P2 |
| L2 多變量 | **先 DPCA baseline（含維度膨脹/lag 取捨告知）**；SFA/CVA 列 P2，須 TEP A/B **證明**優於 DPCA 才採用 |
| 診斷 | RBC replace 原始 contribution（消 smearing）；ISI 當「關係型」輔助旗標（**啟發式**，非保證） |
| L3 軟測量 | base 維持 PLS/GPR |
| **可信度** | **GSI/輸入域相似度保留為無標籤可信度主力**；**CP 僅補強有 lab Y 時的預測區間**（split-CP，固定 seed）；RI 留對照〔後補註記：最終實作 CP 刻意取代 RI、live code 無 RI（soft_sensor.py:3-6）；無標籤可信度=GSI（＋ICAD 路徑，C3 補：本檔 H1 漏 ICAD 免標籤 conformal 變體）；新精靈 step-9 不得稱 RI〕 |
| **L4 漂移** | **MMD/MMDAgg（顯著性）＋ Sinkhorn（量級，標 ε–幾何 trade-off）＋ PSI（溝通）**〔後補註記：量級 as-built 改解析 1D-Wasserstein on PCA-score（無 ε 超參，drift.py）；Sinkhorn 留待真需多維 OT 幾何（reconciliation §4；D4 降級階梯 Sinkhorn→1D-Wasserstein）〕；PCA 分數空間；permutation（固定 seed）＋持續性；KS、Energy distance 退場〔後補註記：KS 退場被對帳推翻（C7：KS(sup-CDF)≠1D MMD，「涵蓋」數學上錯）；as-built KS 保留為廉價 1D first-pass、觸發才升 MMD（drift.py 分層決策）〕 |
| 分段 | ruptures(PELT) 切段；**仍需 steady/transition 標籤準則**（ruptures 給邊界非穩態判定） |
| 採用準則 | **全部 candidates 須在 TEP ground-truth 上 A/B 證明改善成功判準才正式納入**（Rule 4） |

## D. 把握度與殘留（Rule 12）

- **承載 Phase-1 決策的主張：高把握**（DPCA Ku1995、RBC Alcala&Qin2009、FastMCD、ruptures/PELT、MMD Gretton2012、Sinkhorn Genevay2019、split-CP 皆老牌穩固，適用邊界已由 A/B 修正釘住）。
- **無法宣稱每個 DOI 100%**（宣稱本身違反 Rule 12）。**殘留 NOT VERIFIED（皆 Phase-2/3，不 gate Phase-1，引用前須補官方 DOI）**：
  - 工業時序 CP 2025（IEEE 10870871）
  - Unified JITL 2022（Chem. Eng. Sci.）
  - Spatio-temporal LSTM 2023（Control Eng. Pract.）〔後補註記：期刊誤記——實為 *Eng. Appl. Artif. Intell.* 126:106847（DOI 10.1016/j.engappai.2023.106847，R3 抓到本檔此錯）；5 筆正式 DOI 已由 redteam_citations.md 補得，literature_crossref.md 補登仍待辦〕
  - CVA incipient 2024（Chemom. Intell. Lab. Syst.）
  - NF 時序 2023（ISA Trans.）
  - 會議無 DOI：TEP-GNN(arXiv 2210.11164)、Anomaly Transformer、Real NVP、Deep SVDD(PMLR)、DKL(PMLR)
- **不可被修掉的硬限制**：少量點偵測受**統計檢定力下限**約束；MMD/Sinkhorn 提升的是維度/關係敏感度，非「用 5 筆抓 0.2σ」。

## E. 收斂判定
跑兩輪（找漏洞→修正→再審修正本身），第二輪未再出現會改變 **Phase-1 決策**的新漏洞；三項事實已驗證、八項概念已界定邊界。→ **對「將寫進設計文件的 Phase-1 主張」已達事實依據之高把握**；殘留僅 Phase-2/3 DOI 補登，已隔離。

> 下一步：經同意後，依本報告 C 段把 `requirements_spec.md` / `functional_design.md` / `development_plan.md` 與 `modernization_map.md` 一併修正定案。〔後補註記：已完成（2026-06-02 v0.2 回填，commit 72a4173）——惟實際依 reconciliation §4 淨設計回填，非本檔 C 段〕
