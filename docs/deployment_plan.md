# 交付與線上應用計畫：Health_Index → 產線部署

> 本檔為**交付工作的版本化真相**（repo 是唯一真相，對話 context 不算）。loop 依此推進。
> 建立：2026-06-15（git 時間為權威）。範圍決策見 §2「瓶子優先」。

---

## 1. 第一性原理：使用者要什麼

製程工程師 + 現場操作員的 job-to-be-done：**產線跑產品 A → 換線 B/C → 回頭跑 A 時，即時知道 A 有沒有
隱性飄移（每變數仍在規格內、但多變量關係或 X→Y 映射已偏移），早於單變數 SPC；若告警，能追查到哪裡、
該信多少。** 單一產品建一個模型。

## 2. 範圍決策：瓶子優先（bottle-first）

使用者明確指示：**先把瓶子做出來**——用**公開資料集**做線上模擬，PI 介接**保留 stub**、之後換真酒。
Demo 終態 = 一個 UI 走通四步：**選定資料範圍 → 建立模型 → 確認模擬資料 → 查看健康指標**。

- **瓶子（先做）**：模型生命週期 + 線上評分 runner + 4 步 UI，以公開時序資料集（TEP/synthetic/uci）驗證。
- **新酒（後換）**：(a) 真實 PI 資料源（D2 的 PISource 填實 + 現場實測）；(b) 演算法正確性升級（P1/P2）。

## 3. 運行架構（目標）

```
離線建模【工程師】          線上監測【服務/排程】
選資料範圍→選黃金段  ──→  模型 bundle(版本+黃金指紋)  ──→  評分 runner(排程輪詢 takt/10)
  ↑ golden='auto' 輔助        ↑ G1 save/load                  ├ X 鏈: L1/L2/L4(不需Y)
  └ 驗收(hold-out FPR)        └ per-product 模型庫(G4)         └ Y 鏈: 軟量測延遲到達→被動分析
                                                              → persistence_k 連續k窗才告警
                                                              → 告警雙視圖(操作員/工程師)
```

使用者答覆定案的部署參數：
- 資料源 = **PI**（先 stub，公開資料集模擬）；軟量測**延遲到達**，系統**被動**接收後分析。
- 節拍 = 製程 takt 不等（1h/4h…），系統設計取 **takt/10**（≈6–24 分輪詢）。
- 告警同步**現場操作員 + 工程師**（操作員再人工通報工程師＝第二層防護）。
- **單一產品一個模型**。

## 4. 關鍵架構決策（≥2 方案，已定）

- **D1 模型持久化**：選 **joblib + 指紋重放驗證**（load 時重放黃金樣本比對存檔輸出，行為不符即 fail-loud；
  涵蓋 GPR/PLS/MinCovDet 等 sklearn 物件；manifest 記版本）。對比 npz 自訂（手寫 GPR 難）、純 pickle（跨版碎）。
- **D2 Runner 形態**：選 **`poll_once()` 純函式 + 外部排程器驅動**（確定性可測、部署彈性、PI 走 DataSource 協定
  隔離）。對比常駐 daemon（難測、高耦合）。狀態（last_ts/連續告警數/當前 campaign）持久化 JSON，重啟安全。
- **D3 告警雙視圖**：單一 `AlarmEvent` 兩渲染層（操作員=紅綠燈+去查哪裡+持續窗數，零術語；工程師=分層
  語義 L1/L2/L4/Y + p-value + RBC 全榜 + 模型版本）。傳輸走 `AlarmSink` 協定（console/file/webhook）。

## 5. 模組規劃（全加法，不動 interface.py 骨架，Rule 3）

```
src/health_index/deploy/
  bundle.py      G1 模型打包 save/load + 指紋重放
  sources.py     G2 DataSource 協定 + FileDropSource/ReplaySource(可測) + PISource(stub, NOT VERIFIED)
  runner.py      G2 poll_once() + 狀態持久化 + re-entry 追蹤 + persistence_k 接線
  alarms.py      G2 AlarmEvent 雙視圖 + AlarmSink
  acceptance.py  G3 生產驗收報告(改造桶6 benchmark)
  lifecycle.py   G4 per-product 模型庫 + 重建基準觸發 + 哨兵
  ui/            Demo UI(4步流程)；舊 Dash frontend 作廢
```

## 6. 執行順序（瓶子優先；每桶 worktree→TDD→≥2 紅隊(承載性)→綠燈 commit→merge→devlog）

