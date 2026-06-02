# Red Team — 地端落地可行性對抗審查（deployment red team）

> 日期 2026-06-02 · 視角：**地端產業落地（on-prem deployment）可行性**
> 對象：`modernization_map.md` 的 Phase-1 方法（DPCA/RBC/FastMCD/ruptures/split-CP/MMD/Sinkhorn）+ `modernization_audit.md` 的 F1–F3、H1–H8、C 段「淨設計結論」
> 立場：懷疑、不信任既有結論、自己重推。新主張附真實 DOI/URL；查不到標 **NOT FOUND**。
> 落地脈絡（已讀 `requirements_spec.md`/`functional_design.md`/`development_plan.md`）：FastAPI+Dash、地端原生 venv、單機離線、TEP+penicillin、Y 標籤稀少、確定性合規（Rule 5）、線上運算上限（Rule 6）、維運團隊須能調參與解釋。

---

## 0. 紅隊核心命題（TL;DR）

audit 把現代化建議從「為新而換」收斂到「證據驅動 A/B」，方向正確。但 audit 仍在**三個落地維度系統性低估成本**：

1. **確定性 ≠ 可重現的審計合規**。audit 的 H7 說「固定 seed 即確定性」——這是把 *reproducibility*（同 seed 同輸出）誤當成 *statistical determinism*（同輸入唯一正解）。固定 seed 只凍結了一個有雜訊估計子的單次抽樣，p-value 的 Monte Carlo 變異仍在；換個合法 seed，告警/不告警可能翻面。對需要對稽核解釋「為何此 run 判飄移」的地端產業，這是**可追溯性破口**，不是綠勾。
2. **丟掉 KS 是淨負債，不是淨升級**。KS 在 1D-on-PCA-score 上有解析 p-value、零 permutation、零調參。換 MMD 後每窗多出 `O(B·n²)` permutation + bandwidth/kernel 選擇 + seed 治理，全壓到**沒有統計博士的維運團隊**身上。audit H4/H8 承認 MMD 非全面碾壓，卻仍讓 KS「退場」——落地上應是 **MMD augment、KS 保留為廉價 1D 哨兵**。
3. **「證據驅動 A/B」(H2) 沒有出口條件**。要求「全部 candidates 須在 TEP ground-truth A/B 證明改善才納入」在方法論上無懈可擊，但實務上 ground-truth 主要靠 pyTEP 自生（`requirements_spec.md` §5），**A/B 的裁判本身是未驗證的合成 oracle**；若無「A/B 預算上限 + 預設採用基線」，H2 會把 MVP 拖進無限 benchmark 迴圈，違反 Rule 2/Rule 4 的「先跑通最小鏈」。

---

## 1. 原始建議落地漏洞表（Phase-1 方法 × 地端五約束）

約束：① 地端單機 ② 資料/標籤有限 ③ 確定性合規 ④ 可解釋 ⑤ 線上運算上限。

