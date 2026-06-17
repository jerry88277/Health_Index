# 模型 Registry 設計（製程/模型解耦 + 生命週期）

> 增量7。使用者決策（2026-06-17）：採**完整 registry table**（非輕量 manifest）；「更換模型」＝重建替換現役+
> 舊版封存；軟刪除**完全隱藏、只在歷史可見**；placeholder 製程顯示「待建模」。
> 本設計**已經 3 個獨立子代理紅隊複審**（狀態機/資料完整性、向後相容/最小性、產品落地），下列不變式與
> 修正皆為紅隊揪出後採納（對帳見 §5）。符合專案 anti-self-certification（schema 變更需 ≥2 獨立紅隊）。

---

## 1. 第一性原理：為什麼需要這層

現況耦合（紅隊一致揪出）：`product == 資料集名 == bundle 檔名` **三位一體**，硬編碼於
`monitoring_overview`（`registry.build(product)`）、glob 列舉、前端 `_open_model`/`_run`/`_detail`/`_dl_timeline`。
沒有「製程（監控點）」獨立概念，也沒有版本、現役指針、軟刪除、稽核 log。

要解耦的本質：**製程（monitored asset，人取的名）≠ 模型（fitted bundle 版本）≠ 資料集（replay 來源）**。
一個製程可隨時間累積多個模型版本（重建基準），其中一個為現役。

---

## 2. Schema（`{models_dir}/registry.json`，原子寫入）

```json
{
  "schema_version": 1,
  "processes": [
    {"id": "synthetic", "display_name": "合成製程 A", "area": null,
     "dataset": "synthetic", "current_model_id": "synthetic__v2",
     "next_version": 3, "deleted": false,
     "created_at": "2026-06-17T10:00:00+08:00", "created_by": "未具名"}
  ],
  "models": [
    {"id": "synthetic__v1", "process_id": "synthetic", "version": 1,
     "path": "synthetic__v1.joblib", "dataset": "synthetic",
     "golden_range": [0, 600], "fingerprint_hi": 0.97, "has_y_health": true,
     "acceptance": {"passed": true, "holdout_golden_fpr": 0.02, "drift_recall": 0.8, "verdict": "..."},
     "deleted": false, "created_at": "...", "created_by": "未具名", "note": ""}
  ],
  "audit": [
    {"at": "...", "actor": "未具名", "action": "create_process", "process_id": "synthetic",
     "model_id": null, "detail": "placeholder dataset=synthetic"},
    {"at": "...", "actor": "未具名", "action": "build_model", "process_id": "synthetic",
     "model_id": "synthetic__v1", "detail": "golden=[0,600]"},
    {"at": "...", "actor": "未具名", "action": "swap_model", "process_id": "synthetic",
     "model_id": "synthetic__v2", "detail": "v1→v2 重建基準"},
    {"at": "...", "actor": "未具名", "action": "delete_model", "process_id": "synthetic",
     "model_id": "synthetic__v1", "detail": "reason=過期"}
  ]
}
```

---

## 3. 不變式（寫入時強制，違反即 fail-loud）

1. **模型「現役」狀態為衍生**：model 是現役 iff `id == 其 process.current_model_id`；否則為歷史版本或
   （`deleted=true`）已刪。**不存 `active/superseded` 欄位**（避免與 current_model_id drift；紅隊 RT-1#12/RT-2）。
2. `current_model_id` 必須指向**同製程、未刪**的 model，或為 `null`（placeholder / 全部已刪）。
3. **version 來自單調計數器** `process.next_version`（只增不回收）→ 刪最高版後再建不會碰撞 id/path（紅隊 RT-1#2）。
4. `dataset` 必須 ∈ `adapters.registry.available()`（create_process / build 前置檢查）→ 不讓總覽默默全紅（紅隊 RT-1#4）。
5. **軟刪除絕不刪 .joblib**（歷史頁要能重放）→ 只翻 `deleted` 旗標（紅隊 RT-1#8）。
6. **製程 id = ascii-slug(display_name) + 衝突時短 hash**；中文 display_name 僅供顯示，不入路徑（紅隊 RT-1#9）。
7. **持久化原子**：寫 temp + `os.replace`（同卷原子）→ 寫一半不會損毀整個 registry（紅隊 RT-1#5）。
8. **時間字串統一 ISO-8601 帶 offset**（與 events.py 對齊）。

