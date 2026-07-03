# 線上模擬部署使用指南（deploy 模組）

> 對象：資料科學家 / 製程工程師。目標：用公開資料集把「選資料→建模→模擬→看健康指標→告警」跑通。
> PI 介接為 stub（`PISource`，NOT VERIFIED），現場換真酒見 §6。模組：`src/health_index/deploy/`。
> 現行建模精靈將被 9 步 batch-AVM Golden 精靈取代（docs/batch_avm_design.md §3；INC-1 `preprocess/batch_features.py` 已落地）；替換前本指南仍為有效操作文件。

---

## 1. 五分鐘快速上手（程式路徑）

```python
from health_index.deploy import demo

# ① 選定資料範圍：看資料集概覽（列數/維度/分段/建議 golden）
ov = demo.dataset_overview("synthetic")            # 或 "tep" / "tep_tp" / "uci_gas_drift"

# ② 建立模型：以 golden 段建模 + 打包 bundle（指紋重放保護）
m = demo.build_and_save_model("synthetic", golden="auto",   # golden: "auto" | (start,end) | None(真值)
                              models_dir="models", created_at="2026-06-15T10:00+08:00")

# ③ 確認模擬資料：預覽將重放的時序
pv = demo.replay_preview("synthetic", window=60)

# ④ 查看健康指標：重放→時間線（region: golden/clean_reentry/drift/other）
tl = demo.score_timeline(m["bundle_path"], "synthetic", window=60)
print(tl["n_alarms"], tl["points"][0])
```

## 2. UI demo（多畫面＋5 步建模精靈）

```bash
set PYTHONPATH=src           # PowerShell: $env:PYTHONPATH="src"
python frontend/demo_app.py  # 開 http://127.0.0.1:8051
```
五步精靈：選資料源 → 訓練資料範圍 → 測試資料範圍 → 建立模型 → 完成（frontend/demo_app.py:215）；另有 home 總覽、告警事件（events）、歷史（history）、段分析（segview）畫面，結果頁支援 GSI/T²/SPE/RBC 點選下鑽（window_detail）。
（舊 `frontend/app.py` 作廢；UI 視覺未渲染驗證，邏輯由 `tests/test_demo.py` 保證。）

## 3. 線上評分 runner（排程輪詢，takt/10）

```python
from health_index.deploy.bundle import load
from health_index.deploy.runner import poll_once, RunnerState, save_state, load_state
from health_index.deploy.sources import FrameSource   # 線上換 PISource

bundle = load("models/synthetic.joblib")               # 指紋 verify，漂移/損毀拒載
src = FrameSource(latest_frame, bundle.x_columns)      # 你的即時資料窗
state = load_state("runner_state.json")                # 重啟安全
scores, state = poll_once(bundle, src, state, window=60, persistence_k=2, compute_fwer=True)
save_state(state, "runner_state.json")
```
- `poll_once` 純函式，外部排程器（Windows 工作排程/cron）每 takt/10 呼叫一次。
- 告警 = `is_alarm ∨ fwer_alarm`；`persistence_k` 連續 k 窗才 `persisted_alarm`（濾毛刺）。
- 軟量測延遲到達：`FrameSource.y_arrivals_until(cursor)` 取已落地的 Y（被動分析）。

## 4. 告警雙視圖（操作員 / 工程師）

```python
from health_index.deploy.alarms import build_alarm_event, dispatch, ConsoleSink, FileSink
for s in scores:
    ev = build_alarm_event(bundle, s, src.x_slice(s.start, s.end))
    dispatch(ev, [ConsoleSink(), FileSink("alarms.jsonl")], only_persisted=True)
    # ev.operator_view()  → 紅綠燈+去查哪裡（零術語）；ev.engineer_view() → 分層+p-value+RBC+版本
```

## 5. 部署驗收 + 生命週期

```python
from health_index.deploy.acceptance import acceptance_from_dataset
r = acceptance_from_dataset("tep_tp", holdout_frac=0.5, target_fpr=0.05, compute_fwer=True)
print(r.verdict())   # PASS / FAIL（區分 golden 誤報率 vs 偵測力 vs SPC）

from health_index.deploy.lifecycle import ModelRegistry, assess_model_currency, rebuild_model
reg = ModelRegistry("models")
cur = assess_model_currency(bundle, recent_confirmed_golden)  # 近期確認-正常資料→CURRENT/REBUILD_RECOMMENDED
# 製程刻意變更後：rebuild_model(reg, "A", new_golden, bundle.x_columns, created_at=...)
```

## 6. 換真酒：PI 介接（現場，NOT VERIFIED）

`deploy/sources.py::PISource` 為 stub。現場填實 checklist（見其 docstring）：
- X 取 **interpolated**（固定網格）；Y 取 **recorded/actual**（真實 lab 值，不內插）。
- 延遲 Y/backfill：回看 lookback 窗重查、用 Y_TIMESTAMP 對齊。
- 時區/UTC；PI quality/substituted 旗標→L1 資料效度；tag→x_column 映射；認證；取樣率對齊 takt/10。
協定隔離使未驗證面僅限 `PISource` 一檔；本機以 `FrameSource`/公開資料集完整測過評分/告警/驗收。

## 7. 已知限制（誠實標，Rule 12）
- **弱隱性飄移**（如 ds≲0.3 / 真實自相關 covert drift）window 級偵測力低，倚賴 fwer + full-segment + 持久化；
  見 `health.fwer_pvalues` / `_severity_health` docstring。
- **非平穩 golden** 會抬高 hold-out FPR（acceptance 會 surface）；golden 段須選平穩代表性段（`golden="auto"` 輔助）。
- 詳見 `docs/deployment_plan.md`（Phase 2 誠實邊界）與 `docs/decision_threshold_calibration.md`（桶5）。