| 方法 | 落地漏洞（紅隊重推） | 命中約束 | 嚴重度 | 落地處置建議 |
|---|---|---|---|---|
| **MMD / MMDAgg** | permutation/wild bootstrap 每窗 `O(B·n²)`（典型 B=200–1000）；MMDAgg 是**多 bandwidth 聚合 → 成本再乘上 kernel 數**，非「免調參免成本」。MMDAgg 解的是 bandwidth 選擇，**沒解掉 permutation 成本**（Schrab 2023 仍用 permutation/wild bootstrap 定門檻）。p-value 有 Monte Carlo 變異，固定 seed 只凍結單次抽樣。 | ②③④⑤ | 🔴 | MMD 作 augment；線上路徑限 `n≤` 數百、降採樣 PCA-score；permutation B 版本化並記錄；對工程師輸出「距離+嚴重度帶」而非裸 p-value |
| **Sinkhorn divergence** | audit F2 已釘 `1/√n` 只在大 ε 成立、且大 ε 犧牲 OT 幾何——但**落地更痛的是 ε 變成第二個 bandwidth 級超參**，且 `O(n²/ε)` 在小 ε（要幾何保真）時迭代數爆增。維運要同時調 MMD-bandwidth + Sinkhorn-ε，認知負擔倍增。 | ④⑤ | 🟡 | 量級指標可先用**精確 1D-Wasserstein on PCA-score**（解析、無 ε、無迭代）；Sinkhorn 留待真需多維 OT 幾何時 |
| **split-CP（可信度）** | calibration set 需**有標籤 Y**，但專案前提 Y 稀少（FR-3、§7）。小 calibration 下 empirical coverage 分佈很寬，單一 split 可能遠低於名目（已查證，見 §5）。要 α=0.1 且「95% 把握達 90% coverage」級別保證，calibration 需數百–上千筆有效樣本——**地端冷啟動期根本湊不到**。 | ②③④ | 🔴 | 採 audit H1 的修正（GSI/T² 擔無標籤可信度，CP 僅在累積足夠 lab-Y 後上線）；明訂 CP 上線的最小 calibration 門檻並版本化 |
| **DPCA** | 維度 `p→p(l+1)`（audit H5 已標）。落地真痛點：golden-A 在「換線後第一段 A」**本來樣本就少**（re-entry 期是重點監看對象），lag 堆疊使 `n/p` 進一步惡化 → 協方差奇異、控制限不穩。 | ② | 🟡 | lag order 保守（l=1–2）；以 `n≥10·p(l+1)` 為硬下限 gate，不足則退回靜態 PCA 並 surface |
| **RBC** | 純線性代數、`O(m)`、共用 PCA——**落地幾乎無漏洞**，紅隊背書。唯一注意：audit H3 對「單感測器保證 ≠ 多變量關係根因」的界定要寫進 UI，避免工程師把 RBC 長條誤讀成因果根因。 | ④ | 🟢 | 直接 replace；UI 標注「relational drift 時 RBC 為定位非因果」 |
| **FastMCD** | 統計成熟、sklearn `MinCovDet` 一行替換——但 **FastMCD 內部有隨機子集抽樣（C-steps 起點隨機）**，非完全確定性，需固定 `random_state`。audit 把它歸在「本身確定性」（H7 表述）**略不精確**。 | ③ | 🟢 | 固定 `random_state` 並版本化；`support_fraction` 顯式設定不靠預設 |
| **ruptures (PELT)** | PELT 本身 DP 確定性、近線性——落地穩。真痛點是 **penalty 超參無通解**，且 audit C 段自己承認「ruptures 給邊界，仍需 steady/transition 標籤準則」→ 等於**沒真的消掉手刻規則**，只是把「window 長度啟發式」換成「penalty + 穩態判定準則」兩個超參。淨簡化幅度被 map 高估。 | ④ | 🟡 | penalty 用 TEP ground-truth 掃描定值並版本化；坦承 SSD 規則未被完全取代，是「penalty + 後置穩態 gate」 |

---

## 2. audit-the-audit 裁決表（F1–F3、H1–H8）

判準：從**地端落地**視角，audit 該條結論是否站得住。✅=對且落地友善 / ⚠️=方向對但低估或漏一塊 / ❌=過度或誤導。

