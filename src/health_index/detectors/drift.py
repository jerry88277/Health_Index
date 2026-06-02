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
        return self

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

    def mmd_pvalue(self, X_new: np.ndarray, *, block_size: int = 1) -> float:
        """MMD block-permutation p-value（多維；KS 觸發或需多維敏感度時升級用）。"""
        Sn = self._scores(X_new)
        pooled = np.vstack([self.Sg_, Sn])
        n_x = len(self.Sg_)
        obs = self._mmd2(self.Sg_, Sn)
        rng = np.random.default_rng(self.config.random_state)
        B = self.config.perm_B
        count = sum(
            self._mmd2(pooled[(perm := self._block_perm(len(pooled), block_size, rng))[:n_x]], pooled[perm[n_x:]])
            >= obs
            for _ in range(B)
        )
        return (1 + count) / (B + 1)

    def wasserstein_magnitude(self, X_new: np.ndarray) -> float:
        """1D-Wasserstein 量級（對 golden null 標準化的 z-score；跨段可比，紅隊 N5）。

        所有比較皆 **s-vs-s 等樣本、disjoint**（消經驗 Wasserstein 的有限樣本偏差 O(s^{−1/d})，
        否則同分佈段的 z 會隨段長爆走而誤報，紅隊 🔴-1）。每 rep 從 golden 抽兩 disjoint s-樣本：
            null = golden_A vs golden_B；觀測 = golden_A vs X_new 子樣本。s 上限 n//2 使 null 有變異。
        """
        Sn = self._scores(X_new)
        n = len(self.Sg_)
        s = min(len(Sn), n // 2)  # 上限 n//2 → 每 rep 可抽兩 disjoint s-樣本（null 才有變異）
        reps = self.config.w_null_reps
        rng = np.random.default_rng(self.config.random_state)
        obs_list, null = [], []
        for _ in range(reps):
            gi = rng.choice(n, size=2 * s, replace=False)
            ga, gb = self.Sg_[gi[:s]], self.Sg_[gi[s:]]
            null.append(self._sum_wasserstein(ga, gb))
            ni = rng.choice(len(Sn), size=s, replace=False)
            obs_list.append(self._sum_wasserstein(ga, Sn[ni]))
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

    def is_drift(self, X_new: np.ndarray, *, block_size: int = 1) -> bool:
        """分層決策：KS first-pass 廉價篩；觸發則升 MMD 確認（兩者皆顯著才判漂移）。

        取捨（紅隊 Y1）：first-pass 假設漂移會在某 PCA-score 邊際留痕（線性協方差型漂移成立）；
        對「邊際與協方差皆不變、只有高階聯合結構變」的純高階相依漂移，KS 可能漏而 MMD 抓得到
        → 此分層在該情形會漏報。屬成本分層的已知取捨，列 TEP 待驗。M7 融合層宜用 power curve 校準。
        """
        alpha = self.config.ks_alpha
        if self.ks_min_pvalue(X_new) >= alpha:
            return False  # 廉價 first-pass 未觸發 → 非漂移
        return self.mmd_pvalue(X_new, block_size=block_size) < self.config.mspc_alpha
