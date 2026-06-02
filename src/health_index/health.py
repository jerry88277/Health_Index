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
        ncal = n // 3
        mind = self.config.min_samples_per_dim
        if ncal >= mind and (n - ncal) >= 2 * mind:
            perm = np.random.default_rng(self.config.random_state).permutation(n)
            self._fwer_cal_ = G[perm[:ncal]]
            gfit = G[perm[ncal:]]
            self._fwer_dqi_ = DQIxGate(self.config).fit(gfit)
            self._fwer_mspc_ = MSPCModel(self.config).fit(gfit)
            self._fwer_drift_ = DriftDetector(self.config).fit(gfit)
            self._fwer_split_ = True
        else:
            self._fwer_cal_ = G
            self._fwer_dqi_, self._fwer_mspc_, self._fwer_drift_ = self.dqi_, self.mspc_, self.drift_
            self._fwer_split_ = False
            warnings.warn(  # Rule 12 fail loud：退回 in-sample 校準時 FWER 較不保守，須讓呼叫端知道
                f"FWER split 校準停用（golden n={n} 不足 3·min_samples_per_dim）→ 退回 in-sample null，"
                "golden 誤報率控制較不保守（AC-6 不保證 ≤α）。請增大 golden 或降維。",
                RuntimeWarning,
                stacklevel=2,
            )
        self._fwer_ready_ = True

    def subscores(self, X: np.ndarray) -> dict[str, float]:
        """各層 0–1 健康子分數（1=健康；方向統一）。"""
        s_l1 = float(self.dqi_.is_inlier(X).mean())          # 域內樣本比例
        s_l2 = float(1.0 - self.mspc_.is_anomaly(X).mean())  # in-control 樣本比例
        z = float(self.drift_.wasserstein_magnitude(X))
        s_l4 = float(np.exp(-max(z, 0.0) / self.config.drift_scale))  # 漂移越大越低
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
        """
        return bool(self.health_index(X) < self.config.hi_alarm_threshold or any(self.hard_gates(X).values()))

    def fwer_pvalues(self, X: np.ndarray) -> dict[str, float]:
        """各層對 golden-A null 的窗級右尾 p-value（越小越異常）。

        各層用 permutation 兩樣本，使 p-value 在 golden null 下近似 uniform（不受 in-sample 控制限低估
        之累，紅隊 N6）：
        - **L1**：離域指標比例（golden_calib vs X；離散低計數，此 synthetic 下近乎無功效＝恆保守）。
        - **L2**：每樣本 **SPE 均值**（golden_calib vs X；連續統計量，比 0/1 失控率更平滑有力——隱性飄移主訊號）。
        - **L4**：``DriftDetector.mmd_pvalue``（比對 **golden_fit** 分數 ``Sg_`` vs X 的 block-permutation；
          本即自校準 p-value，為三層中**唯一未用 calib split**者——輕微不對稱、已知設計債）。

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
        spe_c = self._fwer_mspc_.spe(cal)
        p2 = self._perm_two_sample(spe_c, spe_x)
        # L4：MMD block-permutation（PCA 分數空間）
        p4 = float(self._fwer_drift_.mmd_pvalue(X))
        return {"L1": float(p1), "L2": float(p2), "L4": p4}

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

    def fwer_alarm(self, X: np.ndarray, *, alpha: float | None = None) -> bool:
        """AC-6 單一決策點：3 層 p-value 經 **Holm 校正**，任一拒絕虛無即告警。

        取代 ``is_alarm`` 的裸 OR（紅隊 N2）：在 golden-A null 下 Holm 保證族系錯誤率（FWER）≤ alpha
        → golden 誤報率受控（AC-6）。``is_alarm``（H8 雙軌硬閘）保留為安全網，兩者語義不同、並存。
        """
        alpha = self.config.fwer_alpha if alpha is None else alpha
        return any(_holm_reject(self.fwer_pvalues(X), alpha).values())


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