---

## 4. 操作（`AssetStore`，全部回傳可序列化 dict）

| 操作 | 語意 | audit action |
|---|---|---|
| `create_process(display_name, dataset, by, at, area=None)` | 建 placeholder（current=null, deleted=false, next_version=1） | create_process |
| `record_build(pid, path, dataset, golden_range, fingerprint_hi, has_y_health, acceptance, by, at, note)` | 新版本（取 next_version 後 +1）→ 設 current_model_id | build_model（v1）/ swap_model（v>1）|
| `soft_delete_model(model_id, reason, by, at)` | `deleted=true`；若為 current → current 退回**同製程最高版未刪** model 或 null | delete_model |
| `soft_delete_process(pid, reason, by, at, incident_store=None)` | `deleted=true`；給 store 則**強制關閉其 active incidents**（reason=process_deleted）解孤兒 | delete_process |
| `restore_process(pid)` / `restore_model(model_id)` | 反轉 deleted（入口僅在歷史/稽核頁，呼應「完全隱藏」）| restore_* |
| `list_processes(include_deleted=False)` / `get_process` / `current_model(pid)` | 查詢 | — |
| `list_models(pid, include_deleted=False)` | 該製程版本清單 | — |
| `audit_log(pid=None)` | 稽核 log（log存取）| — |
| `history(pid)` | `{process, models(含 acceptance 快照), audit}`；前端再併入該製程 incidents | — |

**「查看模型歷史監控紀錄」**（紅隊 RT-3）：歷史頁 = 版本清單 + **每版 acceptance 快照**（golden_fpr/recall/passed，
建模時 `acceptance_summary` 現成）+ 該製程服役期 incidents 數。純 audit log 回答「誰動過」，不回答「動了變好變壞」，
後者才是工程師 rollback 依據。

---

## 5. 紅隊對帳（我漏的 / 我審錯的，Rule 7 擇一不平均）

**漏的（採納為不變式）**：①product==dataset 三位一體耦合→評分吃 process.dataset；②version 碰撞→單調計數器；
③JSON 非原子→temp+os.replace；④孤兒 incidents→刪製程強制關閉；⑤軟刪不可刪檔；⑥placeholder 污染健康燈→三態。

**審錯的（擇一說明）**：
- `superseded` 狀態多餘 → **砍**（現役為衍生）。
- 巢狀目錄多餘 → 扁平 `{pid}__v{n}.joblib` + 顯式 `path` 欄。
- **保留 `audit[]`**（與 RT-2 砍 audit 相左）：使用者明確要「log存取」，製程級動作無從掛 per-model history，單一
  append-only audit 同涵蓋製程級+模型級；原子性已由 temp+os.replace 解決。
- 「更換模型」在 demo＝**重建基準 re-baseline**（換 golden→髒段 FAIL/乾淨段 PASS），不承諾自動建議重建。
- **不強制 placeholder 前置步驟**（違 item3「點下一關看結果」）：主精靈走快路，placeholder 走進階入口。
- **不 rename** monitoring_overview/plant_hierarchy（守 Rule 3）：改內部讀 registry、保留 `product` 鍵、空 registry 退回 glob。
- **無需遷移**：_MODELS_DIR 是 temp 每 session 重建。

---

## 6. 向後相容

- `build_and_save_model` 簽名**不動**（紅隊 RT-2 警示 `created_at` 為必填 keyword，勿手滑）。registry 流程走新
  orchestration 函式。
- `monitoring_overview`：registry 存在 → 列舉 registry 的非刪製程（含 placeholder 標 `data_unavailable`/待建模）並對現役
  model 評分；無 registry → 退回 glob（既有測試 + 行為不變）。輸出保留 `product` 鍵（=pid）、新增 `dataset`。
- 健康燈**三態**：plant_status 彙總只看「有現役模型且能評分」者定綠/紅；placeholder/不可得歸灰，banner 顯
  「N 監控中／M 告警／K 待建模」，灰不進綠紅分母。

---

## 7. 命名

- 新模組 `deploy/assets.py`，類別 `AssetStore`（比照 `IncidentStore`）。
- **不**叫 `ModelRegistry`（lifecycle.py 已佔）、不叫 `registry`（adapters.registry 已佔）。