| 條 | audit 主張 | 裁決 | 紅隊理由（落地視角） |
|---|---|---|---|
| **F1** | RI DOI 以 `.914373` 為準，`.914388` 錯 | ✅ | 純事實校正，與落地無關但正確；維持。 |
| **F2** | Sinkhorn `1/√n` 僅大 ε 成立、與保幾何 trade-off | ✅ | 紅隊認同且**加碼**：落地上 ε 是新增超參，`O(n²/ε)` 小 ε 迭代爆增（§1）。audit 講對了統計面，漏了**運維調參面**。 |
| **F3** | Energy distance = MMD 特例，從候選移除 | ✅ | 正確去重，減一個維運選項，落地友善。 |
| **H1** | CP 不整碗取代 RI；GSI 擔無標籤可信度，CP 僅補有 lab-Y 段 | ✅ | **這是 audit 最關鍵且最對的落地修正**。直接解掉「Y 稀少→CP 無米可炊」。紅隊強烈背書，並補：須明訂 CP 上線的**最小 calibration 門檻**（§5）。 |
| **H2** | 改證據驅動 A/B，「證明改善才採用」 | ⚠️ | 方法論對，**落地缺出口條件**：A/B 的 oracle 是 pyTEP 合成 ground-truth（本身未獨立驗證）；無「A/B 預算上限 + 預設基線」會無限拖延 MVP。應補：每 candidate A/B ≤ N 次、逾時則保留經典基線、現代法降級為 P2。 |
| **H3** | RBC 單感測器保證 ≠ 多變量關係根因；「RBC高+ISI低」是啟發式非定理 | ✅ | 落地關鍵誠實。紅隊補：此界定**必須上 UI**，否則工程師把 RBC 當因果根因是可預期的誤用。 |
| **H4** | MMD 非「嚴格優於 KS」，用 MMDAgg 免調參 | ⚠️ | 前半對。後半**誤導**：MMDAgg 免的是 bandwidth 調參，**沒免 permutation 成本**（已查證 Schrab 2023）。audit 用 MMDAgg 當「成本顧慮已解」的擋箭牌，低估維運負擔。 |
| **H5** | DPCA 非零成本，維度膨脹要選 lag | ✅ | 對。紅隊補：在 **re-entry 小樣本期**這個惡化被放大，需 `n/p` 硬 gate，audit 只說「需更多資料」未給門檻。 |
| **H6** | SFA 助益判準3但非完整解，仍需 L2/L4 對 golden-A 收尾 | ✅ | 落地誠實，且 SFA 在 P2，不 gate MVP。維持。 |
| **H7** | permutation/EnbPI bootstrap「固定 seed 才確定性」 | ❌ | **紅隊最強烈反對**。固定 seed 給的是 *reproducibility*（同 seed 重跑同值），**不是 statistical determinism**。p-value 仍有 Monte Carlo 變異（Pmin=1/(B+1)，近門檻處 ±%級抖動，已查證）；換合法 seed 告警可翻面。對需向稽核解釋「此 run 為何判飄移」的地端產業，**固定 seed 掩蓋了結論對 RNG 的脆弱性**。Rule 5「code 能算的就用 code 算」精神上偏好**解析門檻（KS/T²/SPE/精確 1D-Wasserstein）**，permutation 是不得已。audit 把這條降到 🟢 嚴重度是**落地誤判**。 |
| **H8** | L4 收斂為 MMD+Sinkhorn+PSI，KS 退場 | ⚠️ | 收斂方向對，但**「KS 退場」過度**。KS-on-PCA-score 解析 p-value、零 permutation、零調參、零 seed 治理，是最廉價的 1D 哨兵。落地應 **KS 保留為快速 first-pass，MMD 僅在 KS 觸發或需多維/關係敏感度時啟動**（成本分層），而非全砍。 |

**裁決統計**：✅×5（F1,F2,F3,H1,H3,H5,H6 中的對齊項）/ ⚠️×3（H2,H4,H8）/ ❌×1（H7）。
> audit 的**概念面（H1/H3/H5/H6）落地友善且誠實**；**成本與合規面（H4/H7/H8）系統性低估維運與審計負擔**。

---

## 3. 雙方都漏的落地盲點（map 與 audit 皆未談）

| # | 盲點 | 為何重要（地端產業） | 處置 |
|---|---|---|---|
| **B1** | **超參數爆炸的維運總帳** | map/audit 逐方法看超參，沒人算**總和**：DPCA-lag + ruptures-penalty + MMD-bandwidth(或 MMDAgg kernel set) + Sinkhorn-ε + CP-α + permutation-B + 多個 random_state。一個沒有統計團隊的廠端維運，**根本無法 own 這套**。經典鏈（KS+PCA-k+Wasserstein）超參數量級小一截。 | 出**單一 config 檔 + 每參數的 TEP 掃描預設值 + 「不要動除非…」說明**；非預設值才需人介入 |
| **B2** | **A/B 的 oracle 是合成資料，未交叉驗證落地有效性** | H2 要求 A/B 證明，但主 ground-truth 是 pyTEP 自生 drift（`requirements_spec.md` §5）。**用合成 oracle 證明現代法贏，再宣稱地端有效**，是循環論證。PRONTO/Gas-Drift 真實集才是落地代理。 | A/B 的「正式採用」門檻應**綁真實集（PRONTO/Gas-Drift）至少不退化**，非只看 pyTEP |
| **B3** | **permutation/Sinkhorn 的線上節拍預算從未被量化** | Rule 6 要求「超節拍 surface」，但無人給**目標節拍數字**（每窗幾秒？窗多長？n 多大？）。沒有預算就無法判斷 MMD permutation 是否扛得住。 | 在 `development_plan.md` 補一條 NFR：定義線上窗大小、節拍上限、各 L4 指標的 per-window 時間預算與 fallback |
| **B4** | **CP/MMD 失效時的 graceful degradation 未設計** | 地端 calibration 不足 → CP 無法上線；permutation 超時 → MMD 無 p-value。系統該怎麼**降級**而非崩潰或假裝有結果？ | 設計 fallback 階梯：CP→GSI、MMD→KS、Sinkhorn→1D-Wasserstein，並在 UI 標示「降級模式」 |
| **B5** | **可解釋性的對象錯位** | map 比較 MMD/Sinkhorn vs T²/SPE 的「數學可解釋性」，但落地受眾是**製程工程師**。T²/SPE/contribution/Wasserstein 有物理直覺（哪個感測器、漂多遠）；MMD-statistic、Sinkhorn-divergence、p-value **對工程師是黑話**。 | UI 一律把 L4 翻成「漂移嚴重度帶 + 肇因感測器（RBC）」，數學量當 tooltip，不當主訊息 |
| **B6** | **last-green / rollback 與隨機性的衝突** | CLAUDE.md 要求「regression（之前過現在不過）自動 rollback」。但 permutation/CP 含 RNG，**同一 commit 換 seed 可能讓某測試時過時不過**，觸發偽 regression、誤判 doom loop。 | 所有含 RNG 的測試**必須鎖 seed 且斷言容忍帶**（非點值）；CI 用固定 seed 矩陣，避免偽 regression |

