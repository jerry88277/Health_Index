# 需求規格書 — Health_Index MVP

> 版本 **v0.2**（納入自我審核 + 三方紅隊對帳修正）· 日期 2026-06-02
> 變更依據：`modernization_audit.md`、`redteam_reconciliation.md`（N1–N6 統計盲點、D1–D8 落地盲點、C1–C7 自審過度修正）
> 配套：`functional_design.md`、`development_plan.md`、`avm_metrics_definitions.md`、`continuous_*`、`literature_crossref.md`
> 規範：專案 `CLAUDE.md`（含「審核獨立性」）

---

## 0. 術語小辭典（零基礎可讀）
| 術語 | 一句話 |
|---|---|
| T²／SPE | PCA 兩哨兵：T²＝在已知正常關係內偏多遠；**SPE＝偏離正常關係結構多遠（隱性飄移主訊號）** |
| GSI | 全空間 Mahalanobis 相似度，問「這筆 X 像不像歷史正常」——**免 Y 標籤** |
| RI | AVM 可信度（兩模型預測分佈重疊面積）|
| DQI_x | AVM 資料效度閘（PCA 特徵空間 Euclidean 距離）|
| Conformal Prediction (CP) | 有覆蓋保證的預測區間；**split-CP 需有標籤 Y 的校準集** |
| ICAD | 免標籤 conformal 異常 p-value，只需乾淨參考集 |
| MMD | 核方法兩群分佈差，多維、抓關係型漂移，需 permutation＋選 kernel |
| KS | 兩 CDF 最大落差，1D、**有解析 p-value、零調參**（廉價哨兵）|
| PSI | 分箱漂移指標（＝對稱 KL），少量點脆，僅供溝通 |
| Wasserstein / Sinkhorn | 推土機距離 / 加熵正則的快速版（ε 越小越保幾何但越貴）|
| RBC | 改良肇因定位，消單故障 smearing；**多方向漂移仍殘留 smearing** |
| DPCA／SFA／CVA | PCA 動態升級：補時間落後／分「正常變動 vs 動態異常」／抓緩起隱性故障 |
| FastMCD | 抗離群協方差估計（需固定 random_state）|
| ruptures (PELT) | 變點偵測切穩態段 |
| FWER | 多重檢定的家族誤報率（多 detector 併判必須控制）|
| golden-A / campaign / re-entry | 凍結健康基準／同產品連續段／換線或維修後第一段 A |

## 1. 目的與範圍
取鄭芳田 AVM 精神，建**泛化工連續製程**的隱性飄移偵測：同產線 A→換 B/C 或維修→回 A 時，偵測 A 是否發生**隱性多變量飄移**（每變數在規格內、僅多變量關係或 X→Y 映射偏移），並以虛擬量測 Ŷ 取代破壞性抽樣。

**In Scope（MVP）**：連續型資料；L1–L4＋Health Index 融合＋re-entry 觸發；連續製程前處理（穩態切段、transition/maintenance 閘、X→Y 對齊）；地端 FastAPI+Dash、原生 venv；跨資料集 cross-validation。
**Out（後續）**：L5 批次 DTW；learned meta-model 融合；雲端/多租戶/登入；全自動線上重訓（MVP 僅手動＋凍結 golden-A）。

## 2. 利害關係人
製程工程師（看 Health Index 時間軸＋肇因感測器）／資料科學家（可解釋、可驗證、可泛化）／C-level（能否以 Ŷ 取代抽樣）。

## 3. 功能需求 (FR)

| 編號 | 需求 | 對應 | 優先 |
|---|---|---|---|
| FR-1 | adapter 載入連續資料 → 統一契約（原始 5 類欄位）| 資料 | P0 |
| FR-2 | **ruptures(PELT) 切穩態段＋後置穩態判定準則**；transition/maintenance 標記排除於 A baseline（坦承：penalty＋穩態 gate 仍為 2 超參，非全消手刻規則）| 前處理 | P0 |
| FR-3 | X→Y 延遲估計，稀疏延遲 Y 對齊回 X(t−d) | 前處理 | P1 |
| FR-4 | L1：sanity check（NaN/凍結/超界）＋ **FastMCD 抗污染協方差**（固定 random_state）＋ DQI_x | L1 | P0 |
| FR-5 | L2：golden-A 訓練 PCA→GSI(D²/p)/T²/SPE＋控制限；**控制限對自相關用 block-bootstrap/KDE**；診斷用 **RBC**（標註「單故障定位；多變量關係漂移為**定位非因果**、仍殘留 smearing」）；ISI 僅當「關係型 vs 顯性」輔助分類 | L2 | P0 |
| FR-6 | L3：軟測量 **GPR** 預測 Ŷ；**可信度分兩路**——(a) 無標籤：GSI/SFA／**ICAD**（免標籤 conformal p-value）；(b) 有 lab-Y 累積足量後：**split-CP**（定最小 calibration 門檻）。**時序 CP(EnbPI/ACI) 不宣稱覆蓋保證**（re-entry 非穩態/無線上標籤破其前提）；RI 留相容對照 | L3 | P0 |
| FR-7 | L4：**KS-on-PCA-score 廉價 1D first-pass → 觸發或需多維時升 MMD/MMDAgg**；量級用**解析 1D-Wasserstein**（Sinkhorn 留待真需多維 OT 幾何，ε 須 TEP 掃描）；PSI 僅供溝通不參與顯著性；**所有指標對 golden-A null 標準化後才跨段比較**；**block-permutation＋凍結模型**校準 | L4 | P1 |
| FR-8 | Health Index：各分量先轉**對 golden-A null 的尾機率/標準化分數**再加權成 0–1；**單一融合分數為唯一告警決策點**（各 detector 當特徵不各自宣告）；re-entry 期重點監看 | 融合/觸發 | P0 |
| FR-9 | REST API：選資料集/建凍結 baseline/執行分析/取 Health Index 時間軸/contribution/crossval | 後端 | P0 |
| FR-10 | Dash 前端：HI 時間軸、T²/SPE/GSI、Ŷ vs Y、**RBC 肇因感測器、漂移嚴重度帶**（數學量當 tooltip）、降級模式標示 | 前端 | P0 |
| FR-11 | cross-validation runner：同邏輯多資料集驗證 | 驗證 | P0 |
| FR-12 | golden-A 凍結管理（is_golden_A），禁自適應吸收飄移 | 資料/模型 | P0 |
| FR-13 | **失效降級階梯**：CP→GSI、MMD→KS、Sinkhorn→1D-Wasserstein；UI 標「降級模式」不崩潰/不假裝有結果 | 全鏈 | P0 |

