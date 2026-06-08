"""L4 campaign 級分佈漂移：KS first-pass → MMD；解析 1D-Wasserstein 量級；PSI 供溝通。

依 ``docs/redteam_reconciliation.md`` §4：
- **空間**：PCA 分數空間（decorrelate → 捕捉關係型隱性漂移；per-component 1D 檢定更有意義）。
- **KS-on-score 廉價 1D first-pass**（解析 p-value、零 permutation/調參）→ 觸發或需多維時升 MMD。
- **MMD**：多維 kernel two-sample（RBF, median heuristic bandwidth），**block-permutation** p-value（紅隊 N4）。
- **量級**：解析 1D-Wasserstein，**對 golden-A null 標準化**後才可跨段比較（紅隊 N5）。
- **PSI**：分箱漂移指標，**僅供溝通、不參與顯著性決策**（少量點脆，紅隊）。
- **多重比較**：per-component KS 以 Bonferroni 校正（紅隊 N2）；最終決策點在 M7 融合層。

偵測器確定性（Rule 5）：permutation 固定 random_state。模型在 golden-A fit 後凍結（紅隊 N3）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.spatial.distance import cdist
from scipy.stats import ks_2samp, wasserstein_distance

from ..config import DEFAULT, Config


@dataclass
class DriftDetector:
    """campaign 級分佈漂移偵測：golden-A 上 fit（PCA + null）並凍結。"""

    config: Config = field(default=DEFAULT)

    def fit(self, X_golden: np.ndarray) -> "DriftDetector":
        """建立標準化、PCA、golden 分數、MMD bandwidth 與 Wasserstein 量級的 golden null。"""
        X = np.asarray(X_golden, dtype=float)
        self.mean_ = X.mean(axis=0)
        self.std_ = X.std(axis=0) + 1e-9
        Xs = (X - self.mean_) / self.std_
        cov = np.cov(Xs, rowvar=False)
        eigvals, eigvecs = np.linalg.eigh(cov)
        self.P_ = eigvecs[:, np.argsort(eigvals)[::-1]]
        self.Sg_ = Xs @ self.P_  # golden 分數
        # MMD RBF bandwidth：golden 內配對距離中位數（median heuristic）
        d2 = cdist(self.Sg_, self.Sg_, "sqeuclidean")
        med = np.median(d2[d2 > 0])
        self.gamma_ = 1.0 / (med + 1e-12)
        # block-bootstrap 區塊長度（保序自相關 → 加寬 null；iid → 1 完全向後相容，紅隊驗證）
        self.block_len_ = self._estimate_block_len(self.Sg_[:, 0])
        return self

    def _estimate_block_len(self, series: np.ndarray) -> int:
        """估區塊長度 ℓ：PC1 分數自相關**連續** k 個 lag 落入白噪帶（|ρ(h)| < z/√n）的起始 lag。

        WHY（紅隊驗證的不變式）：iid 資料 ρ_1 即不顯著 → ℓ=1 → 下游退回原 iid null（**統計等價**：
        ≈95% 走 iid 路徑；偶發 ℓ=2 仍受控）；強自相關（連續 TEP，golden PC1 ρ_1≈0.92）→ ℓ>1（實測 ~40）
        → null 改抽連續窗以反映窗級變異，消除「iid null 對自相關過敏 → 健康連續窗誤報」（②根因）。

        紅隊 A#2：用 **連續 k 個 lag 皆落帶** 而非首次穿越——抗非單調/振盪 ACF（如 AR(2)）在某 lag 偶然
        近零就早判去相關、低估 ℓ、加寬不足。單調衰減（TEP AR(1)-like）下兩者等價，故 TEP 行為不變。

        Args: series: golden PC1 分數（時序，須保序；亂序/iid → 自相關≈0 → ℓ=1）。
        Returns: ℓ∈[1, n//4]（cap 確保 null 至少有數個區塊可抽）。
        """
        x = np.asarray(series, dtype=float)
        n = x.shape[0]
        x = x - x.mean()
        denom = float((x * x).sum()) + 1e-12
        thr = self.config.drift_block_z / np.sqrt(n)

        def rho(h: int) -> float:
            return abs(float((x[:-h] * x[h:]).sum()) / denom)

        if rho(1) < thr:
            return 1  # lag-1 即不顯著＝無序列相依（iid）→ ℓ=1（穩健還原 iid 路徑，~95% iid 命中於此）
        cap = max(2, n // 4)
        need = 3  # 有 lag-1 相依時，需連續 need 個 lag 皆落帶才認定去相關（抗非單調 ACF 早穿越）
        run = 0
        for h in range(1, cap):
            if rho(h) < thr:
                run += 1
                if run >= need:
                    return h - need + 1  # 連續落帶段的起始 lag = 有效相依長度
            else:
                run = 0
        return cap

    def _scores(self, X: np.ndarray) -> np.ndarray:
        return ((np.asarray(X, dtype=float) - self.mean_) / self.std_) @ self.P_

    @staticmethod
    def _sum_wasserstein(A: np.ndarray, B: np.ndarray) -> float:
        return float(sum(wasserstein_distance(A[:, j], B[:, j]) for j in range(A.shape[1])))

    def _mmd2(self, A: np.ndarray, B: np.ndarray) -> float:
        """有偏 MMD²（RBF）。"""
        g = self.gamma_
        kab = np.exp(-g * cdist(A, B, "sqeuclidean")).mean()
        kaa = np.exp(-g * cdist(A, A, "sqeuclidean")).mean()
        kbb = np.exp(-g * cdist(B, B, "sqeuclidean")).mean()
        return float(kaa + kbb - 2 * kab)

    @staticmethod
    def _block_perm(n: int, block_size: int, rng: np.random.Generator) -> np.ndarray:
        """block-permutation 索引（block_size=1 即標準 permutation；>1 保短程相依，紅隊 N4）。"""
        nb = int(np.ceil(n / block_size))
        order = rng.permutation(nb)
        return np.concatenate([np.arange(b * block_size, min((b + 1) * block_size, n)) for b in order])

    # ---- 公開指標 ----

    def ks_min_pvalue(self, X_new: np.ndarray) -> float:
        """KS first-pass：per-component KS 的最小 p-value，**Bonferroni 校正**（×維度）。"""
        Sn = self._scores(X_new)
        p = self.Sg_.shape[1]
        pmin = min(ks_2samp(self.Sg_[:, j], Sn[:, j]).pvalue for j in range(p))
        return float(min(pmin * p, 1.0))

    def mmd_pvalue(self, X_new: np.ndarray, *, block_size: int | None = None) -> float:
        """MMD two-sample p-value（多維；KS 觸發或需多維敏感度時升級用）。

        雙路（②修正——非平穩穩健）：
        - **ℓ≤1（iid）**：原 **vs-pool permutation** 檢定（標準 permutation；逐位元相容）。
        - **ℓ>1（保序強自相關，連續 TEP）**：改 **window-vs-window block-bootstrap**——把 X_new 視為一個
          連續窗，比對它與 golden **同長連續窗** 的 MMD，null＝golden 連續窗兩兩 MMD 的分佈。
          理由（實證）：vs-pool 比對「窗 vs 整段 golden 池」在非平穩下對自然操作點漫遊過敏（300 樣本窗
          落在 golden 3000 樣本漫遊範圍內的某點 → 與池平均必不同 → 誤報）；window-vs-window 讓 null 含
          相同的窗級漫遊變異，乾淨連續回歸 p≈0.4（不誤報）、真分佈位移（換產品 B/C）p≈0.005（仍抓）。
          注（誠實標）：obs 取多 rep 平均以降噪、null 為單對 MMD 分佈，屬**篩選統計量**（非嚴格 uniform
          p-value）；紅隊實測型一誤差 ≈6%@α=.05、1.3%@α=.01（近名目、略偏寬，在 B=200 蒙地卡羅噪內），
          決策分離極大（clean p≈0.4 vs B/C 0.005）故穩健，與 ``wasserstein_magnitude`` 同結構（Rule 11）。
        """
        if block_size is None:
            block_size = self.block_len_
        Sn = self._scores(X_new)
        rng = np.random.default_rng(self.config.random_state)
        B = self.config.perm_B
        if block_size <= 1:
            pooled = np.vstack([self.Sg_, Sn])  # iid：vs-pool permutation（原行為）
            n_x = len(self.Sg_)
            obs = self._mmd2(self.Sg_, Sn)
            count = sum(
                self._mmd2(pooled[(perm := self._block_perm(len(pooled), block_size, rng))[:n_x]], pooled[perm[n_x:]])
                >= obs
                for _ in range(B)
            )
            return (1 + count) / (B + 1)
        # block：window-vs-window block-bootstrap（非平穩穩健）
        n = len(self.Sg_)
        s = min(len(Sn), n // 2)
        null, obs_list = [], []
        for _ in range(B):
            a0, b0 = int(rng.integers(0, n - s + 1)), int(rng.integers(0, n - s + 1))
            null.append(self._mmd2(self.Sg_[a0 : a0 + s], self.Sg_[b0 : b0 + s]))
            c0 = int(rng.integers(0, n - s + 1))
            obs_list.append(self._mmd2(self.Sg_[c0 : c0 + s], Sn[:s]))
        obs = float(np.mean(obs_list))
        count = sum(nv >= obs for nv in null)
        return (1 + count) / (B + 1)

    def wasserstein_magnitude(self, X_new: np.ndarray) -> float:
        """1D-Wasserstein 量級（對 golden null 標準化的 z-score；跨段可比，紅隊 N5）。

        所有比較皆 **s-vs-s 等樣本、disjoint**（消經驗 Wasserstein 的有限樣本偏差 O(s^{−1/d})，
        否則同分佈段的 z 會隨段長爆走而誤報，紅隊 🔴-1）。

        雙路（block-bootstrap，②的核心修正）：
        - **ℓ==1（iid，含 synthetic 與 iid 重抽 TEP）**：原 iid disjoint 子抽樣 null（統計等價向後相容）。
        - **ℓ>1（保序強自相關，連續 TEP）**：null 改抽 **連續窗**（block bootstrap），使 null 反映
          窗級自然變異（操作點漫遊＋自相關）。否則 iid null 嚴重低估窗級變異 → 健康連續窗 z 爆高
          誤報（②根因）。代價：對「保邊際的關係飄移」L4 失去鑑別力（該訊號改由 L2 SPE 殘差空間抓，
          已實證）；L4 仍保有對「真分佈位移」（如換產品 B/C 操作點變）的鑑別力。
        """
        Sn = self._scores(X_new)
        n = len(self.Sg_)
        s = min(len(Sn), n // 2)  # 上限 n//2 → 每 rep 可抽兩 disjoint/連續 s-樣本（null 才有變異）
        reps = self.config.w_null_reps
        rng = np.random.default_rng(self.config.random_state)
        obs_list, null = [], []
        if self.block_len_ <= 1:
            for _ in range(reps):  # iid 路徑（原行為，向後相容）
                gi = rng.choice(n, size=2 * s, replace=False)
                ga, gb = self.Sg_[gi[:s]], self.Sg_[gi[s:]]
                null.append(self._sum_wasserstein(ga, gb))
                ni = rng.choice(len(Sn), size=s, replace=False)
                obs_list.append(self._sum_wasserstein(ga, Sn[ni]))
        else:
            for _ in range(reps):  # block 路徑：連續窗 vs 連續窗（保自相關，加寬 null）
                a0, b0 = int(rng.integers(0, n - s + 1)), int(rng.integers(0, n - s + 1))
                ga, gb = self.Sg_[a0 : a0 + s], self.Sg_[b0 : b0 + s]
                null.append(self._sum_wasserstein(ga, gb))
                c0 = int(rng.integers(0, n - s + 1))
                obs_list.append(self._sum_wasserstein(self.Sg_[c0 : c0 + s], Sn[:s]))
        obs = float(np.mean(obs_list))
        return (obs - float(np.mean(null))) / (float(np.std(null)) + 1e-12)

    def psi(self, X_new: np.ndarray, *, bins: int = 10) -> float:
        """PSI（per-component 取最大；**僅供溝通、不入顯著性決策**）。"""
        Sn = self._scores(X_new)
        out = 0.0
        for j in range(self.Sg_.shape[1]):
            edges = np.quantile(self.Sg_[:, j], np.linspace(0, 1, bins + 1))
            edges[0], edges[-1] = -np.inf, np.inf
            pg = np.histogram(self.Sg_[:, j], edges)[0] / len(self.Sg_) + 1e-6
            pn = np.histogram(Sn[:, j], edges)[0] / len(Sn) + 1e-6
            out = max(out, float(np.sum((pn - pg) * np.log(pn / pg))))
        return out

    def is_drift(self, X_new: np.ndarray, *, block_size: int | None = None) -> bool:
        """分層決策：KS first-pass 廉價篩；觸發則升 MMD 確認（兩者皆顯著才判漂移）。

        取捨（紅隊 Y1）：first-pass 假設漂移會在某 PCA-score 邊際留痕（線性協方差型漂移成立）；
        對「邊際與協方差皆不變、只有高階聯合結構變」的純高階相依漂移，KS 可能漏而 MMD 抓得到
        → 此分層在該情形會漏報。屬成本分層的已知取捨，列 TEP 待驗。M7 融合層宜用 power curve 校準。

        block_size=None → MMD 用 ``block_len_``。自相關下 KS first-pass 會過度觸發（型一膨脹）但
        無害：僅多花 MMD 計算，最終決策由 **block-aware MMD** 把關（連續 TEP 實證 clean/drift 皆
        p>α → 不誤報；保邊際關係飄移由 L2 SPE 抓，非 L4）。
        """
        alpha = self.config.ks_alpha
        if self.ks_min_pvalue(X_new) >= alpha:
            return False  # 廉價 first-pass 未觸發 → 非漂移
        return self.mmd_pvalue(X_new, block_size=block_size) < self.config.mspc_alpha
