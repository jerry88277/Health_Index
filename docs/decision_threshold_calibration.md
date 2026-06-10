# 決策記錄：per-dataset 告警門檻自動校準（桶5）— 調查結論「現階段不採用」

> 類型：負面發現 / 設計決策（ADR）。狀態：**investigated → NOT WARRANTED（現行資料集）**。
> 建立：2026-06-10（git 時間為權威）。本結論承載且調查中翻轉多次 → 已派 **≥2 獨立紅隊**對抗複審
> （明確指示「嘗試證明校準需要、推翻此結論」），兩隊獨立裁決 **AGREE-NOT-WARRANTED**；其揪出的
> 偏誤已併入下文（§4 靈敏度、§3 window、§3 仿射、§5 可操作哨兵、§6 cross-ref）。

---

## 1. 問題（第一性原理）

路線圖桶5 假設：`HealthIndex.is_alarm` 的固定門檻 `config.hi_alarm_threshold=0.6` **不可跨資料集移植**
——不同資料集的 Health Index（HI）分布尺度因維度/雜訊/相關結構而異，固定 0.6 應在某些資料集
golden 就常告警（誤報）或太鬆（漏報）。預期解法：在 golden 上自動校準門檻命中目標 golden FPR。

## 2. 調查方法

對 `synthetic`(p=10)、`tep`(p=22)、`uci_gas_drift`(p=128 真實半導體)、`indpensim`(批次 penicillin, p≈23)
量測 golden 窗級 HI 分布與 `is_alarm` 的 golden FPR，對照固定門檻 vs 候選校準規則。紅隊另擴充 9 種
對抗性 golden 分布（極端尺度、重尾、強自相關、多模態）。**評估須用平穩、代表性 golden**；非平穩切分
製造假象（§3.3）。

## 3. 證據（實測，確定性數學；可重現）

### 3.1 固定門檻 0.6 的 golden FPR 跨資料集皆 ≈0（含真實資料 + 仿射極端）
| golden 型態 | golden HI median / floor | 固定 0.6 golden FPR | hard_gate 觸發率 |
|---|---|---|---|
| synthetic | 0.98 / ~0.91 | 0.00 | 0.00 |
| tep | 0.96–0.99 / ~0.89 | 0.00 | 0.00 |
| uci (p=128, full-golden in-sample) | 0.99 / ~0.89 | 0.00 | 0.00 |
| indpensim（真實 penicillin 批次）| 0.976 / **0.676** | 0.00 | 0.00 |
| synthetic ×1000 / +1e4 offset / 異質尺度 | 0.988 / 0.975 | 0.00 | 0.00 |
| 重尾 t(2) / AR(1) ρ=.95 / 多模態 / 純噪 | 0.99 / ≥0.93 | 0.00 | 0.00 |

### 3.2 機制：dead-zone 是 in-sample 自正規化的**結構性**後果（非巧合）
HI 各層子分數**對 golden 自正規化**（L1=域內比例、L2=in-control 比例、L4=exp(−z/golden-null-z)）→
golden HI 天生 ≈1。偵測器（MCD、PCA 協方差、Wasserstein-vs-golden-null）皆**仿射等變**，fit 在 golden
上即吸收尺度/偏移 → 紅隊實測 ×1000 尺度、+1e4 偏移、異質單位**完全不動 HI**。試圖工程化「golden
floor < 0.6」（小 n 高 p、含 regime change、單調 ramp）**全部失敗**，floor 仍 ≥0.90。**固定 0.6 落在
golden floor(~0.89) 與 drift 之間的 dead-zone 是結構性的，可移植性比原假設更強。**（紅隊 B 強化）

### 3.3 關鍵教訓：非平穩 golden 切分製造假象（差點誤導結論）
一度觀測「uci 固定 0.6 → hold-out FPR=0.80」似證明門檻失效。深查為**評估假象**：來自「fit 前半 /
eval 後半」，而 uci golden 跨 445 樣本非平穩（前半 HI~0.98、後半~0.30）。診斷三證（紅隊 A 複現）：
temporal split → FPR=1.00；**random-shuffle**（消時序非平穩）→ FPR=**0.000**（20 seeds）；full-golden
in-sample → 0.000。三者一致 → 80% 確為非平穩假象，非門檻移植問題。
> 教訓：golden FPR 評估**必須用平穩代表性 golden**；非平穩段切分會把「資料平穩性問題」誤判為
> 「門檻移植問題」。