## 4. 非功能需求 (NFR)
| 編號 | 需求 |
|---|---|
| NFR-1 確定性 | 偵測為確定性數學，**runtime 不呼叫 LLM**；含 RNG 者（permutation/CP ensemble/FastMCD）**鎖 seed＋容忍帶斷言（非點值）＋審計記錄 B 與 seed**；**優先解析門檻**（KS/T²/SPE/1D-Wasserstein），permutation 為不得已。註：固定 seed＝可重現，**≠統計確定性**（紅隊 H7）|
| NFR-2 type-I 控制 | **全鏈單一融合決策點＋FWER 控制**（各 detector 不各自宣告）；TEP 上驗 golden-A 期誤報率與 null type-I≈α（紅隊 N2/N3）|
| NFR-3 地端 | 單機離線、僅 Python+venv |
| NFR-4 線上節拍 | **定義線上窗大小、節拍上限、各 L4 指標 per-window 時間預算與 fallback**；重指標（MMD permutation O(B·n²)、Sinkhorn O(n²/ε)）超節拍即 surface 並降級（紅隊 D3）|
| NFR-5 可重現 | 固定種子、版本化超參（lag/penalty/bandwidth/ε/α/B），同輸入同輸出 |
| NFR-6 可解釋 | 經 RBC 反解到感測器；UI 以「嚴重度帶＋肇因感測器」為主訊息（紅隊 D5）|
| NFR-7 授權 | 僅開放授權資料集（CC BY/BSD/MIT）|
| NFR-8 測試 | 編碼 WHY；含「index 停止偵測隱性飄移即失敗」的測試；**RNG 測試鎖 seed＋容忍帶（防偽 regression 觸發 rollback）**（紅隊 D6）|
| NFR-9 超參治理 | **單一 config 檔**收全部超參＋TEP 掃描預設＋「勿動除非」說明（紅隊 D1）|

## 5. 資料需求（cross-validation）
| 角色 | 資料集 | 授權 |
|---|---|---|
| 錨點（多 mode 模擬）| Extended TEP (DOI 10.11583/DTU.13385936) + pyTEP (BSD-3) | CC BY 4.0 |
| 真實工廠互補 | PRONTO/Cranfield TPFF (DOI 10.5281/zenodo.1341583) | CC BY 4.0 |
| 純 drift 壓測 | UCI Gas Sensor Array Drift (DOI 10.24432/C5RP6W) | CC BY 4.0 |

- golden-A＝某穩態 mode 乾淨良品段（凍結）。
- **主 ground-truth 由 pyTEP 生成**；但**正式採用門檻綁真實集（PRONTO/Gas）不退化**，避免「用合成 oracle 自證」的循環（紅隊 D2）。

## 6. 驗收判準 (AC)
1. **AC-1** golden-A 期間 Health Index 低分。
2. **AC-2** 隱性多變量飄移**早於單變數 SPC** 升高；下限以 **TEP 模擬 relationship-drift power curve 實證**（不套單變量均值位移公式，紅隊 N1）。
3. **AC-3** 區分「乾淨換線回歸」vs「殘留飄移」。
4. **AC-4（泛化）** 同邏輯在 ≥2 資料集滿足 AC-1~3，**且於真實集不退化**。
5. **AC-5（全棧）** 地端依手冊一次拉起前後端，前端呈現 HI 時間軸與 RBC 肇因。
6. **AC-6（type-I）** golden-A 期全鏈誤報率在校正後 ≤ 目標 α（驗 N2）。

## 7. 假設與限制
| 假設/限制 | 處置 |
|---|---|
| AVM-continuous 原生落地無前例（research gap）| 標原創組合，cross-validation 佐證 |
| 線性假設、X→Y 延遲局部平穩 | MVP 接受；非線性/自適應列後續 |
| golden-A 凍結 | 永久製程改變由人工＋DQI_y 觸發 re-baseline |
| **少量點檢定力下限**（硬限制）| MMD/Sinkhorn/CP 不能「5 筆抓 0.2σ」；地端冷啟動受**資料累積時間**約束，非演算法可解 |
| **時序 CP 保證前提**在 re-entry 失效 | 不宣稱保證，僅批次校準 |

## 變更紀錄
- v0.2：納入三方紅隊修正——FR-5(RBC caveat)、FR-6(GSI/ICAD/CP 分路)、FR-7(KS first-pass/1D-Wasserstein/標準化/block-permutation)、FR-8(單一決策點)、FR-13(降級)、NFR-1/2/4/8/9(seed+容忍帶/FWER/節拍/超參治理)、AC-2/4/6(power curve/真實集/type-I)。
