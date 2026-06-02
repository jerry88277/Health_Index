# Red-Team 統計嚴謹度審查（獨立對抗複審）

> 日期 2026-06-02 · 立場：懷疑、不信任既有結論、自己重推
> 對象：`modernization_map.md`（原始建議）＋ `modernization_audit.md`（自我審核 F1–F3 / H1–H8）
> 方法：對每條主張獨立重推數學，凡引用新事實附 primary source（已 WebFetch/WebSearch 查證）；查不到標 NOT FOUND
> 紀律：Rule 7（衝突擇一說明）、Rule 12（Fail loud，不確定一律標記）
> 範圍邊界：本檔僅評統計嚴謹度，不改其他 `redteam_*` 檔，不回填設計文件

---

## 0. 一頁判決（TL;DR）

- **audit 的事實層（F1–F3）方向正確，但 F2、F3 都「對一半」**：F2 把 trade-off 講對了卻把率的成立條件講錯（1/√n 對**任意固定 ε** 都成立，問題在常數 e^{κ/ε} 對小 ε 與高維 d 爆炸）；F3 把「等價」講成無條件，漏掉**negative-type semimetric** 這個必要條件。
- **audit 的概念層最大盲點在 H1（CP）**：H1 正確指出「CP 需標籤」與「marginal 單點最弱」，但**漏掉 unsupervised / inductive conformal anomaly detection（ICAD）根本不需要 Y 標籤**這一整類變體；同時 H1 對 EnbPI/ACI 的「保證」照單全收（map 也是），未戳破 **EnbPI 只給 approximate-asymptotic 覆蓋、ACI 只給 long-run 平均且需線上 label stream**——而這兩個前提恰好在本專案 re-entry（非穩態、無線上 label）情境下失效。
- **雙方都漏的最大盲點**：(a) RBC 對**多變數同時故障仍會 smear**（本專案目標正是多變數關係漂移，非單感測器故障，RBC 的「保證」在此**完全不適用**）；(b) audit 引的「少量點檢定力下限」公式 `n≈2(z+z)²/δ²` 是**均值位移 + 單變量**公式，**不適用於本專案要抓的 covariance/relationship 漂移**，當「硬限制」引用屬張冠李戴；(c) 全鏈條 permutation/多 detector 併判，**無任何多重比較（multiplicity）校正**，Phase-1「全確定性」標記與「有效 type-I 控制」是兩回事。

---

## 1. 對原始建議（modernization_map.md）的新發現（漏洞表）

