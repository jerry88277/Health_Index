# 啟動手冊 — Health_Index 全棧（M10）

> 目標：在**乾淨環境**一次拉起全棧（後端判斷鏈 API + 前端視覺化），並以煙霧測試確認端到端正常。
> 本手冊命令與預期輸出於 <重新實測日期/commit> 實測更新（原 2026-06-02 基準之測試數/端點/資料集清單已變動）。
> 範圍誠實（Rule 12）：資料源含內建合成（synthetic/synthetic_pgn）與真實集 adapter：tep/tep_tp（`data/tep/` 12 個 MMFDD .mat 在庫、`tep.generate()` 可跑）、uci_gas_drift、ccpp(_covert)、steel(_covert)；PRONTO 仍未接。

---

## 0. 架構一覽

```
合成資料 generate → preprocess.segment → golden-A 上 fit HealthIndex
        → per-campaign 健康度/告警/re-entry
   ┌─────────────────────────────────────────────┐
   │  後端 FastAPI  :8000   /health /datasets /analyze │
   └─────────────────────────────────────────────┘
                    ▲ REST (httpx)
   ┌─────────────────────────────────────────────┐
   │  前端 Dash     :8050   HI 長條圖 + 各層子分數圖    │
   └─────────────────────────────────────────────┘
```

判斷鏈（確定性數學，runtime 不呼叫 LLM）：`L1 DQI_x → L2 T²/SPE/GSI → L3 軟測量+CP → L4 漂移 →（批次離線）L5 DTW → Health Index 融合 + re-entry`。

---

## 1. 前置需求

| 項目 | 需求 |
|---|---|
| Python | ≥ 3.10（開發實測 3.12） |
| OS | 跨平台；以下指令給 Windows PowerShell 與 POSIX 兩版 |
| 網路 | 僅安裝套件時需要；runtime（合成資料）離線可跑 |
| 編譯器 | **不需要**（純 numpy 合成，未用 pyTEP/Fortran） |

---

## 2. 建 venv 並安裝

**Windows PowerShell**
```powershell
cd D:\Side_project\Health_index
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev,api]"
```

**POSIX (bash/zsh)**
```bash
cd /path/to/Health_index
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,api]"
```

extras 說明（`pyproject.toml`）：
- 核心偵測鏈：`numpy / scipy / scikit-learn / pandas / POT / ruptures`（base 依賴，自動裝）。
- `dev`：`pytest / httpx`（跑測試）。
- `api`：`fastapi / uvicorn / dash / plotly`（後端 + 前端）。

> 只想跑偵測鏈與測試、不開全棧：`pip install -e ".[dev]"` 即可。

---

## 3. 資料

MVP 內建**合成連續製程**，無需下載：`grade A(golden) → B → A(clean re-entry) → C → A(drift re-entry)`，
在最後一段 A 注入**隱性多變量飄移**（每變數仍在單變數規格內、僅相關結構偏移）。

真實集 adapter 已接：`tep`/`tep_tp`、`uci_gas_drift`、`ccpp(_covert)`、`steel(_covert)`（皆沿用同一 `interface` 契約，清單以 `adapters.registry.available()` 為準）；PRONTO 未接。

---

## 4. 啟動後端 + 健康檢查

```powershell
# 終端機 A（保持開啟）
python -m uvicorn health_index.api.server:app --host 127.0.0.1 --port 8000
```

健康檢查（另開終端機）：
```powershell
# PowerShell
(Invoke-WebRequest http://127.0.0.1:8000/health).Content
# 或 curl
curl http://127.0.0.1:8000/health
```
**預期**：`{"status":"ok","version":"0.0.1"}`

---

## 5. 啟動前端

終端機 B：`python frontend/app.py`（:8050，工程師視圖）。另補終端機 C：`python frontend/demo_app.py`（:8051，產品 UI：監控總覽 → 建模精靈 → 結果下鑽，含事件閉環與製程/模型 registry；注意現行 5 步精靈將由 9 步 batch-AVM Golden 精靈取代，見 docs/batch_avm_design.md §3）。
瀏覽器開 **http://127.0.0.1:8050** → 選 `synthetic`、設 seed/drift_strength → 按「分析」。

預期看到 app.py 現行版面（由大到小）：前情提要 → 總健康度 → 三面向子分數 → 可疑參數排行（RBC）→ 異常程度時間軸，術語為現場白話（SPE→「異常程度」等）。

---

## 6. 煙霧測試

**(a) 單元測試全綠**
```powershell
python -m pytest -q
```
**預期**：全綠（2026-07-03 commit 5052b8a 基準為 `451 passed`；以當下全綠為準）。

**(b) API 端到端**（後端需在跑）
```powershell
curl -X POST http://127.0.0.1:8000/analyze -H "Content-Type: application/json" -d "{\"dataset_id\":\"synthetic\",\"seed\":5,\"drift_strength\":1.2}"
```

**(c) cross-validation runner（M9，離線）**
```powershell
python -c "from health_index.validation.crossval import cross_validate, format_report; print(format_report(cross_validate()))"
```
**預期**：5/5 組態 AC-1/2/3 全過的 markdown 報告。

---

## 7. Demo Walkthrough（判讀預期結果）

