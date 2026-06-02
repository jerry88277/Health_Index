# 紅隊三方對帳報告（球員兼裁判的補正）

> 日期 2026-06-02 · 對帳對象：`modernization_map.md`（建議）+ `modernization_audit.md`（我的自我審核 F1–F3/H1–H8）
> 三位獨立紅隊：R1 統計嚴謹度（`redteam_statistical.md`）、R2 產業落地（`redteam_deployment.md`）、R3 文獻誠信（`redteam_citations.md`）
> 原則：衝突 surface 不平均（Rule 7）；不確定一律標記（Rule 12）
> 元結論：**我的自我審核無捏造、無方向性錯誤，但在 F2/F3/H1/H3/H7/H8 六處「修對一半」**——印證自審的共同盲點，紅隊有實質增值。

---

## 1. 三方對 F1–F3 / H1–H8 的裁決對帳

| 條 | 我的審核（原） | R1 統計 | R2 落地 | R3 文獻 | **對帳後最終裁決** |
|---|---|---|---|---|---|
| F1 | RI DOI 改 `.914373` | ✅ | ✅ | ✅ **且 `.914388` 是另一篇真實他人論文（Yoon&Shen pp.83-91），更危險** | ✅ 成立；頁碼定 **92–103**（不再掛待核）|
| F2 | Sinkhorn 1/√n 僅大 ε | ⚠️ 率對任意固定 ε 成立，痛點是**常數 e^{κ/ε}·(1+1/ε^⌊d/2⌋) 隨 ε→0、隨 d 爆炸** | ✅+加碼 ε 是新增運維超參 | ✅ DOI 對 | ⚠️ **過度/不精確**：改「1/√n 是率；保幾何(小ε)時常數對 ε 指數、對 d 多項式惡化」 |
| F3 | Energy=MMD，移除 | ⚠️ 等價**需 negative-type semimetric** 條件 | ✅ 去重 | ✅ DOI 對 | ⚠️ 操作結論可留，**理由補條件** |
| H1 | CP 不取代 RI；GSI 擔無標籤、CP 補有 Y | ⚠️ **漏 ICAD 免標籤 CP 變體**；EnbPI/ACI「保證」被高估 | ✅ **最對的落地修正**，補最小 calibration 門檻 | — | ⚠️ **方向對、不完整**：補 ICAD 路徑＋戳破時序 CP 保證 |
| H2 | 證據驅動 A/B | ✅ 但須評**對的 alternative**(關係漂移非均值) | ⚠️ **缺出口條件**＋oracle 是合成 pyTEP(循環) | — | ⚠️ 成立但**補出口條件＋綁真實集** |
| H3 | RBC 僅單故障保證 | ⚠️ **漏：多方向時 RBC 自身仍 smear**→「嚴格消 smearing」直接為假 | ✅ 需上 UI | — | ⚠️ **不完整**：再降級「嚴格消 smearing」 |
| H4 | MMD 非嚴格優於 KS | ✅ | ⚠️ **MMDAgg 沒解 permutation 成本**，我誤當擋箭牌 | — | ⚠️ 補：MMDAgg 只免 bandwidth、不免成本 |
| H5 | DPCA 非零成本 | ✅ | ✅ 補 **n/p 硬 gate** | — | ✅ 成立＋加 n≥10·p(l+1) gate |
| H6 | SFA 非完整解 | ✅ | ✅ | — | ✅ 成立 |
| H7 | 固定 seed 即確定性 | ⚠️ 真盲點是**多重比較非 seed** | ❌ **應升🔴**：reproducibility≠statistical determinism≠type-I 控制 | — | ❌ **我嚴重低估**：拆成(a)MC p-value 變異(稽核破口)(b)無 FWER 校正 |
| H8 | KS 退場(被 MMD 1D 涵蓋) | ⚠️ **「涵蓋」數學上錯**(KS sup-CDF≠1D MMD)；PCA 分數 permutation 須凍結 PCA | ⚠️ **KS 不該退**，當廉價 1D first-pass | — | ⚠️ **過度**：KS 保留為 first-pass，成本分層 |

