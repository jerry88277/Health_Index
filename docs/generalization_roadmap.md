# 泛化路線圖：X&Y 健康指標 → 多連續製程 + 軟量測資料集

> 目的：把目前以 synthetic/TEP 為主的 X&Y 健康指標，泛化到**任意多變量連續製程 + 軟量測**資料集
> （不限化工）。本檔以**第一性原理 + MECE** 盤點缺口，附決策對比表與可平行開發的優先級路線。
> 建立：2026-06-10（git 時間為權威）。狀態圖例：`[ ]` 未開始 / `[/]` 進行中 / `[x]` 完成。

---

## 0. 第一性原理：管線分解

要讓框架對「任一條產線的 X（製程參數）+ Y（軟量測目標）」輸出可信健康指標，資料須流經：

```
攝入 Ingest → 契約 Contract → 前處理 Preprocess → 偵測 Detect(L1–L4 on X；L3+Y-MSPC on Y)
            → 融合 Fuse → 決策 Decide(HI / AC-6) → 評估 Evaluate(DoD)
```

**泛化缺口 = 任一階段目前對「特定資料集」寫死的假設。** 下節以此管線為 MECE 切分維度逐一盤點。

---

## 1. 現況盤點（grounded，附 file 證據）

| 元件 | 現況 | 泛化阻礙 |
|---|---|---|
| 契約 `interface.py` | `ProcessDataset(frame, x_columns, name)` + `validate_raw`；`RAW_REQUIRED` 含 **Y_VALUE/Y_TIMESTAMP/GRADE_LABEL（皆必填）** | 無 Y / 無 grade 的資料集須手動填 NaN / 常數（`uci_gas_drift.py:131`）——可接受但無 helper |
| Adapter 層 | 4 個**各自為政**：`synthetic.generate`→`SyntheticGroundTruth`、`tep.generate`→`TEPGroundTruth`、`uci_gas_drift.load`→`GasDriftGroundTruth`、`indpensim.load`→`BatchDataset` | **無統一 `DatasetAdapter` 協定**；入口名不一（generate vs load）；**3 個重疊的 `*GroundTruth`**（golden_mask/x_columns/bounds 各自定義）→ 第 3 次重複，**抽象門檻已達** |
| 通用攝入 | **無**通用 CSV/DataFrame adapter | 新資料集**一律要寫 Python 模組**；無「給我一張表 + 欄位角色宣告 → ProcessDataset」的路徑 |
| Ground-truth | 每資料集 bespoke dataclass（欄位重疊） | 評估/驗證無法以統一介面消費任一資料集 |
| L1 DQI_x | FastMCD（`MinCovDet` 需 n>2p） | 高維（uci p=128，`real_set.py:9`）**跑不動**；無 PCA-score 降級路徑 |
| L3 軟量測 | GPR（O(n³)） | 大 n 不可擴展；**無 PLS/線性 fallback**（軟量測經典作法）；單一純量 Y（多 Y 走另一條 Y-MSPC） |
| L4 漂移 | permutation O(B·n²) | 大 batch 線上成本超標（`uci_gas_drift.py:21`）；已有 block-bootstrap（②）但成本未解 |
| 融合/門檻 | `config.py` 預設「須 TEP 校準」硬編 | **無 per-dataset 自動校準** 到目標 golden FPR |
| 評估 | `validation/real_set.py` bespoke `evaluate_gas_drift` | 每資料集手寫評估；**無統一 benchmark harness** 跑 DoD |

---

## 2. MECE 缺口分桶（互斥且窮盡）

> 每桶標：缺什麼、為何（第一性）、相依、可否平行。

### 桶 1 — 攝入與契約（**地基／關鍵路徑**）
- **缺**：(a) `DatasetAdapter` 協定（統一入口 `build() -> (ProcessDataset, GroundTruth)`）；
  (b) 通用 `dataframe_adapter`（任意表 + 欄位角色映射 → 契約，自動補常數 grade / NaN Y）；
  (c) 統一 `GroundTruth` 協定（`golden_mask` / `drift_mask`(opt) / `segment_bounds` / `x_columns`）。
