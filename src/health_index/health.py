"""Health Index 融合 + campaign re-entry 觸發（判斷鏈收口）。

把 L1/L2/L4 偵測器在 golden-A 上 fit 並凍結，對 campaign 算各層 0–1 子分數（1=健康），加權成
0–1 Health Index。依紅隊：
- **方向統一**：所有子分數「越高越健康」。
- **決策＝融合趨勢分數 + 硬閘安全網（雙軌，紅隊 H8）**：is_alarm = HI<門檻 OR 任一單層硬閘。
  這**不是**嚴格「單一決策點」（紅隊 N2 的理想）——硬閘是 H8 的安全網，防致命破壞被融合平均稀釋。
  **B3 接線**：嚴格 FWER 單一決策點已實作為 ``fwer_alarm``（各層→對 golden null 尾機率→Holm 校正，
  golden 誤報率 ≤ config.fwer_alpha，AC-6）；``is_alarm`` 雙軌保留為 H8 安全網，兩者並存、語義不同。
  持續性閾值（drift_persistence_k）仍預留未接線。硬閘的「自然必要性」（融合漏、硬閘獨抓）在合成資料
  無法產生（漂移使兩者同時觸發），此處僅機制性驗證硬閘路徑，自然場景待 TEP/真實單層致命故障驗證。
- **re-entry 觸發**：偵測「換產品（非 A grade）後第一段 A」。**維修型 re-entry**（同 grade A 中停機）
  需 mode=maintenance 資料支援，synthetic 無此事件，列 M-later TODO（不宣稱已實作）。

注：融合權重（config.fusion_weights）與門檻為 MVP 簡單加權（Rule 2）；紅隊 N6 要求「各分量→對 golden
null 尾機率」再加權，目前 s_l1/s_l2 為**比例近似**、s_l4 為 exp 衰減（非嚴格尾機率），屬已知設計債，
M9 校準。L3 軟測量可信度（CP/GSI）為獨立「Ŷ 可否信」旗標，不併入健康分數（語義不同）。
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field

import numpy as np

from .config import DEFAULT, Config
from .detectors.dqi_x import DQIxGate
from .detectors.drift import DriftDetector
from .detectors.mspc import MSPCModel
from .interface import CAMPAIGN_ID, GRADE_LABEL, ProcessDataset


@dataclass
class HealthIndex:
    """L1/L2/L4 融合健康度。fit(golden-A) → health_index / hard_gates / is_alarm。"""

    config: Config = field(default=DEFAULT)  # 融合權重在 config.fusion_weights（單一 config 治理，D1）

    def fit(self, X_golden: np.ndarray) -> "HealthIndex":
        self._golden_ = np.asarray(X_golden, dtype=float)
        self.dqi_ = DQIxGate(self.config).fit(X_golden)
        self.mspc_ = MSPCModel(self.config).fit(X_golden)
        self.drift_ = DriftDetector(self.config).fit(X_golden)
        # P1：golden per-sample DQI/SPE baseline（mean/std）供 subscores 的**不飽和嚴重度**標準化。
        # 取代原「超限比例」（弱隱性飄移下飽和於高位→漏報）；per-sample 標準化使窗均值不受窗長影響。
        dqi_g = self.dqi_.score(self._golden_)
        spe_g = self.mspc_.spe(self._golden_)
        self._dqi_mu_, self._dqi_sig_ = float(dqi_g.mean()), float(dqi_g.std() + 1e-9)
        self._spe_mu_, self._spe_sig_ = float(spe_g.mean()), float(spe_g.std() + 1e-9)
        return self

    def _fit_fwer_calibration(self) -> None:
        """B3：為 FWER p-value 建 **split 校準**——偵測器 fit 於 golden_fit、null 取自 disjoint 的
        golden_calib（out-of-sample）。這避免 production 偵測器的 in-sample 控制限低估 golden 誤報率
        （M3 記錄 in-sample≈2α vs hold-out≈4α 的 gap），使 p-value 在 golden null 下真正近似 uniform。

        **lazy**：僅在首次呼叫 ``fwer_pvalues``/``fwer_alarm`` 時建（含額外 FastMCD，不拖慢未用 FWER
        的共同路徑 health_index/is_alarm/timeline，Rule 6）。golden 太小無法 split（不足 2·min_samples_per_dim）
        時退回 production 偵測器 + in-sample 校準，並以 ``_fwer_split_=False`` 標記（FWER 較不保守，誠實 surface）。
        """
        G = self._golden_
        n = len(G)
        mind = self.config.min_samples_per_dim
        self._fwer_l2_block_ = self.drift_.block_len_ > 1
        self._fwer_block_cal_ = None
        if self._fwer_l2_block_:
            # 自相關（連續 TEP）→ **P2：時間連續 split**（fit 前 2/3 連續段保自相關；null 取後 1/3 連續段
            # out-of-sample）。修正原「fit 全 golden + null 取 in-sample」之樂觀——實證 tep_tp hold-out golden
            # fwer FPR 0.44（in-sample 看似正常）。連續 split 同時滿足「保序（block-bootstrap 前提）」與
            # 「out-of-sample（split 校準前提）」——二者非互斥，原註解誤當 trade-off（審查 P2 / 紅隊診斷）。
            n_fit = (2 * n) // 3
            if n_fit >= 2 * mind and (n - n_fit) >= mind:
                gfit = G[:n_fit]  # 連續前段（保自相關）
                self._fwer_cal_ = G[n_fit:]  # 連續尾段（out-of-sample null；L1/L2 共用）
                self._fwer_block_cal_ = self._fwer_cal_
                self._fwer_dqi_ = DQIxGate(self.config).fit(gfit)
                self._fwer_mspc_ = MSPCModel(self.config).fit(gfit)
                # L4 例外（紅隊 A#4）：mmd_pvalue 本即 window-vs-window 自校準、**不需** calib split；若 fit 於
                # 前 2/3、卻以漂移的後段評分，L4 會把 golden 自然操作點漫遊誤判為位移（實證 golden FPR 0.04→0.12）。
                # 故 L4 維持 fit 於**全 golden**（null 涵蓋整時域），只 L1/L2 套 continuous split。
                self._fwer_drift_ = DriftDetector(self.config).fit(G)
                self._fwer_split_ = True
            else:  # 太短無法連續 split → in-sample fallback + warn
                self._fwer_cal_ = G
                self._fwer_dqi_, self._fwer_mspc_, self._fwer_drift_ = self.dqi_, self.mspc_, self.drift_
                self._fwer_split_ = False
                warnings.warn(
                    f"FWER 連續 split 停用（自相關 golden n={n} 不足）→ 退回 in-sample null，FWER 較不保守"
                    "（AC-6 不保證 ≤α，自相關下實證可達 0.44）。請增大 golden。",
                    RuntimeWarning, stacklevel=2,
                )
        else:
            # iid（synthetic）→ 原 shuffle split + permutation（統計等價，向後相容）
            ncal = n // 3
            if ncal >= mind and (n - ncal) >= 2 * mind:
                perm = np.random.default_rng(self.config.random_state).permutation(n)
                self._fwer_cal_ = G[perm[:ncal]]
                gfit = G[perm[ncal:]]
                self._fwer_dqi_ = DQIxGate(self.config).fit(gfit)
                self._fwer_mspc_ = MSPCModel(self.config).fit(gfit)
                self._fwer_drift_ = DriftDetector(self.config).fit(G)
                self._fwer_split_ = True
            else:
                self._fwer_cal_ = G
                self._fwer_dqi_, self._fwer_mspc_, self._fwer_drift_ = self.dqi_, self.mspc_, self.drift_
                self._fwer_split_ = False
                warnings.warn(
                    f"FWER split 校準停用（golden n={n} 不足 3·min_samples_per_dim）→ 退回 in-sample null，"
                    "golden 誤報率控制較不保守（AC-6 不保證 ≤α）。請增大 golden 或降維。",
                    RuntimeWarning, stacklevel=2,
                )
        self._fwer_ready_ = True

    def _severity_health(self, stat: np.ndarray, mu: float, sig: float) -> float:
        """per-sample 對 golden 標準化嚴重度 → exp 健康 → 窗均值（1=健康，不飽和）。

        P1（紅隊+審查）：原 L1/L2「超限比例」把連續統計量用控制限二值化再取比例 → 弱隱性飄移下
        多數樣本未破限 → 比例飽和於高位 → HI 漏報。改逐樣本標準化 z=clip((x−μ)/σ,0,∞)、exp(−z/scale)
        後取窗均值：弱但一致的抬高使每樣本健康同步下滑、窗均值單調反映（不飽和），且 per-sample
        標準化使結果不受窗長影響（與 L4 的 exp(−z/scale) 同構，跨層語義統一）。

        誠實邊界（紅隊實證，Rule 12）：
        - **自相關失效**：σ 為 golden **per-sample** std；自相關資料（連續 TEP，PC1 ρ₁≈0.93）的窗均值
          變異 ≈ iid 預測（σ/√w）的 **2.2×** → 本標準化**低估窗級變異（anti-conservative）**，使 P1 融合對
          真實連續製程的 covert drift **窗級鑑別力弱**（實測 tep_tp drift 窗 HI<0.6 recall≈0）；該訊號由
          fwer_alarm（window-vs-window block-bootstrap，runner 已 union）扛起，非 P1 融合。徹底修需改窗級
          block-aware 標準化（列後續）。
        - **in-sample 樂觀**：μ/σ 取自 fit 的 golden（in-sample）；n/p 充足（生產尺寸 n≥~2p）時 hold-out
          golden FPR 仍 0，但極端高維（n≈p）會低估 σ → hold-out golden 偶誤報（且 degraded_ 未必觸發）。
        - **scale 為敏感度旋鈕非 FPR 旋鈕**：dead-zone 寬，golden FPR 對 scale 不敏感（實測各 scale 皆 0）；
          scale 越小越敏感（recall↑）。預設 3.0 偏保守（防自相關 σ 低估下的誤報），非 recall 最佳。
        """
        z = np.clip((np.asarray(stat, dtype=float) - mu) / sig, 0.0, None)
        return float(np.mean(np.exp(-z / self.config.fusion_severity_scale)))

    def subscores(self, X: np.ndarray) -> dict[str, float]:
        """各層 0–1 健康子分數（1=健康；方向統一）。三層皆為 exp(−標準化嚴重度) 形（P1 一致化）。"""
        s_l1 = self._severity_health(self.dqi_.score(X), self._dqi_mu_, self._dqi_sig_)   # 域偏離嚴重度
        s_l2 = self._severity_health(self.mspc_.spe(X), self._spe_mu_, self._spe_sig_)    # SPE 嚴重度（隱性飄移主訊號）
        z = float(self.drift_.wasserstein_magnitude(X))
        s_l4 = float(np.exp(-max(z, 0.0) / self.config.drift_scale))  # 漂移量級（已是標準化嚴重度形）
        return {"L1": s_l1, "L2": s_l2, "L4": s_l4}

    def health_index(self, X: np.ndarray) -> float:
        """0–1 融合健康分數（1=健康）。"""
        s = self.subscores(X)
        return float(np.average([s["L1"], s["L2"], s["L4"]], weights=self.config.fusion_weights))

    def hard_gates(self, X: np.ndarray) -> dict[str, bool]:
        """單層硬閘（任一 True＝該層嚴重破限）；避免致命破壞被融合稀釋。"""
        return {
            "L1": bool(self.dqi_.is_inlier(X).mean() < 0.5),
            "L2": bool(self.mspc_.is_anomaly(X).mean() > 0.5),
            "L4": bool(self.drift_.is_drift(X)),
        }

    def is_alarm(self, X: np.ndarray) -> bool:
        """融合趨勢 + 硬閘雙軌告警（H8 安全網）：融合分數低於門檻，或任一單層硬閘破限。

        註（B3）：此為 H8 雙軌（非嚴格 FWER）。需 golden 誤報率受 α 控制（AC-6）時用 ``fwer_alarm``。
        P1 後 ``is_alarm`` 維持「便宜快路徑」語義（不納入 fwer，以保 sentinel/portability 的「只用 golden、
        零行為改變」契約）；**權威告警＝is_alarm ∨ fwer_alarm 的聯集已收口於 ``alarm()``**（線上 runner.poll_once
        經 ``alarm()`` 判決），對最弱飄移（ds≲0.3）由 fwer leg 補（deployment_plan §6 P1）。
        """
        return bool(self.health_index(X) < self.config.hi_alarm_threshold or any(self.hard_gates(X).values()))

    def check_threshold_portability(
        self, X_golden: np.ndarray, *, window: int | None = None, margin: float = 0.1
    ) -> float:
        """門檻可移植性哨兵：只用 golden 算窗級 HI floor，逼近告警門檻則 fail-loud（Rule 12）。

        桶5 調查結論（``docs/decision_threshold_calibration.md``，經 ≥2 紅隊複審）：固定
        ``hi_alarm_threshold=0.6`` 下 golden FPR≈0，**per-dataset 自動校準 not warranted**（有 recall 收益
        但 hold-out FPR 代價不可接受；真實失效屬偵測力非門檻）。

        **P1 後重檢（桶5 重開，紅隊實證）**：P1 把子分數改不飽和嚴重度後，golden HI 由 ~0.98 降至 ~0.93、
        dead-zone **變窄**（synthetic floor~0.86、tep_tp~0.80、真實 indpensim 窗級 floor 已逼近甚至偶破 0.6，
        median 仍 ~0.97 故 golden FPR 仍≈0）。結論：固定 0.6 對現行資料集**仍可移植**（FPR≈0），但「floor
        遠高於門檻」的舊論述不再普遍成立 → **本哨兵的價值在 P1 後上升**（dead-zone 不再寬到可忽略）。

        本哨兵**只用 golden**（無需 drift 標籤 → 泛化場景可操作）在 floor 逼近門檻時 warn。**不自動改門檻**。

        Args:
            X_golden: golden 樣本（須為平穩代表性 golden；非平穩段會低估 floor 製造假警，見決策文件 §3.3）。
            window: 窗長（None→config.drift_window）。
            margin: floor 與門檻的安全餘裕；floor < 門檻+margin 即警示。

        Returns:
            觀測到的 golden 窗 HI floor（最小值）；golden 短於窗長則回 ``nan`` 不檢。
        """
        w = int(window or self.config.drift_window)
        G = np.asarray(X_golden, dtype=float)
        if len(G) < w:
            return float("nan")
        step = max(1, w // 4)
        floor = min(self.health_index(G[i : i + w]) for i in range(0, len(G) - w + 1, step))
        thr = self.config.hi_alarm_threshold
        if floor < thr + margin:
            warnings.warn(
                f"golden HI floor={floor:.3f} 逼近告警門檻 {thr}（margin {margin}）→ 固定門檻可能不可移植/"
                "對輕微 drift 漏報。見 docs/decision_threshold_calibration.md（校準經 ≥2 紅隊驗證 not warranted）。",
                RuntimeWarning,
                stacklevel=2,
            )
        return float(floor)

    def fwer_pvalues(self, X: np.ndarray) -> dict[str, float]:
        """各層對 golden-A null 的窗級右尾 p-value（越小越異常）。

        各層用 permutation 兩樣本，使 p-value 在 golden null 下近似 uniform（不受 in-sample 控制限低估
        之累，紅隊 N6）：
        - **L1**：離域指標比例（golden_calib vs X；離散低計數，此 synthetic 下近乎無功效＝恆保守）。
        - **L2**：每樣本 **SPE 均值**——雙路：iid（block_len_=1）用 ``_perm_two_sample``（golden_calib vs X）；
          自相關（連續 TEP）改 ``_block_window_pvalue``，**P2 後 null 取 out-of-sample 連續尾段**
          （``_fwer_block_cal_``，非 in-sample 全 golden）——修正 in-sample 樂觀（紅隊實證 tep_tp hold-out
          golden L2 FPR 0.44→0.04）。隱性飄移主訊號。誠實標：弱 drift 在**短窗（如 60）out-of-sample 下
          window-level recall 可能掉到 ~0**（需足夠樣本/full-segment 才有功效，紅隊）；融合 HI 對此惰性。
        - **L4**：``DriftDetector.mmd_pvalue``（window-vs-window block-bootstrap；fit 於**全 golden**，本即
          自校準、不套 calib split——P2 刻意不對 L4 split，否則對非平穩後段誤報）。誠實標（紅隊修正）：
          舊註「golden FPR 0.000」僅在 **in-sample/平穩** golden 成立；**非平穩 golden 的 hold-out 下 L4 可達
          ~0.08**（操作點漫遊被視為位移）——此為 golden 品質訊號（acceptance 會 surface），非校準 bug。

        Returns: {"L1","L2","L4"} → p∈(0,1]。
        """
        if not getattr(self, "_fwer_ready_", False):
            self._fit_fwer_calibration()  # lazy：首次用 FWER 才建校準（不拖慢共同路徑，Rule 6）
        X = np.asarray(X, dtype=float)
        cal = self._fwer_cal_
        # L1：離域比例（permutation 兩樣本；calib vs X 可交換 → 校準）
        out_x = (~self._fwer_dqi_.is_inlier(X)).astype(float)
        out_c = (~self._fwer_dqi_.is_inlier(cal)).astype(float)
        p1 = self._perm_two_sample(out_c, out_x)
        # L2：每樣本 SPE 均值（連續統計量；隱性飄移主訊號）
        spe_x = self._fwer_mspc_.spe(X)
        if self._fwer_l2_block_:  # 自相關：window-vs-window 區塊化 null
            # P2：null 取**out-of-sample 連續尾段**（_fwer_block_cal_）的逐樣本 SPE，非 in-sample 全 golden。
            # 連續段保自相關（block-bootstrap 前提）且 disjoint 於 mspc fit 的前段（消 in-sample 樂觀 0.44）。
            cal_series = self._fwer_block_cal_ if self._fwer_block_cal_ is not None else self._golden_
            spe_g = self._fwer_mspc_.spe(cal_series)
            p2 = self._block_window_pvalue(spe_g, float(np.mean(spe_x)), len(X))
        else:                     # iid：原 permutation 兩樣本（向後相容）
            p2 = self._perm_two_sample(self._fwer_mspc_.spe(cal), spe_x)
        # L4：MMD block-permutation（PCA 分數空間）
        p4 = float(self._fwer_drift_.mmd_pvalue(X))
        return {"L1": float(p1), "L2": float(p2), "L4": p4}

    def _block_window_pvalue(self, golden_series: np.ndarray, obs_mean: float, s: int) -> float:
        """window-vs-window 區塊化單尾 p-value：null=golden **連續窗**的統計量均值分佈，obs=X 窗均值。

        WHY（紅隊②揭露的 L2 既有債）：permutation 兩樣本假設逐樣本可交換；自相關連續窗的 SPE 有效
        樣本數 ≪ 窗長 → permutation null 低估窗均值變異 → in-sample 過度拒絕（實測 FP@.05=0.22≫α）。
        改抽 golden **連續窗**建 null（窗級含同序列相依）→ FP 回落 ≈名目（實測 0.058）；drift 仍抓
        （SPE 均值遠高於 golden 窗 → obs≫null → p≈0）。s=X 窗長（block＝整窗，與 L4 window-vs-window 同構）。

        Args: golden_series: 保序 golden 逐樣本統計量（如 SPE）；obs_mean: X 窗統計量均值；s: X 窗長。
        Returns: 右尾 p∈(0,1]（越小越異常）。
        """
        g = np.asarray(golden_series, dtype=float)
        n = len(g)
        s = min(int(s), n)
        rng = np.random.default_rng(self.config.random_state)
        starts = rng.integers(0, n - s + 1, size=self.config.fwer_n_boot)
        null = np.array([g[a0 : a0 + s].mean() for a0 in starts])
        count = int((null >= obs_mean).sum())
        return (1 + count) / (self.config.fwer_n_boot + 1)

    def _perm_two_sample(self, ref: np.ndarray, new: np.ndarray) -> float:
        """單尾 permutation 兩樣本檢定：H1＝new 的均值 > ref（越異常越大）。

        統計量＝new 群均值；pool(ref,new) 後 permutation 重排、取 len(new) 群算均值建 null。
        ref（golden_calib，out-of-sample）與 new（X）在 golden null 下可交換 → p 精確近似 uniform。
        """
        ref = np.asarray(ref, dtype=float)
        new = np.asarray(new, dtype=float)
        pooled = np.concatenate([ref, new])
        nn = len(new)
        obs = float(new.mean())
        rng = np.random.default_rng(self.config.random_state)
        B = self.config.fwer_n_boot
        count = sum(float(rng.permutation(pooled)[:nn].mean()) >= obs for _ in range(B))
        return (1 + count) / (B + 1)

    def fwer_alarm(
        self, X: np.ndarray, *, alpha: float | None = None, _pvalues: dict[str, float] | None = None
    ) -> bool:
        """AC-6 單一決策點：3 層 p-value 經 **Holm 校正**，任一拒絕虛無即告警。

        取代 ``is_alarm`` 的裸 OR（紅隊 N2）：在 golden-A null 下 Holm 保證族系錯誤率（FWER）≤ alpha
        → golden 誤報率受控（AC-6）。``is_alarm``（H8 雙軌硬閘）保留為安全網，兩者語義不同、並存。

        Args:
            _pvalues: 內部優化——已算好 ``fwer_pvalues`` 時傳入避免重算（如 ``alarm()``/runner 共用同一窗
                的 p-value）；一般呼叫端留 None 由本方法自算。
        """
        alpha = self.config.fwer_alpha if alpha is None else alpha
        pv = self.fwer_pvalues(X) if _pvalues is None else _pvalues
        return any(_holm_reject(pv, alpha).values())

    def alarm(
        self, X: np.ndarray, *, compute_fwer: bool = True, alpha: float | None = None,
        _pvalues: dict[str, float] | None = None,
    ) -> bool:
        """**單一權威告警出口**：``is_alarm``（H8 雙軌快路徑）∨ ``fwer_alarm``（AC-6 嚴格 FWER）。

        統一線上判決——此前該聯集由各呼叫端（runner.poll_once）自拼，最弱飄移（ds≲0.3）只由 fwer leg
        補（deployment_plan §6 P1）。收口為單一加法方法（紅隊指引：**不改 is_alarm 本體**以保
        sentinel/portability『只用 golden、零行為改變』契約 → 改以本方法承載聯集語義）。

        韌性（fail-safe，與 runner 既有 try/except 同口徑）：fwer 較貴且可能因校準不足（golden 太小）/
        數值問題拋例外 → 退回 is_alarm 快路徑結果並 ``warn``（寧可少 fwer leg 也不讓線上判決崩；不確定性
        surface 不靜默，Rule 12）。短路：is_alarm 已 True 時聯集必 True，不再花 fwer 成本（Rule 6）。

        Args:
            X: 待評窗 (n, p)。
            compute_fwer: False → 只跑 is_alarm 快路徑（省 permutation/bootstrap，Rule 6）。
            alpha: fwer 的 FWER 水準（None→config.fwer_alpha）。
            _pvalues: **內部優化**——呼叫端（如 runner 需 p-value 作工程師視圖展示）已算好 ``fwer_pvalues``
                時傳入避免重算；一般呼叫端勿用、留 None 由本方法自算。

        Returns:
            bool（任一軌告警即 True）。
        """
        base = bool(self.is_alarm(X))
        if base or not compute_fwer:
            return base  # 已告警（聯集必 True）或關閉 fwer → 不花 fwer 成本
        try:
            return self.fwer_alarm(X, alpha=alpha, _pvalues=_pvalues)
        except Exception:  # fwer 校準/數值失敗 → 退回 is_alarm（fail-safe），surface 不靜默
            warnings.warn(
                "fwer 計算失敗，alarm() 退回 is_alarm 快路徑（本窗少 FWER leg）",
                RuntimeWarning,
                stacklevel=2,
            )
            return base


def _holm_reject(pvalues: dict[str, float], alpha: float) -> dict[str, bool]:
    """Holm–Bonferroni step-down：回傳每層是否拒絕虛無，使族系錯誤率（FWER）≤ alpha。

    程序：p 升序 p_(1)≤..≤p_(m)；依序檢定 p_(i) ≤ alpha/(m−i+1)，一旦某層不過即停止拒絕其後所有層。
    不變式：在所有虛無皆真（golden）時，P(任一被拒) ≤ alpha（單一決策點的 FWER 控制，紅隊 N2）。
    """
    items = sorted(pvalues.items(), key=lambda kv: kv[1])  # p 升序
    m = len(items)
    reject: dict[str, bool] = {}
    still = True
    for i, (k, p) in enumerate(items):
        still = still and (p <= alpha / (m - i))
        reject[k] = still
    return reject


def detect_reentry_campaigns(dataset: ProcessDataset, *, golden_grade: str = "A") -> list[int]:
    """偵測 re-entry campaign：grade==golden_grade 且其前一個 campaign 為**非** golden_grade。

    即「**換產品**後第一段 A」；第一個 golden campaign 不算 re-entry。需先經 preprocess.segment
    填入 campaign_id/grade_label。

    範圍誠實標記（Rule 12）：僅偵測 **grade 切換型** re-entry。**維修型**（同 grade A 中停機，
    mode=maintenance）不換 grade、campaign 不切分，本函式**抓不到**——待 maintenance 資料就緒
    時以 MODE 切分擴充（M-later TODO）。

    Returns: re-entry campaign_id 清單（依出現順序）。
    """
    fr = dataset.frame
    grades = fr.groupby(CAMPAIGN_ID)[GRADE_LABEL].first().sort_index()
    reentry: list[int] = []
    prev = None
    for cid, g in grades.items():
        if g == golden_grade and prev is not None and prev != golden_grade:
            reentry.append(int(cid))
        prev = g
    return reentry
