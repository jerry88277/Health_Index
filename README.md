# Health_Index — 泛化製程健康度 / 隱性飄移偵測

取成大鄭芳田教授 **AVM（自動虛擬量測）精神**，做一個**泛化於任意多變量連續製程 + 軟量測**的健康度／
隱性飄移偵測器：同一條產線跑產品 A → 換線 B/C 或維修 → 回頭跑 A 時，偵測 **A 有沒有隱性飄移**
（每個感測器都還在單變數規格內、但多變量關係或 X→Y 映射已偏移，單變數 SPC 抓不到），且**早於單變數 SPC**。

產品核心＝**多產線健康儀表板**（點產線→即時記錄／告警歷史／模型資訊；告警下鑽到偏移的 X 參數或 Y 量測）；三目標 G1 純 Y-vs-歷史漂移／G2 Y 漂移→X 歸因／G3 Ŷ 越適用域→X 歸因，各以 SMTP 通知收尾（串接暫緩）。

**偵測為確定性數學**（PCA T²/SPE、MCD、Wasserstein、DTW、conformal），runtime 不呼叫 LLM。

---

## 安裝

```bash
pip install -e .          # 需 Python 3.12；核心 numpy/scipy/scikit-learn/pandas/POT
pip install -e ".[api]"   # 選配：FastAPI + Dash demo UI
```

## 30 秒上手：把一張表跑出健康度

```python
import pandas as pd
from health_index.adapters.dataframe import from_frame
from health_index.health import HealthIndex

ds, gt = from_frame(df, x_columns=["t1", "f1", "p1"], golden="auto")  # 任意表→統一契約；自動挑乾淨基準
Xg = ds.frame.loc[gt.golden_mask, list(gt.x_columns)].to_numpy()
hi = HealthIndex().fit(Xg)            # 在 golden 上 fit 並凍結（像建迴歸/異常偵測基準）
print(hi.health_index(X_new))         # 0–1 健康度（1=健康）
print(hi.is_alarm(X_new), hi.fwer_alarm(X_new))   # H8 雙軌 / AC-6 嚴格 FWER
```

## 線上模擬 demo（選資料→建模→確認→看健康指標）
> 註：現行 5 步精靈將由 9 步 batch-AVM Golden 精靈取代（2026-07-02 定調，設計見 docs/batch_avm_design.md；INC-1 批次疊圖+[param×stat] 已建）。

```bash
$env:PYTHONPATH="src"; python frontend/demo_app.py   # http://127.0.0.1:8051
```
程式路徑與部署（runner/告警/驗收/生命週期/PI 換真酒）見 **[docs/deploy_guide.md](docs/deploy_guide.md)**。

---

## 判斷鏈（MECE，第一性原理）

```
L1 DQI_x 資料效度閘 → L2 T²/SPE 多變量域相似度 → L3 軟測量 Ŷ + 可信度
→ L4 campaign Wasserstein/KL 分佈漂移 →（批次）L5 DTW → Health Index 0–1 + 告警旗標
```
重點監看「非 A campaign 或維修後第一段 A」的 re-entry 期。資料基準：連續＝**TEP**、批次＝**penicillin/IndPenSim**。

## 文件地圖（依用途）

| 我想… | 看這份 |
|---|---|
| 用交付系統（建模→模擬→告警→驗收）| [docs/deploy_guide.md](docs/deploy_guide.md) |
| 懂交付計畫與架構決策、已知限制 | [docs/deployment_plan.md](docs/deployment_plan.md) |
| 懂泛化路線圖與缺口分桶 | [docs/generalization_roadmap.md](docs/generalization_roadmap.md) |
| 懂各指標定義（含對 AVM 偏離留痕）| [docs/avm_metrics_definitions.md](docs/avm_metrics_definitions.md) |
| 查文獻（半導體↔化工，逐筆查證，唯一真相）| [docs/literature_crossref.md](docs/literature_crossref.md) |
| 懂某設計為何「不做」（負面決策）| `docs/decision_*.md`（如門檻校準）|
| 懂 batch-AVM 新路徑（Golden 兩關卡／X*=[param×stat]／小n CP／隱性 Y 漂移）| [docs/batch_avm_design.md](docs/batch_avm_design.md) |
| 每日進度 | `docs/devlog/YYYY-MM-DD.md` |
| 專案規範 | [CLAUDE.md](CLAUDE.md) |

## 開發

```bash
$env:PYTHONPATH="src"; python -m pytest -q     # 全套件（部分需 data/tep/*.mat，缺則 skip）
```
規範：綠燈才 commit（測試/型別/health 過、訊息帶 `[verified]`）；承載性改動派 ≥2 獨立紅隊複審；
不造假（查不到標 NOT FOUND）。偵測器與 `interface.py` 契約為骨架、保持穩定；只動領域層。

## 成功判準（DoD）
1. golden 期間維持低分（健康，不誤報）。
2. 對「每變數在規格內」的隱性多變量飄移，**早於單變數 SPC** 升高。
3. 區分「乾淨換線後 A 正常回歸」vs「A 回歸但殘留飄移」。

## 已知邊界（誠實標，Rule 12）
- 弱隱性飄移（極弱 / 真實自相關 covert drift）window 級偵測力低，倚賴 FWER + full-segment + 持久化。
- 非平穩 golden 會抬高誤報率（acceptance 報告會 surface）；golden 須選平穩代表性段。
- PI 介接為 stub（`deploy/sources.py::PISource`，NOT VERIFIED）；本機以公開資料集模擬。