| # | 項目 | 問題（自己重推） | 嚴重度 | 修正 | 來源 |
|---|---|---|---|---|---|
| R1 | CP「P(y∈Ĉ)≥1−α 有保證」掛在 EnbPI/ACI 名下（map §①、L3 §2.1） | split-CP 才有 finite-sample distribution-free marginal 覆蓋。**EnbPI 只給 approximately valid、asymptotic 的 marginal 覆蓋，且前提是 error stationary strongly-mixing**；**ACI 只保 long-run 平均覆蓋**。把「有保證」一詞籠統套到時序變體＝誇大。 | 🔴 | 區分三檔：split-CP=finite-sample 保證（但需 exchangeable）；EnbPI=approximate+需 stationarity；ACI=long-run 平均。本專案 re-entry **是非穩態斷點**，恰好打破 EnbPI 的 stationary-mixing 前提 → 不能宣稱保證。 | Xu & Xie 2021 *Conformal prediction for time series* arXiv:2010.09107；Gibbs & Candès 2021 ACI arXiv:2106.00170（DOI:10.48550/arXiv.2106.00170） |
| R2 | ACI/EnbPI「契合 re-entry 漂移」（map §①、L3 §2.1/4.1） | ACI 的更新規則需要**每步真實 y_t** 來判斷上一個區間有沒有 cover；EnbPI 需殘差流。本專案前提是 **Y 稀少、無線上 label**。**無 label 時 ACI/EnbPI 根本無法運轉**，不是「marginal 單點不準」而已。 | 🔴 | 明列前提：時序 CP 變體需線上 label stream；本專案無 → 時序 CP 不可當 L3 主力，只能在「有 lab Y 補測時」批次校準。 | 同上；ACI 機制（區間未覆蓋則加寬）見 Gibbs & Candès 2021 |
| R3 | Sinkhorn「sample complexity 1/√n、少量點友善」（map §②、L4 §2.4） | 1/√n **率**對任意固定 ε 成立，但**常數 = e^{κ/ε}·(1+1/ε^⌊d/2⌋)**，κ=2L·diam(X)+‖c‖∞。小 ε（保 OT 幾何）時常數對 ε **指數爆炸**、且對維度 d 多項式爆炸。「少量點友善」只在大 ε（≈MMD 區）成立，此時已非 OT 幾何。 | 🟡 | 敘述改為：「Sinkhorn 在固定 ε 下達 1/√n，但常數隨 ε→0 指數惡化、隨 d 惡化；保 OT 幾何與少量點穩定是 trade-off」。ε 必須在 TEP 上掃描，不可宣稱「兼得」。 | Genevay et al. 2019 AISTATS, Thm 3：E\|S_ε−Ŝ_ε\|=O(e^{κ/ε}/√n·(1+1/ε^⌊d/2⌋))（arXiv:1810.02733，已 WebFetch ar5iv 取得式子） |
| R4 | 「MMD 嚴格優於 KS／取代 KS 主判據」（map §②、L4 §3.1） | 三點未講：(a) KS 有**解析 p-value**，MMD 需 permutation（成本×B）；(b) MMD 檢定力**強依賴 kernel/bandwidth**，差核→低 power，需 MMDAgg 補救；(c) 在**真 1-D 邊際**漂移上 KS 不一定輸，MMD 的 RKHS 距離未必更敏感。「嚴格優於」是過度宣稱。 | 🟡 | 改「在多維/關係型漂移上 MMD 較佳；1-D 上 KS 仍有解析校準優勢」。此點 audit H4 已部分修正（見裁決表）。 | Gretton et al. 2012 JMLR 13:723-773；Schrab et al. 2023 JMLR 24(194) MMDAgg |
| R5 | RBC「理論保證單變數故障必正確定位、嚴格消 smearing」（map §③） | RBC 的保證**僅限單感測器、且大故障幅度**；當**多個故障方向並存時，RBC 自身仍會 smear**（Alcala&Qin 原文：RBC 係數沿某方向的估計會被其他方向投影污染）。本專案目標是**多變數關係漂移**＝多方向 → RBC 的「保證」與「嚴格消 smearing」在此**不成立**。 | 🔴 | 改「RBC 消除單故障 smearing；多變數關係漂移下仍有殘留 smearing，無乾淨保證」。audit H3 抓到「僅單故障」，但**未戳破「嚴格消 smearing」這句在多故障下也是假的**。 | Alcala & Qin 2009 *Automatica* 45(7):1593-1600（RBC）；多方向 smearing 見原文與 *J. Process Control* 2016 S0959152416000196 |
| R6 | DPCA「零增量／零成本」（map §④、L2 §1.2） | 堆疊 l 階 lag 使維度 p→p(l+1)，**惡化共線性（痛點④的 Mahalanobis 奇異）與 n≫p 需求**；lag 階數本身是須調的超參。非零成本。 | 🟡 | audit H5 已正確修正（見裁決表），map 本身仍寫「零增量」，待同步。 | Ku et al. 1995 *Chemom. Intell. Lab. Syst.* 30:179-196 |
| R7 | 全鏈多 detector + 多 permutation **無多重比較校正** | L1(IsoForest)+L2(T²/SPE/SFA/CVA)+L4(MMD/Sinkhorn/PSI/ADWIN/PH) 多旗標併判，每個各自 α。**家族錯誤率（FWER）膨脹**：k 個獨立 α=0.05 檢定，至少一誤報機率 1−0.95^k。Phase-1「全確定性」標記與「有效 type-I 控制」是**兩回事**——固定 seed 只消除蒙地卡羅隨機，不解決 multiplicity。 | 🔴 | 加一層 FWER/FDR 控制（Bonferroni/Holm 或 BH），或明訂「融合分數＋單一持續性閾值」為唯一決策點、各 detector 只當特徵。這點 **map 與 audit 均未提**。 | 標準多重比較理論（Holm 1979 *Scand. J. Stat.* 6:65-70；Benjamini-Hochberg 1995 *JRSS-B* 57:289-300） |
| R8 | T²/SPE 控制限沿用 F/χ²，但對 DPCA/自相關資料 | 控制限公式 `T²_α=k(n²−1)/(n(n−k))·F` 假設**樣本獨立同分布且近高斯**。DPCA 後資料**強自相關**，有效樣本數 n_eff≪n，F/χ² 限會**低估、誤報率上升**。avm_metrics_definitions §5 直接沿用此式而未提自相關修正。 | 🟡 | 對動態模型用 KDE / block-bootstrap 經驗控制限，或以 n_eff 修正自由度。map/audit 均未觸及。 | Jackson & Mudholkar 1979（SPE 限）；自相關對 MSPC 控制限影響為 MSPC 常識 |

