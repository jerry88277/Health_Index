"""Y（軟量測/品質）健康指標（桶2b）：對稱於 X 側 ``HealthIndex``（L1/L2/L4 on X）。

融合兩個互補的 Y 健康分量 → 單一 0–1（1=Y 健康）：
- **映射健康（map）**：X→Y 軟測量殘差相對可信帶——抓「X→Y 關係斷了」（注入 drift：Y 邊際分布不變
  但 Ŷ 偏離實際 Y）。需窗內有 Y 觀測。
- **分布健康（dist）**：多維品質 Y 的 Y-MSPC（T²/SPE）——抓「品質分布本身變了」（換產品 G/H 比例變）。
  純量品質資料集無此分量。

第一性原理（為何兩者皆需）：Y 可從兩個正交方向變壞——關係斷（map）與分布移（dist）。單看其一會漏：
drift 的 dist 健康、B/C 的 map 可能健康。融合才完整（紅隊實證見 tests）。

決策雙軌（類比 X 側 HealthIndex，但**非完全對稱**——無 FWER/threshold 決策層，誠實標）：
- ``y_health``：加權**均值**梯度分數（與 X 側 health_index 同採均值；資訊性、非安全網）。
- ``y_flagged``：**任一可用分量 < y_flag_threshold** 即 True（安全網，類比 X 側 hard-gate）——抓分量
  塌陷（如換產品 dist→0），即使均值被另一分量稀釋未過閾（紅隊 A1：均值會遮蔽單分量崩）。

誠實標（Rule 12）：分量不可算時回 ``None``（無 Y 觀測 / 無多維品質），融合僅用可用分量、不靜默補 0。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .config import DEFAULT, Config
from .detectors.mspc import MSPCModel
from .detectors.soft_sensor import make_soft_sensor


@dataclass
class YHealthIndex:
    """Y 健康指標：fit(golden X, y[, Yq]) → y_health(window)。融合映射健康 ⊕ 分布健康。"""

    config: Config = field(default=DEFAULT)

    def fit(self, X_golden: np.ndarray, y_golden: np.ndarray, Yq_golden: np.ndarray | None = None) -> "YHealthIndex":
        """以 golden 的 (X, y[, Yq]) 凍結：軟測量（映射）+（多維品質時）Y-MSPC（分布）。

        Args:
            X_golden: (n, p) golden 製程參數。
            y_golden: (n,) golden 軟量測 Y（稀疏，NaN 為未觀測）。
            Yq_golden: (n, q) golden 多維品質（q≥2 才建 Y-MSPC；None/純量→無分布分量）。

        Raises:
            ValueError: golden 有效 (X, y) 觀測不足（軟測量無法訓練）。
        """
        X = np.asarray(X_golden, dtype=float)
        y = np.asarray(y_golden, dtype=float)
        obs = np.isfinite(y)
        self.ss_ = make_soft_sensor(self.config, n_samples=int(obs.sum()), n_features=X.shape[1]).fit(X, y)
        self.ss_.calibrate_cp(X, y)  # in-sample 校準（小標籤；覆蓋為近似，誠實標同 server /softsensor）
        self.y_mspc_ = None
        if Yq_golden is not None:
            Yq = np.asarray(Yq_golden, dtype=float)
            qobs = np.isfinite(Yq).all(axis=1)
            if Yq.ndim == 2 and Yq.shape[1] >= 2 and int(qobs.sum()) >= 2:
                self.y_mspc_ = MSPCModel(self.config).fit(Yq[qobs])
        return self

    def _band_half(self, X: np.ndarray) -> np.ndarray:
        """逐樣本可信帶半寬：CP 可用→常數 cp_q_；否則 2×預測 std（與 /softsensor 同邏輯）。

        已知不連續（紅隊 A2，誠實標）：golden 標籤跨越 cp_min_calibration 門檻使 CP 由不可用↔可用切換時，
        帶寬會跳變（實測 ~+39%）→ map_health 同步跳變。同尺寸但標籤數略差的 golden 可得不同分數；
        屬 split-CP 上線門檻的離散性，非連續校準（後續可改混合/連續帶）。
        """
        if self.ss_.cp_available:
            return np.full(len(X), float(self.ss_.cp_q_))
        _, std = self.ss_.predict(X, return_std=True)
        return 2.0 * std

    def map_health(self, X: np.ndarray, y: np.ndarray) -> float | None:
        """映射健康∈(0,1]：觀測 Y 的殘差相對可信帶——帶內→1，超帶越多越低（exp 衰減）。

        Returns: 健康分數，或 ``None``（窗內 Y 觀測 < y_map_min_obs，不可靠故不算）。
        """
        X = np.asarray(X, dtype=float)
        y = np.asarray(y, dtype=float)
        obs = np.isfinite(y)
        if int(obs.sum()) < self.config.y_map_min_obs:
            return None
        Xo = X[obs]
        yhat = self.ss_.predict(Xo)
        band = self._band_half(Xo)
        ratio = np.abs(y[obs] - yhat) / np.maximum(band, 1e-12)  # 殘差/帶
        excess = float(np.maximum(0.0, ratio - 1.0).mean())       # 超帶部分均值（帶內為 0）
        return float(np.exp(-excess / self.config.y_map_scale))

    def dist_health(self, Yq: np.ndarray | None) -> float | None:
        """分布健康∈[0,1]：1−Y-MSPC 異常率。``None``＝無 Y-MSPC（純量品質）或無觀測。"""
        if self.y_mspc_ is None or Yq is None:
            return None
        Yq = np.asarray(Yq, dtype=float)
        qobs = np.isfinite(Yq).all(axis=1)
        if int(qobs.sum()) == 0:
            return None
        return float(1.0 - self.y_mspc_.is_anomaly(Yq[qobs]).mean())

    def subscores(self, X: np.ndarray, y: np.ndarray, Yq: np.ndarray | None = None) -> dict[str, float | None]:
        """各分量健康（None＝該分量不可算）。"""
        return {"map": self.map_health(X, y), "dist": self.dist_health(Yq)}

    def y_health(self, X: np.ndarray, y: np.ndarray, Yq: np.ndarray | None = None) -> float:
        """融合 0–1 Y 健康（加權平均可用分量）。

        Raises:
            ValueError: 無任何可用分量（窗無足夠 Y 觀測且無多維品質）——不靜默回假值（Rule 12）。
        """
        sm = self.map_health(X, y)
        sd = self.dist_health(Yq)
        wm, wd = self.config.y_fusion_weights
        parts, weights = [], []
        if sm is not None:
            parts.append(sm)
            weights.append(wm)
        if sd is not None:
            parts.append(sd)
            weights.append(wd)
        if not parts:
            raise ValueError("無可用 Y 健康分量（窗內 Y 觀測不足且無多維品質）；無法計算 Y 健康")
        return float(np.average(parts, weights=weights))

    def y_flagged(self, X: np.ndarray, y: np.ndarray, Yq: np.ndarray | None = None) -> bool:
        """安全網旗標（類比 X 側 hard-gate）：**任一可用分量 < y_flag_threshold** 即 True。

        抓單分量塌陷（如換產品 dist→0），即使 ``y_health`` 均值被另一健康分量稀釋未過閾（紅隊 A1）。
        無任何可用分量 → False（不可判，不假陽）。
        """
        sm = self.map_health(X, y)
        sd = self.dist_health(Yq)
        avail = [s for s in (sm, sd) if s is not None]
        return any(s < self.config.y_flag_threshold for s in avail)