- **為何**：沒有統一攝入與真值協定，「多資料集」永遠是 per-dataset 苦工；下游評估無法泛化消費。
- **相依**：無（地基）。**阻擋** 桶 6（評估）、部分桶 2/4。
- **平行**：(a)(c) 先行；(b) 依賴 (a)(c)。
- **Rule 3 注意**：**不動 `interface.py` 骨架**；新增協定/通用 adapter 為 domain 層**加法**，向後相容。

### 桶 2 — Y／軟量測健康（**X&Y 核心**）
- **缺**：(a) 可擴展軟量測（PLS／線性 fallback，大 n 與低 n/p 友善；多輸出 Y）；
  (b) **統一 Y 健康分數**（軟量測殘差健康 ⊕ Y 分布健康 Y-MSPC → 單一 0–1）；
  (c) X→Y 映射可信度（RI/CP）升為一級指標並入融合。
- **為何**：使用者明指「X&Y...軟量測」；現況 GPR 不可擴展、Y 健康分散在 `/softsensor` 與 `/yhealth`。
- **相依**：桶 1 的 Y 欄約定（多 Y 用 `yq_` 前綴，已存在於 tep）。**平行**：與桶 3/4 獨立。

### 桶 3 — 高維／規模穩健
- **缺**：(a) L1/L4 的 **PCA-score 降級路徑**（p≫n 或 n 大時自動降維再跑）；
  (b) 偵測器**適用性旗標**（不滿足前提時誠實降級/略過，非靜默錯誤，Rule 12）。
- **為何**：真實連續資料常高維（uci p=128）或長序列；現況超出線上成本即無法跑全鏈。
- **相依**：偵測器層。**平行**：與桶 2/4 獨立。

### 桶 4 — 前處理穩健
- **缺**：(a) 缺值/NaN 欄處理（真實資料有斷點）；(b) **無 grade/mode 時的 golden 自動挑選**
  （現況 golden 由真值 mask 給；通用資料集需「取前 X% 平穩段為 golden」啟發式）；(c) 非平穩基準（EWMA/recursive）。
- **為何**：通用攝入後資料更髒；golden 定義不能再靠 dataset-specific mask。
- **相依**：桶 1（攝入）。**平行**：(a) 可先行。

### 桶 5 — 融合與自動校準
- **缺**：per-dataset 校準程序——在 golden 上掃 `hi_alarm_threshold`/`fwer_alpha`/`fusion_weights` 命中目標 golden FPR。
- **為何**：`config` 預設值「須校準」；不同資料集尺度/維度不同，固定門檻不可移植。
- **相依**：偵測器（多已完成）。**平行**：晚期（需資料集就緒）。

### 桶 6 — 評估與 benchmark
- **缺**：統一 benchmark harness——消費 `GroundTruth` 協定，對 **N 個資料集**輸出 DoD 報表
  （golden 低分 / 隱性漂移早於單變數 SPC / 區分乾淨 vs 殘留）。
- **為何**：泛化的**證明**必須跨資料集可重現；現況 per-dataset 手寫。
- **相依**：桶 1（GroundTruth 協定）。**阻擋**：泛化 DoD 驗收。

---

## 3. 關鍵架構決策：統一 Adapter／GroundTruth 協定（2 方案對比）

> 決策性結論——依規範附 ≥2 方案 + 對比 + 選定理由 + 向後相容；落地前派紅隊複審。

| 方案 | A：Protocol（`typing.Protocol`，鴨子型別） | B：ABC 基底類別（`abc.ABC` 繼承） |
|---|---|---|
| 既有 adapter 改動 | **零**（既有 `generate/load` 回傳已符結構即視為合規） | 需改既有 adapter 繼承基底、改方法名 |
| 向後相容 | ✅ 完全（加法） | ⚠️ 須改 4 個既有 adapter |
| 強制性 | 弱（靜態檢查/文件約束） | 強（執行期繼承保證） |
| 樣板量 | 低 | 中 |
| 契合現況 | 高（adapter 已是自由函式 + dataclass） | 低（需重構為類別） |