---

## 2. Audit-the-Audit 裁決表（F1–F3、H1–H8）

對 audit 每條獨立重推，給 ✅成立 / ⚠️過度或不完整 / ❌錯誤。

| 條目 | audit 主張（摘） | 裁決 | 理由（自己重推）｜應如何改 |
|---|---|---|---|
| **F1** | RI DOI 應為 `10.1109/TSM.2007.914373`（非 .914388），doc 4447298，pp.92-103 | ✅ 成立 | 與 `literature_crossref.md`（專案唯一真相，標 VERIFIED）一致：T-SM 21(1):92-103, Feb 2008, doc 4447298。L3 檔的 .914388 確為錯。**僅補一點**：頁碼 audit 自己標「92-102 vs 92-103 待核」，crossref 與 avm_metrics 皆作 **92-103**，可定為 92-103，不必再掛待核。 |
| **F2** | Sinkhorn 1/√n **僅在大 ε** 成立，大 ε 犧牲 OT 幾何，少量點友善與保幾何是 trade-off | ⚠️ 過度／不精確 | **trade-off 結論對，但率的條件講錯**。Genevay Thm 3：E\|誤差\|=O(e^{κ/ε}/√n·(1+1/ε^⌊d/2⌋))。1/√n **率對任意固定 ε>0 都成立**，不是「僅大 ε」；真正的痛點是**常數** e^{κ/ε}·1/ε^⌊d/2⌋ 隨 ε→0 **指數爆炸**、隨維度 d 爆炸。改述：「1/√n 是率；保 OT 幾何（小 ε）時常數對 ε 指數、對 d 多項式惡化 → 有效樣本需求暴增」。 |
| **F3** | Energy distance **就是** distance-kernel 的 MMD，兩者等價 → 從候選移除 | ⚠️ 過度一般化 | 等價**有條件**：須以 **negative-type semimetric**（如 ‖·‖^q, 0<q≤2 的 Euclidean 距離）誘導的 distance kernel，MMD 才等於 energy distance。反向：任意 PD kernel 的 MMD 可寫成某 negative-type semimetric 的 energy distance。audit 漏掉「negative-type」這個必要條件，寫成無條件等價＝過度一般化。「從候選移除」的**操作結論可接受**（在標準 Euclidean energy distance 下確等價於對應 MMD），但理由須補條件，否則誤導未來對非歐距離的使用。 | Sejdinovic et al. 2013 *Ann. Stat.* 41(5):2263-2291, DOI 10.1214/13-AOS1140 |
| **H1** | CP 需標籤 calibration set；marginal 單點最弱；無標籤時 CP 無輸出 → CP 不整碗取代 RI，GSI/T²/SFA 當無標籤可信度，CP 只在有 lab Y 時校準 | ⚠️ 不完整（漏一整類變體） | **方向對、操作結論（GSI 擔無標籤可信度、CP 補有 Y 區間）可採**，但**遺漏 unsupervised / inductive conformal anomaly detection（ICAD）**：ICAD 用 nonconformity measure 對 test 點算 conformal p-value，**只需 pristine 校準集、不需 Y 標籤**——這恰好是「無標籤可信度」的 CP 原生解，與 GSI 競爭。H1 把「CP=需 Y 的回歸區間 CP」當成 CP 全貌＝以偏概全。改：補一格「無標籤路徑可用 ICAD（conformal p-value on input/representation），與 GSI 並列比較，非互斥」。另：H1 對 EnbPI/ACI 的覆蓋「保證」未質疑（見 R1/R2），仍把時序 CP 當保證源，需一併修。 | ICAD：Laxhammar & Falkman；綜述見 nonconform 套件與 cross-conformal anomaly p-values arXiv:2402.16388。exchangeability/ICAD 不需 Y：WebSearch 確認 |
| **H2** | 「因為新就換」是謬誤；改證據驅動、TEP A/B 證明改善才採用；標題改 candidates | ✅ 成立 | 方法論正確且與 Rule 4/2 一致。**唯一補強**：A/B 的「改善」須對**正確的 alternative** 評估——本專案目標是 relationship/covariance 漂移，評測指標不能只看 mean-shift detection rate（否則回到 R-bis 的張冠李戴）。建議 A/B 評測集明確含「每變數在規格內的純多變量漂移」案例（呼應 Rule 9）。 |
| **H3** | RBC 可診斷性保證僅限單感測器故障；關係型漂移根因是一組變數、無乾淨保證；「RBC高+ISI低」是啟發式非定理 | ⚠️ 不完整 | **單故障限制抓對、啟發式定性抓對**，但**漏掉更硬的一刀**：RBC 在**多故障方向並存時自身仍 smear**（Alcala&Qin 原文明述 RBC 係數受其他方向投影污染）。所以不只是「無乾淨保證」，而是 map 說的「**嚴格消 smearing**」這句**在本專案的多變數情境直接為假**。應把 map 的「嚴格消 smearing」降級為「消除單故障 smearing、多故障殘留」。 | Alcala & Qin 2009；多方向污染見原文 §smearing analysis |
| **H4** | MMD「嚴格優於 KS」過度宣稱；MMD 需 bandwidth→用 MMDAgg；MMD 對多維/關係型較佳非全面碾壓 | ✅ 成立 | 重推一致。**補兩點精度**：(1) MMDAgg 的「免調參」代價是對一組 bandwidth 各跑一次 permutation/wild-bootstrap，成本×(#bandwidth)；其保證是**非漸近 type-I 控制 + Sobolev ball 上 minimax power（差一個 iterated-log 因子）**，非「任意 alternative 最優」。(2) audit 未提 KS 的**解析 p-value vs MMD 需 permutation** 這個實務差異（R4），建議併入。 | Schrab et al. 2023 JMLR 24(194):1-81 |
| **H5** | DPCA 非零成本：維度 p→p(l+1) 惡化 n≫p 與奇異性，lag 要選 | ✅ 成立 | 完全正確，且正中痛點④。map 仍寫「零增量/零成本」需同步改。無過度。 |
| **H6** | SFA 助益判準3 但非完整解，最終仍需 L2/L4 對 golden-A 比較收尾 | ✅ 成立 | 正確且誠實。SFA 的 slow/fast 切分閾值是額外超參，audit 已在 map §④隱含、此處可不再加碼。無異議。 |
| **H7** | Phase-1「全確定性」：permutation/EnbPI bootstrap 僅固定 seed 才確定；split-CP/Sinkhorn/RBC/DPCA 本身確定 | ⚠️ 不完整（真盲點在別處） | **「固定 seed→可重現」對，但把問題框小了**。固定 seed 只消除**蒙地卡羅隨機性**，**不解決多重比較（R7）**：多 detector × 多 permutation 的 FWER 膨脹與 seed 無關。audit 把「確定性合規」當成統計效力合規，混淆兩個層次。應補：確定性 ≠ 有效 type-I 控制；需 multiplicity 校正。 |
| **H8** | 收斂最終 L4：MMD/MMDAgg(p-value)+Sinkhorn(量級,含 ε 取捨)+PSI(嚴重度,少量點低權重)，PCA 分數空間，permutation+持續性；KS 退場（被 MMD 1D 特例涵蓋） | ⚠️ 過度（一處錯誤＋一處盲點） | (1) **「KS 被 MMD 1D 特例涵蓋」不準確**：1-D MMD（特定 kernel）與 KS（sup-norm on CDF）**是不同統計量**，對不同 alternative 敏感度不同；KS 對單調 CDF 位移、MMD 對 mean-embedding 差，無「涵蓋」關係。退場理由應改為「1-D 上 KS 仍可用、但多維主判據改 MMD」，而非數學涵蓋。(2) **盲點**：在 **PCA 分數空間**做 two-sample test，分數本身是從**同一批資料估的 PCA**投影 → P 與 Q 的分數**非獨立於估計步驟**，permutation null 的 exchangeability 在「用 pooled 資料重估 PCA」與否之間有微妙差別，須明確固定「PCA 在 golden-A 上 fit、固定後投影」否則 p-value 偏樂觀。(3) PSI 分箱在少量點下變異大，「低權重」對，但建議**直接標 PSI 不參與顯著性決策、僅供溝通**。 |

**裁決統計**：F1✅ / F2⚠️ / F3⚠️ / H1⚠️ / H2✅ / H3⚠️ / H4✅ / H5✅ / H6✅ / H7⚠️ / H8⚠️。
→ 3 條完全成立（F1,H2,H4,H5,H6 實為 5 條✅）、6 條過度或不完整、0 條全錯。**audit 無捏造、無方向性錯誤，但在 F2/F3/H1/H3/H7/H8 六處「修對了一半」**，主要模式是：抓到表層修正，但**漏掉更深的條件/變體/盲點**。

---

## 3. 我（red team）發現、雙方都漏掉的盲點

| # | 盲點 | 為何關鍵 | 建議 |
|---|---|---|---|
| B1 | **「少量點檢定力下限」公式用錯 alternative** | audit §D 把 `n≈2(z_{1-α/2}+z_{1-β})²/δ²` 當「不可被修掉的硬限制」。但此式是 **two-sample 均值差 + 已知變異 + 單變量** 的標準功效公式（δ＝標準化均值位移 Δμ/σ）。本專案目標是 **covariance/relationship 漂移**（均值可不動），此式**根本不描述該 alternative 的檢定力**。當「硬限制」引用＝張冠李戴。 | 改用對應 alternative 的功效分析：協方差變化用 likelihood-ratio / box-M 類功效，或在 TEP 上以模擬 power curve（固定 relationship-drift 幅度掃 n）實證下限，不套均值位移公式。 |
| B2 | **全鏈無多重比較校正（FWER/FDR）** | 見 R7。多 detector + 多窗 + 多 permutation 併判，family-wise 誤報率隨檢定數膨脹；「golden-A 維持低分」這條 DoD 會因 multiplicity 被破壞（健康期也會有人誤報）。 | 單一融合分數＋單一閾值為唯一決策點（各 detector 當特徵，不各自宣告），或 Holm/BH 校正。 |
| B3 | **permutation 校準在「PCA 分數空間」的 exchangeability 細節** | 在以 pooled 資料估的 PCA 分數上做 permutation two-sample，若 PCA 隨 permutation 重估則 OK，若固定 PCA 則 null 分佈與「golden-A fit、test 投影」設定耦合，p-value 可能偏樂觀（雙方都只說「permutation 校準」未界定 refit 與否）。 | 明訂：PCA/DPCA/SFA 模型在 **golden-A** 上 fit 並凍結，permutation 只重排樣本標籤、不重估模型；並在 TEP 上驗 null 的實際 type-I≈α。 |
| B4 | **自相關對 T²/SPE 控制限與 permutation 的雙重破壞** | 見 R8。連續製程強自相關使 (a) F/χ² 控制限低估、(b) i.i.d. permutation 破壞時間相依結構 → null 過窄、誤報。DPCA 部分吸收但不消除。 | 控制限用 block-bootstrap / KDE；two-sample permutation 改 **block-permutation** 保留短程相依。 |
| B5 | **MMD/Sinkhorn 的「漂移幅度」不可跨維度/跨核比較** | map 把 Sinkhorn 當「漂移多大」的可解釋量級。但 Sinkhorn 值依 ε、核/cost、標準化方式而變，**非無量綱**；不同 campaign 間直接比大小可能誤導。 | 對量級指標做 **golden-A 內部自舉的標準化（如 z-score over null 分佈）** 再跨段比較，而非用原始距離值。 |
| B6 | **Health Index 0–1 融合的單調性與校準未定義** | DoD 要求「golden-A 低、隱性漂移早升、區分乾淨回歸 vs 殘留」。但把多個**不同尺度、不同 null**的統計量加權成 0–1，未定義各分量如何標到可比尺度、權重如何定、是否單調。map §6 僅列「先簡單加權」，未談校準。 | 各分量先轉成**對 golden-A null 的尾機率（p 或 1−p）或標準化分數**再融合；在 TEP ground-truth 上校準權重並驗單調性（Rule 9 的 WHY 測試）。 |

---

## 4. 把握度與 NOT FOUND

**高把握（已查 primary source 並重推）**：
- Genevay 2019 Thm 3 的 `e^{κ/ε}/√n·(1+1/ε^⌊d/2⌋)` 式子（ar5iv 全文取得）→ R3/F2 裁決。
- Sejdinovic 2013 energy↔MMD 需 **negative-type semimetric** 條件（Ann. Stat. 摘要明述）→ F3 裁決。
- EnbPI=approximate+stationary-mixing、ACI=long-run 平均且需線上 label（Xu&Xie 2021、Gibbs&Candès 2021）→ R1/R2/H1。
- ICAD 不需 Y 標籤（多來源確認）→ H1 不完整。
- RBC 單故障保證 + 多方向仍 smear（Alcala&Qin 2009 原文）→ R5/H3。
- F1 DOI `.914373` 與 crossref VERIFIED 一致。

**中把握（理論常識，未逐篇 fetch 全文）**：
- 多重比較 FWER 膨脹（R7/B2）、自相關對 MSPC 控制限影響（R8/B4）、均值位移功效公式不適用協方差漂移（B1）—皆為標準統計推論，未另引單篇 primary source 逐字核對。

**NOT FOUND / 未逐字驗證**：
- Genevay Thm 3 **官方 PMLR PDF 為二進位壓縮，無法逐字抽取**；式子取自 ar5iv HTML 鏡像（arxiv:1810.02733），與 PMLR 應一致但未對 PMLR 原頁逐字比對 → 標**式子來源=ar5iv，DOI 層級 NOT FULLY CROSS-CHECKED**。
- 沿用 audit/map 既有的 NOT VERIFIED 清單（工業時序 CP 2025 IEEE 10870871、Unified JITL 2022、CVA incipient 2024 等）本檔**未重新查證**，維持其 NOT VERIFIED 標記，不升級為已驗證。
- ICAD 原始文獻（Laxhammar & Falkman）僅由綜述/套件間接確認，**未取得原始 DOI 逐字核對** → 標 ICAD 概念成立、原始引用 NOT FULLY VERIFIED。

---

## 5. 下一步
- 在 TEP 上以模擬 power curve 實證「relationship-drift 對 n」的檢定力下限，取代 B1 的均值位移公式。
- L4 決策點收斂為單一融合分數＋FWER/FDR 校正（B2/R7），並用 block-permutation + 凍結 PCA 釘住 null（B3/B4）。
- 把 map 的「零成本 DPCA／嚴格消 smearing RBC／MMD 嚴格優於 KS／EnbPI 有保證」四處用語按本檔 R3/R5/R4/R1 降級改寫，再回填設計文件。