---

## 4. 把握度與 NOT FOUND

**高把握（已查證 primary source）**
- MMDAgg 仍用 permutation/wild bootstrap 定門檻、解的是 bandwidth 非 permutation 成本 — Schrab et al. 2023, *JMLR* 24(194), [arXiv:2110.15073](https://arxiv.org/abs/2110.15073)。
- split-CP 小樣本下 empirical coverage 分佈寬、單 split 可遠低於名目 — [arXiv:2303.02770](https://arxiv.org/pdf/2303.02770)（universal distribution of empirical coverage）；小資料 coverage 變異 [arXiv:2509.15349](https://arxiv.org/html/2509.15349v1)。
- CP coverage 服從 Beta/Beta-Binomial，達標需明確 calibration 規模 — Angelopoulos & Bates 2021 tutorial, [arXiv:2107.07511](https://arxiv.org/html/2107.07511v6)。
- permutation p-value 有 Monte Carlo 變異、Pmin=1/(B+1)、固定 seed 只給 reproducibility 非消除變異 — [arXiv:1603.05766](https://arxiv.org/pdf/1603.05766)（permutation p-value never zero）。
- audit F2/F3 的 Sinkhorn/Energy-distance 校正 — 沿用 audit 已驗證的 Genevay 2019、Sejdinovic 2013（未重查，信任 audit）。

**中把握（推論，非單一文獻直證）**
- FastMCD `MinCovDet` 含隨機子集抽樣需固定 `random_state`：屬 sklearn 實作行為與 FastMCD C-step 設計常識，未逐字查證官方文件 → 落地前以 sklearn 文件確認 `random_state` 參數語意。
- DPCA 在 re-entry 小樣本期惡化 `n/p`：邏輯推論，無針對「AVM-continuous re-entry」的直接文獻（本專案 research gap，`requirements_spec.md` §7 已自承）。

**NOT FOUND / 未查證**
- 「化工製程工程師對 MMD/Sinkhorn vs T²/SPE 可解釋性偏好」的實證調查 — **NOT FOUND**（B5 為紅隊推論，非文獻結論）。
- 針對「permutation-based drift test 在地端即時節拍下的 per-window 延遲 benchmark」 — **NOT FOUND**（B3 即因此存在）。
- audit 殘留的 Phase-2/3 DOI（工業時序 CP 2025 IEEE 10870871 等）紅隊未重查，沿用 audit 的 NOT VERIFIED 標記，不 gate Phase-1。

**不可被修掉的硬限制（與 audit D 段一致）**：少量點偵測受統計檢定力下限約束；MMD/Sinkhorn/CP 都不能「用 5 筆抓 0.2σ」。地端冷啟動期的根本約束是**資料累積時間**，非演算法選擇。

---

> **下一步**
> - 將 H7 從 🟢 升級為 🔴 並改寫為「permutation/CP 含 RNG，需鎖 seed＋容忍帶斷言＋審計記錄 B 與 seed，且優先用解析門檻」。
> - L4 改「KS 廉價 1D 哨兵 → MMD 升級偵測」成本分層，撤回「KS 退場」。
> - 在 `development_plan.md` 補 B3（線上節拍預算 NFR）與 H2 出口條件（A/B 上限＋真實集綁定＋預設基線）。