**選定：A（Protocol）+ 一個輕量 `GroundTruth` dataclass（unify 欄位）+ 一個 `registry`（name→builder）。**
理由：Rule 3（不動骨架、加法）、Rule 2（最小重構）、Rule 11（沿用「自由函式 + dataclass」既定慣例）。
既有 `*GroundTruth` 可保留，新增 `to_common()` 轉換或讓 registry 包裝；不強迫立即重寫。
**向後相容**：既有 `tep.generate` 等入口不動；新增 `adapters.registry.build(name, **kw)` 與
`adapters.dataframe.from_frame(df, x_cols, ...)`；舊測試不受影響。

---

## 4. 優先級 + 可平行路線（critical path 粗體）

```
階段 0（地基，序列）         階段 1（可平行 3 路）              階段 2（收斂）
[1] DatasetAdapter 協定  ──┬─→ [2] PLS/線性軟量測 + 統一 Y 健康
+ 統一 GroundTruth        ├─→ [3] L1/L4 PCA-score 降級 + 適用性旗標
+ registry + 通用 adapter ├─→ [4] 缺值處理 + golden 自動挑選         ──→ [6] 跨資料集 benchmark
（**關鍵路徑**）          └────────────────────────────────────────→     harness + DoD 報表
                                                                  ──→ [5] per-dataset 自動校準
```

- **先做**：桶 1（解鎖一切）。**完成後 2/3/4 三路可平行**（彼此無相依，分屬 detector/Y/preprocess 不同模組）。
- **後做**：桶 6（需 1 的協定）、桶 5（需資料集 + 偵測器就緒）。
- **新資料集候選（非化工，含 Y 軟量測）**：
  - ✅ **發電廠 CCPP（已建，2138632）**：UCI #294，9568 列，X=AT/V/AP/RH、**真實連續 Y=PE 淨發電量**。
    註冊 `ccpp`（real，drift_mask=None）+ `ccpp_covert`（真實特徵基底注入隱性漂移：hub 欄部分置換去相關，
    marginal 精確保留→單變數 SPC 盲、SPE 0.01→0.46 抓到）。**§5 DoD #2「≥3 結構不同資料集含真實非化工 Y」達成**。
  - 待辦候選：半導體 SECOM、鋼鐵能耗、風機 SCADA（NOT VERIFIED，需逐筆查證可用性與授權）。

---

## 5. 泛化 DoD（驗收）
1. 任一符合協定的資料集，一行 `registry.build(name)` 即跑通全鏈（或誠實降級 + 旗標）。
2. benchmark harness 對 ≥3 個結構不同資料集（合成 / TEP / 一個真實非化工含 Y）輸出統一 DoD 報表。
3. 既有 synthetic/TEP/uci 全測試不退化（向後相容）。
4. 高維資料集（p≫n）不再因 L1/L4 前提不滿足而**靜默失敗**——降級並 surface。

---

## 6. 決策待人（僅在自行無法定奪時填；目前空）
- （無。架構決策已於 §3 自行定奪：方案 A，附理由與相容處理。）

---

## 7. 進度
- [x] §1–§6 規劃（本檔）— 2026-06-10
- [x] 桶 1：DatasetAdapter 協定 + 統一 GroundTruth + registry + 通用 dataframe adapter
      — 2026-06-10（merge，紅隊 ≥2 視角複審後修正 tep_tp 防呆/顯式 segment/數值 X 守門/eq=False）