## 4. 校準的代價與「靈敏度」的誠實重述（紅隊 A 修正我的偏誤）

**原稿錯誤主張**「校準無靈敏度收益」——**只對強 drift（drift_strength=0.8，HI≈0.46）成立**。對**輕微**
drift（隱性飄移的本義）固定 0.6 **系統性漏報**：
| drift_strength | drift HI median | 固定 0.6 漏報率 |
|---|---|---|
| 0.5 | **0.631（>0.6）** | 漏 71% |
| 0.3 | — | 漏 98% |
| 0.2 | — | 漏 100% |

故**校準確有 recall 收益**（誠實 OOS-floor 校準可把 recall 從 0.0–0.53 拉到 0.74–1.0）。**但**校準的
**FPR 代價不可接受**：把門檻設到 golden HI 分位（q01/q05）→ shuffled hold-out golden FPR 衝到
**0.62–0.75**（synthetic/uci 一致），因 golden HI 分布為左偏尖峰、近零方差，任何分位門檻落在脆弱近模區。
**根因是偵測力／可分離性，不是門檻可移植性**——見 §4.1。另：dead-zone 的乾淨度**window 相依**——
w≤30 時最壞 drift 窗 HI 可越過 0.6（w=20 達 0.657），**w≥60 才乾淨**（紅隊 A）。

### 4.1 唯一找到的真實失效（indpensim）校準結構上救不了
indpensim golden(med 0.976) 與 faulty(med 0.948) **HI 重疊嚴重**（僅差 0.028），無門檻能乾淨分離：
thr=0.9 → faulty TPR 0.34/golden FPR 0.05；thr=0.95 → TPR 0.52/FPR 0.22。要抓 faulty 須把門檻**上調**，
但任何「安全」校準（§5 min-rule）設計上**只放寬不收緊** → 對此 gap **完全無用**。這是**偵測力/可分離性**
問題（屬桶3b 偵測力 + 偵測器高維壓縮），非門檻問題。**桶5 救不了它。**（紅隊 B）

## 5. 結論與決策

**決策：現階段不實作 per-dataset 門檻自動校準（桶5 → investigated/not warranted）。** 理由：
1. **非門檻問題**：固定 0.6 在 ≥9 種 golden（含真實 penicillin/半導體 + 仿射極端 + 病態分布）FPR≈0；
   dead-zone 為自正規化的結構性後果。
2. **校準有 recall 收益但 FPR 代價不可接受**（hold-out FPR 0.62–0.75）；真實失效（indpensim）需門檻
   上調而安全校準只能下調 → 結構上無用。真正缺口是**偵測力/可分離性**（桶3b），非門檻。
3. **不造假（Rule 12）**：無法誠實展示校準淨益 → 不 ship 假裝有益的功能（Rule 2 不投機）。
4. **hard_gates 非 golden FPR 來源**（9 資料集實測全 0）。

**改 ship：可操作的「門檻可移植性哨兵」（只用 golden，無需 drift 標籤）**。原 §5 觸發條件「golden HI
floor 接近 drift ceiling」**不可操作**（drift ceiling 需標籤，泛化場景正好沒有）。改為**只用 golden 窗 HI
floor** 的機械判準（紅隊 B 建議）：
> `HealthIndex.check_threshold_portability(golden)`：若 `min(golden 窗 HI) < hi_alarm_threshold + margin`
> 則 `warnings.warn`（固定門檻可能不可移植/對輕微 drift 漏報）。**不自動改門檻**（校準經 ≥2 紅隊驗證
> not warranted），只 fail-loud（Rule 12）。零行為改變、零成本、可操作（無需 drift 標籤）。
本哨兵已隨本決策實作（`src/health_index/health.py` + `tests/test_threshold_portability.py`）。

## 6. 與其他桶的關係（避免「藏問題」，紅隊 B）
- **桶3b（次桶候選）**：高維 L2 T² 在 p≫n 脆弱、偵測器高維 HI 壓縮——indpensim faulty 漏抓的**偵測力**
  gap 屬此，非桶5。
- **FWER 自相關校準**：indpensim 上 `fwer_alarm` golden alarm rate≈0.30 ≫ α=0.05，疑批次軌跡自相關使窗
  非 iid（與既有 L2 block-aware 債同源）→ 列待辦，**非桶5**（記此以免誤以為 indpensim 已全驗過）。
- **FWER 軌**：`fwer_alarm` 已由 permutation null 自校準（golden FPR≤α），不在本決策範圍。