> **裁決統計**：完全成立 F1,H5,H6（＋H2/H4 半成立）；**6 條過度或不完整（F2,F3,H1,H3,H7,H8）；H7 實為❌**。三方對 R1/R2 無實質衝突（H7 嚴重度 R1⚠️/R2❌ 同向，對帳取 🔴）。

## 2. 「我審錯／過度修正」清單（self-correction 的 correction）

| # | 我原本的問題 | 正確版本 |
|---|---|---|
| C1 | F2「1/√n 僅大 ε」 | 率對任意固定 ε 成立；真問題是**常數隨 ε→0 指數、隨維度 d 多項式爆炸**（Genevay Thm 3）|
| C2 | F3「無條件等價」 | 等價**須 negative-type semimetric**；標準 Euclidean energy distance 才＝對應 MMD |
| C3 | H1 把 CP 當「需 Y 的回歸區間 CP」 | 漏掉 **ICAD（免標籤 conformal anomaly p-value）**；且 **EnbPI=approximate+需 stationarity、ACI=long-run+需線上 label**，re-entry 非穩態/無線上標籤下**保證失效** |
| C4 | H3 只說「無乾淨保證」 | 更狠：**多方向並存時 RBC 自身仍 smear**→map 的「嚴格消 smearing」**為假** |
| C5 | H4 用 MMDAgg 當「成本已解」 | MMDAgg 只免 **bandwidth 調參**，**不免 permutation 成本**（仍 O(B·n²)×kernel 數）|
| C6 | H7 降為🟢「固定 seed 即可」 | 升🔴：固定 seed＝reproducibility≠statistical determinism≠有效 type-I 控制；近門檻 p-value 有 ±%抖動（Pmin=1/(B+1)）|
| C7 | H8「KS 被 MMD 1D 特例涵蓋」 | 數學錯：KS(sup-CDF)≠1D MMD(mean-embedding)；KS 應**保留為廉價 1D first-pass** |

## 3. 「雙方都漏」的新盲點（紅隊獨立發現，map 與我皆未談）

### 統計層（R1）
| # | 盲點 | 衝擊 | 處置 |
|---|---|---|---|
| N1 🔴 | **檢定力公式張冠李戴**：`n≈2(z+z)²/δ²` 是**單變量均值位移**公式，**不描述 covariance/relationship 漂移**的檢定力 | 我把它當「硬限制」引用是錯的 | 改用 **TEP 上模擬 relationship-drift 的 power curve** 實證下限 |
| N2 🔴 | **全鏈無多重比較校正（FWER 膨脹）**：多 detector×多 permutation 各自 α | **破壞 DoD 第1條「golden-A 維持低分」**（健康期也誤報）| 單一融合分數＋單一閾值為唯一決策點（各 detector 當特徵），或 Holm/BH |
| N3 | **PCA 分數空間 permutation 的 exchangeability** | 不凍結 PCA → null 偏樂觀、p-value 虛低 | PCA/DPCA/SFA 在 golden-A fit 後**凍結**，permutation 只重排標籤；TEP 上驗 null type-I≈α |
| N4 | **自相關雙重破壞**：F/χ² 控制限低估＋iid permutation null 過窄 | 連續製程誤報率上升 | 控制限用 block-bootstrap/KDE；改 **block-permutation** 保短程相依 |
| N5 | **漂移量級不可跨段/跨核比較**：Sinkhorn/MMD 值依 ε、核、標準化 | 直接比大小誤導 | 量級先對 **golden-A null 標準化**(z-score)再跨段比 |
| N6 | **Health Index 0–1 融合的單調性/校準未定義** | DoD 三條無法保證 | 各分量先轉**對 golden-A null 的尾機率**再加權；TEP 校準權重並驗單調(Rule 9) |