- [x] 桶 2a：PLSSoftSensor + split-CP + scale-based selector（大 n/高維軟量測）— 2026-06-10（merge）
- [x] 桶 2b：YHealthIndex（映射健康 ⊕ 分布健康 → 單一 0–1 + y_flagged 安全網）— 2026-06-10（merge）
- [x] 桶 4：通用 adapter 缺值處理（fail-loud NaN + opt-in impute；誠實標『填補製造假陰性』）— 2026-06-10（merge）
- [x] 桶 6：跨資料集 DoD benchmark harness（synthetic/tep/tep_tp 統一通過）— 2026-06-10（merge）
- [x] 桶 3：L1 PCA-score 預降維（p≫n MinCovDet 靜默奇異 → 降維到 score 空間 + degraded_ 旗標）
      + L4 有效秩截斷（免 noise 維汙染 KS Bonferroni）— 2026-06-10（紅隊 ≥2 複審 → FIX-FIRST → 修正後 merge）
      · 誠實邊界：桶3 對 L1 是**數值良定義＋適用性旗標**，非提升 drift 鑑別力（Rule 12）
      · 紅隊修正：degraded_ 改發 `warnings.warn`（原為死旗標、無消費端＝名實不符的靜默，Rule 12）；
        修壞測試（L4 截斷不等式普遍為假、epsilon 吞噬惡化，違 Rule 9）；補 HealthIndex 端到端 p≫n 整合測試
      · **已知限制（NOT 桶3 範圍，紅隊揪出，列次桶候選）**：(1) **L2 T² 在 p≫n 仍脆弱**——`np.cov`+`eigh`
        近零特徵值以 floor 1e-12 相除致 noise 方向膨脹（主訊號 SPE 走殘差投影穩健、端到端不爆，但 T² 未硬化）；
        (2) **近共線感測器**（r≈1 重複欄）會讓 L4 `rank_<p`、行為非逐位元相容（重複欄不帶資訊，改變方向合理但
        宣稱須限定「良定義 full-rank」）；(3) L1 降維後 robust 餘裕較薄（support/維≈1.88，非奇異但中度病態）。
- [~] 桶 5：per-dataset 門檻自動校準 — **investigated → NOT WARRANTED**（2026-06-10，≥2 紅隊對抗複審
      皆 AGREE-NOT-WARRANTED）。固定 0.6 在 ≥9 種 golden（含真實 penicillin/半導體 + 仿射極端 + 病態分布）
      golden FPR≈0——HI 自正規化（仿射等變）→ 結構性寬 dead-zone。校準有 recall 收益但 hold-out FPR 代價
      0.62–0.75 不可接受；真實失效（indpensim 弱故障漏抓）屬**偵測力/可分離性**（桶3b）非門檻、且安全校準
      只能調低救不了。**改 ship**：`check_threshold_portability` 哨兵（只用 golden floor，逼近門檻則 warn，
      不改門檻）。詳 `docs/decision_threshold_calibration.md`。
- [~] 桶 3b（部分完成，2026-06-10，≥2 紅隊 FIX-FIRST → 修正後 merge）：
      · ✅ **benchmark 納 p≫n 案例**（`synthetic_pgn` n=80/p=128，registry + DoD specs）——泛化證明涵蓋
        高維 regime（原僅偵測器單元測試）。誠實邊界（紅隊 A）：DoD 由 L2 SPE+L4 驅動，**桶3 L1 降維對
        DoD pass/fail 無因果貢獻**（不降維時數字逐位元同），桶3 價值＝數值乾淨非 DoD 驅動。
      · ✅ **修 benchmark 高維 SPC bug**（紅隊 A 揪出）：原 spc_blind 取絕對『任一變數破 3σ』比例，p 大時
        被多重比較底噪主導（in-sample 實測 ~0.05–0.09）→ 量噪非訊。改扣 golden in-sample 底噪（低維不變、
        高維公平）。紅隊 B2 揪出我首版含恆真廢測 → 改為呼叫真實 evaluate_dataset 鎖住扣底噪行為。
      · ⏭ **未做（仍開放）**：L2 T² p≫n 硬化——**經診斷不需要**（T² 經 k 選擇只用真實成分、SPE 殘差穩健、
        is_anomaly 正確；僅 GSI reference 爆但不入決策且已文件化 → Rule 3 不修沒壞的）。偵測力/可分離性
        （indpensim faulty 漏抓）為**真開放問題**（需更強特徵/偵測器，研究級），列獨立待辦。
- [ ] 桶 3b-cont（研究級待辦）：偵測器高維 HI 壓縮 / 偵測力——indpensim golden(0.976) vs faulty(0.948)
      HI 重疊，無門檻可分離；屬偵測力非門檻，需更強特徵或 X→Y 軟測量殘差訊號補強。
- [ ] 待辦（非桶5）：indpensim 批次 `fwer_alarm` golden alarm≈0.30≫α=0.05，疑軌跡自相關使窗非 iid（與 L2
      block-aware 債同源）→ FWER 自相關校準延伸至批次。