**Phase 1 — 瓶子（demo 關鍵路徑，先做）✅ DEMO-READY 2026-06-15**
- [x] 桶0：golden='auto'（最早乾淨平穩段，紅隊驗 20/20 不選 drift）— merge aca5f0a
- [x] G1：bundle save/load + 指紋重放 — 394b883（7 測試）
- [x] G2a：sources(FrameSource/Replay) + runner poll_once + persistence_k — e1ff4d4（8 測試，resume-safe）
- [x] UI：4 步 demo orchestration（demo.py）+ Dash 殼（demo_app.py，HTTP 200 跑通）— 6 測試
- [x] 端到端整合：公開資料集跑通 demo（golden 健康/換產品+殘留飄移告警/乾淨回歸不誤報）
- [x] G2b：alarms 雙視圖（操作員零術語紅綠燈+去查哪裡 / 工程師分層+p-value+RBC+版本）+ AlarmSink — 6 測試

**Phase 2 — 新酒（正確性，後換）**
- [x] P1：融合層子分數改不飽和標準化嚴重度 exp(−z/scale)（取代超限比例飽和）— ≥2 紅隊 FIX-FIRST 後修正。
      實效：**L1 去飽和**（舊恆=1.0→隨域偏移單調）、三層語義一致、golden FPR=0、benchmark 通過。誠實邊界：
      synthetic 舊 L2 本未飽和故增量主在 L1；最弱飄移由 fwer leg（runner union）補；**自相關窗級標準化低估
      變異 2.2×**（_severity_health docstring 標）。fwer_alarm 權威由 runner 承載。
- [x] 桶5 重開：P1 後 HI~0.93 dead-zone 變窄，固定 0.6 仍可移植（FPR≈0）但哨兵價值上升 — 已更新桶5 文件+哨兵 docstring。
- [x] P2：FWER block 路徑改時間連續 split（fit 前 2/3 連續段、L1/L2 null 取後 1/3 out-of-sample；
      **L4 例外保持 fit 全 golden**——紅隊 A#4 揪出 P2 原把 L4 也 split 致非平穩後段誤報 0.04→0.12）。
      實效（≥2 紅隊實證）：**L2 in-sample 樂觀 0.44→0.04**（真正修好）；iid 路徑逐位元相容。
      **誠實邊界（未達 AC-6 ≤α 之處）**：整體 fwer golden FPR 在 production（full golden）≈0.04≈α，但
      acceptance 50% hold-out split 下 ~0.08，**殘留由非平穩 golden（桶5 §3.3）主導，非校準 bug**——
      acceptance 會 surface（gate 作用）。原計畫「0.17→≤α」為 stale 數字且 P2 單獨結構上達不到 ≤α
      （需 L4 處理 + 平穩 golden）。弱 drift window-level recall trade-off 見 fwer_pvalues docstring。
- [~] P1.5：(a) HI-leg 窗級 block-aware 標準化 — **investigated → NOT WARRANTED**（2026-06-15 原型）：
      窗均值對 golden 窗均值分布標準化時 σ_window 極小→門檻剃刀薄→hold-out golden FPR **爆炸**
      （synthetic 0→0.50、tep_tp 0.12→0.44，重蹈桶5 剃刀薄門檻）。**現行 per-sample 雖理論自相關下偏樂觀
      實證更穩健（FPR 0 vs 0.50）→ 維持 P1 per-sample**。自相關 HI-leg 殘留偏差屬可接受次要債（fwer 為權威軌）。
      (b) [x] acceptance fpr_ok/recall_ok 分開呈現 — AcceptanceReport.verdict()（紅隊 B#3）。
      (c) [ ] is_alarm 統一為單一權威 alarm()（低優先，runner 已 union）。
- [x] G3：生產驗收報告（部署前 hold-out gate：golden FPR/recall/SPC-blind）— a3450cd（5 測試）
- [x] G4：per-product 模型庫 + 時效評估（重建建議，需人決）+ 重建 — 6dd34b1（5 測試）
- [ ] PISource 填實（現場，NOT VERIFIED→實測）

## 7. Demo 驗收（DoD）
1. UI 四步端到端跑通（公開資料集）。
2. 「建立模型」產出可存取 bundle、可重載（指紋驗證通過）。
3. 「確認模擬資料」可預覽將被重放的時序段。
4. 「查看健康指標」顯示隨模擬時間推進的 HI/告警時間線；在含已知飄移的段顯示告警、golden 段健康。

## 8. 既有資產可重用
- 偵測器 fit/score（凍結後評分便宜）、`segment.py` campaign 邏輯、`benchmark.py` DoD 結構、
  `check_threshold_portability` 哨兵、registry/from_frame 攝入、TEP 稀疏 Y（y_every）天然模擬延遲軟量測。

## 9. 已知前置債（交付前必修，列 Phase 2）
- P1 融合層二值化漏弱飄移（HI 軌）；P2 FWER 對自相關 golden 誤報 0.17；server 繞過 registry（兩套資料集目錄）。