### 落地層（R2）
| # | 盲點 | 處置 |
|---|---|---|
| D1 | **超參數總帳爆炸**(DPCA-lag+penalty+bandwidth+ε+α+B+多 random_state)，無統計團隊的廠端 own 不了 | 單一 config＋TEP 掃描預設＋「勿動除非」說明 |
| D2 | **A/B oracle 是合成 pyTEP（循環論證）** | 正式採用門檻**綁真實集(PRONTO/Gas)不退化** |
| D3 | **線上節拍預算從未量化**(Rule 6) | dev_plan 補 NFR：窗大小/節拍上限/各指標 per-window 時間預算/fallback |
| D4 | **失效降級未設計** | fallback 階梯：CP→GSI、MMD→KS、Sinkhorn→1D-Wasserstein，UI 標「降級模式」 |
| D5 | **可解釋對象錯位**：工程師要「嚴重度帶＋肇因感測器」，非 MMD/p-value 黑話 | UI 數學量當 tooltip，不當主訊息 |
| D6 | **rollback 與 RNG 衝突**：換 seed 致偽 regression→誤觸 doom-loop rollback | 含 RNG 測試**鎖 seed＋容忍帶斷言**(非點值)，CI 固定 seed 矩陣 |
| D7 | FastMCD 含隨機子集抽樣 → 我 H7 歸「本身確定性」不精確 | 固定 `random_state`、顯式 `support_fraction` |
| D8 | ruptures **未真消手刻規則**(penalty＋後置穩態 gate＝仍 2 超參) | 坦承簡化幅度，penalty 用 TEP 掃描定值 |

## 4. 對帳後的「淨設計」更新（取代 audit C 段）

- **L4 漂移**：**KS-on-PCA-score 廉價 1D first-pass → 觸發/需多維才升 MMD**；量級**先用解析 1D-Wasserstein on PCA-score**（無 ε），Sinkhorn 留待真需多維 OT 幾何；PSI **僅供溝通、不參與顯著性**；**全部對 golden-A null 標準化**；**block-permutation＋凍結模型**；**單一融合決策點＋FWER 控制**。
- **可信度**：GSI/T²/SFA 擔無標籤可信度；**ICAD（免標籤 conformal p-value）與 GSI 並列比較**；split-CP 僅在累積足夠 lab-Y 後上線（定最小 calibration 門檻）；**時序 CP 不宣稱保證**（re-entry 破前提）。
- **診斷**：RBC replace，但**「嚴格消 smearing」降級為「消單故障 smearing、多方向殘留」**，UI 標「定位非因果」。
- **L2**：DPCA 加 **n≥10·p(l+1) 硬 gate**，不足退靜態 PCA 並 surface；控制限對自相關用 block-bootstrap/KDE。
- **確定性合規**：所有含 RNG（permutation/CP ensemble/FastMCD）鎖 seed＋容忍帶；**優先解析門檻**；審計記錄 B 與 seed。
- **驗證**：power 下限改 **TEP 模擬 relationship-drift power curve**（非均值公式）；A/B 綁真實集、設預算上限；Health Index 融合先標準化再校準權重、驗單調。
- **方法論**：現代法皆 candidates，經典保留為 baseline 與 fallback。

## 5. 把握度與殘留（Rule 12）
- **R3 文獻**：15 筆關鍵文獻零捏造零 NOT FOUND；F1/F2/F3 DOI 全成立；殘留 5 筆 NOT VERIFIED 已補正式 DOI；**抓到我一處錯誤**：Spatio-temporal LSTM 2023 期刊非 Control Eng. Pract.，實為 *Engineering Applications of AI*（DOI 10.1016/j.engappai.2023.106847）。
- **未逐字驗證**：Genevay Thm 3 式子取自 ar5iv 鏡像（非 PMLR 原頁逐字）；ICAD 原始文獻（Laxhammar & Falkman）僅綜述間接確認。
- **理論常識未單篇直證**：FWER 膨脹、自相關對控制限影響、均值功效公式不適用協方差漂移——標準統計推論。
- **硬限制（三方一致）**：少量點受檢定力下限約束，地端冷啟動受**資料累積時間**約束，非演算法可解。

## 6. 元結論
派紅隊是對的：自審抓到表層（無捏造、無方向錯），但**6/11 條修對一半、且漏掉 N1–N6/D1–D8 共 14 個雙方盲點**——其中 **N2（FWER 破壞 DoD）、N1（功效公式用錯）、H7（確定性誤判）** 是會實際影響正確性的硬傷。**這些必須在回填三份設計文件時一併納入。**