`POST /analyze`（seed=5, drift_strength=1.2）實測結果——這正是本專案三條成功判準的端到端展示：

| campaign | grade | re-entry | Health Index | 告警 | 判讀 |
|---|---|:--:|--:|:--:|---|
| C0 | A | ✗ | 0.990 | ✗ | golden-A 健康（**判準 1**） |
| C1 | B | ✗ | 0.250 | ✔ | 換產品 B（操作點位移，明顯異於 A baseline） |
| C2 | A | ✔ | 0.995 | ✗ | **乾淨換線回歸 A** 維持健康（**判準 3** 的「乾淨」側） |
| C3 | C | ✗ | 0.247 | ✔ | 換產品 C |
| C4 | A | ✔ | 0.288 | ✔ | **殘留隱性飄移的回歸 A**：HI 崩、告警（**判準 2+3**） |

`reentry_campaigns = [2, 4]`。

**關鍵**：C4 的隱性飄移**每個變數都仍在單變數 3σ 規格內**（單變數 SPC 全盲），但 Health Index 由 ~0.99 崩到 0.288 並告警——這就是本 index 存在的理由。對照 C2（乾淨回歸）維持 0.995，證明能區分「乾淨換線後正常回歸」vs「回歸但殘留飄移」。

---

## 8. 範圍與限制（誠實標記，Rule 12）

| 項目 | 狀態 |
|---|---|
| 偵測鏈 L1–L4 + Health Index 融合 + re-entry | ✅ 已實作（M2–M6） |
| 後端 `/health` `/datasets` `/analyze`（彙總式） | ✅ 已實作（M7） |
| 前端 campaign 級 HI / 子分數圖 | ✅ 已實作（M8） |
| cross-validation 跨組態超參 robustness（合成） | ✅ 已實作（M9） |
| 後端 `POST /timeline`（逐樣本 T²/SPE/GSI）、`POST /contribution`（RBC 肇因）+ 前端時間軸/肇因圖 | ✅ B1（指出隱性飄移在序列中何時起、哪個變數） |
| Ŷ vs Y 軟測量端點 | ✅ `POST /softsensor` 已建（另有 `/fwer` `/yhealth` `/yhealth_index` `/series`，見 api/server.py） |
| `/baseline`、`/crossval` 端點 | ⏳ 仍無（crossval 走 §6(c) 離線 runner） |
| L5 批次 DTW（IndPenSim） | ✅ 已實作（`detectors/batch_dtw.py` + `adapters/indpensim.py` + `preprocess/align.py`，離線路徑） |
| **完整 AC-4「真實集不退化」** | 真實集 adapter 已接（uci_gas_drift/tep/ccpp/steel；`validation/real_set.py` 在庫、`data/tep/` .mat 在庫）；AC-4 通過與否以 `validation/benchmark.py` 重新核對後回填（NOT VERIFIED） |
| **AC-6「golden-A 誤報率≤α」嚴格 FWER 控制** | `POST /fwer` 端點已建（api/server.py:140）；嚴格 FWER 治理與「跨線多重比較」仍列 2026-07-02 風險稽核開放缺口——本列狀態需重新核對後回填（NOT VERIFIED） |
| 維修型 re-entry（同 grade A 中停機） | ⏳ 需 mode=maintenance 資料 |

---

## 9. FAQ / 疑難排解

**Q：埠 8000 / 8050 被占用？**
A：後端 `--port` 換埠；前端改 `frontend/app.py` 的 `port=8050` 或 `create_app(base_url=...)` 指向新後端埠。

**Q：前端顯示「後端錯誤：…」？**
A：(1) 後端是否在 :8000 跑著；(2) `create_app` 的 `DEFAULT_API`（`http://127.0.0.1:8000`）是否與後端埠一致；(3) 防火牆是否擋 localhost。

**Q：`ModuleNotFoundError: health_index` 或 `frontend`？**
A：確認已 `pip install -e .`（editable 裝 `src/health_index`）；前端在 repo 根的 `frontend/`，`pyproject.toml` 的 `pytest pythonpath=["src","."]` 已處理測試路徑，手動跑前端時請在 repo 根目錄執行。

**Q：`/analyze` 回 422？**
A：`seed` 須 ≥ 0、`drift_strength` 須 `0 < x ≤ 100`（schema 防 inf/負值）。

**Q：版本不符 / 套件衝突？**
A：以乾淨 `.venv` 重裝；核心要求見 `pyproject.toml`（numpy≥1.23、scipy≥1.9、sklearn≥1.1、pandas≥1.5、POT≥0.9、ruptures≥1.1）。

**Q：降級模式（運算成本）？**
A：重指標（MMD permutation O(B·n²)、Wasserstein）若超線上節拍，依 `dev plan §4` 走降採樣 PCA-score / KS first-pass / 1D-Wasserstein；超參集中於 `config.py`（單一真相，附「勿動除非…」說明）。

---

## 10. 一次拉起全棧（複製貼上）

```powershell
# 一次性
python -m venv .venv; .\.venv\Scripts\Activate.ps1; pip install -e ".[dev,api]"

# 終端機 A：後端
python -m uvicorn health_index.api.server:app --port 8000

# 終端機 B：前端（後端起來後）
python frontend\app.py
# → http://127.0.0.1:8050
```
