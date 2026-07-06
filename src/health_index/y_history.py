"""G1 純 Y-vs-歷史隱性漂移監控（獨立輕量模組；CLAUDE.md Rule 2 明載例外）。

定義（使用者 2026-07-02）：監控**真實量測 Y** 是否相對**歷史 Y** 開始偏移——**獨立於製程參數 X
與 Control-Limit spec**（重點＝管制限內的緩慢偏移，單點 SPC 抓不到）。結構性保證 X-獨立：
本模組 API 只吃 y、只 import numpy/scipy/config（測試鎖）。**不進主 HealthIndex 融合**——G1 是
獨立告警通道（與 G3 同窗共發＝兩封信，SMTP 串接暫緩）。

兩層濾網（使用者 YI/色相例）＋緩漂偵測：
- **CUSUM 層（緩漂主力）**：對 robust 標準化 z=(y−median)/MADσ 累積 C±（allowance k、決策區間 h，
  config g1_*）；報警時以「C± 最後歸零點」估**起漂時點**（可行動：何時開始漂）。
- **KS 分布層（3–5 筆滑窗）**：新 Y 累積到 g1_ks_window 筆 → two-sample KS vs 歷史 Y；
  p < g1_ks_alpha 且**連續 g1_ks_persistence 窗顯著**才報警（抓 step/再校正位移；持續性濾波
  是滑動多重比較的第一道治理——平穩序列跑數百窗必偶發單窗顯著，RED 實測抓到）。誠實標：
  正式 ARL/誤報治理隨驗收指標階段（使用者定調暫緩）。
- 單點 z 一併回報（資訊用；G1 不設 3σ 硬限——那正是它要超越的）。

確定性（Rule 5）：無 RNG；同輸入同輸出。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.stats import ks_2samp

from .config import DEFAULT, Config


@dataclass
class YHistoryMonitor:
    """fit(歷史 Y) → score(線上 Y 序列)。純 Y、確定性、輕量。"""

    config: Config = field(default=DEFAULT)

    def fit(self, y_golden) -> "YHistoryMonitor":
        """以歷史 Y 建 robust 基準（median/MADσ）並凍結。

        Raises:
            ValueError: 有限歷史 Y < g1_min_golden（不足不假評）。
        """
        y = np.asarray(y_golden, dtype=float)
        y = y[np.isfinite(y)]
        if y.size < self.config.g1_min_golden:
            raise ValueError(f"歷史 Y 僅 {y.size} 筆（< g1_min_golden={self.config.g1_min_golden}），G1 不評")
        self.golden_ = y
        self.med_ = float(np.median(y))
        self.mad_sigma_ = 1.4826 * float(np.median(np.abs(y - self.med_))) + 1e-12
        # h 經驗校準（比照 MSPC 經驗控制限）：MADσ 抽樣誤差會使 z 尺度偏離 1（低估 ~10% 即讓
        # 平穩 Y 的 CUSUM 隨機走破固定 h——RED 實測）。在歷史 Y 自身跑同參數 CUSUM，
        # 取 max(C±)×g1_h_margin 為 h 下限，尺度誤差被自動吸收。
        k = float(self.config.g1_cusum_k)
        cpos = cneg = gmax = 0.0
        for v in y:
            z = (float(v) - self.med_) / self.mad_sigma_
            cpos = max(0.0, cpos + z - k)
            cneg = max(0.0, cneg - z - k)
            gmax = max(gmax, cpos, cneg)
        self.h_eff_ = max(float(self.config.g1_cusum_h), float(self.config.g1_h_margin) * gmax)
        return self

    def score(self, y_online) -> dict:
        """對線上 Y 序列逐筆算 CUSUM/KS 兩層與 G1 判定（NaN＝未量測，跳過但保留位置）。

        Returns:
            dict：points（y/z/cusum_pos/cusum_neg/ks_p/ks_alarm/cusum_alarm/g1_alarm，未量測
            點各值 None）、summary（alarm/first_alarm_idx/onset_idx/direction/n_measured/note）。
        """
        if not hasattr(self, "golden_"):
            raise RuntimeError("須先呼叫 fit()")
        cfg = self.config
        y = np.asarray(y_online, dtype=float)
        k, h = float(cfg.g1_cusum_k), float(self.h_eff_)  # h＝config 下限與 golden 經驗校準取大
        cpos = cneg = 0.0
        pos_reset = neg_reset = 0        # C± 最後歸零的量測序位（onset 估計）
        ks_run = 0                       # 連續顯著 KS 窗計數（持續性濾波）
        window: list[float] = []
        points: list[dict] = []
        first_alarm = None
        onset = None
        direction = None
        measured = 0
        for i in range(len(y)):
            if not np.isfinite(y[i]):
                points.append({"y": None, "z": None, "cusum_pos": None, "cusum_neg": None,
                               "ks_p": None, "ks_alarm": False, "cusum_alarm": False, "g1_alarm": False})
                continue
            measured += 1
            z = (float(y[i]) - self.med_) / self.mad_sigma_
            cpos = max(0.0, cpos + z - k)
            cneg = max(0.0, cneg - z - k)
            if cpos == 0.0:
                pos_reset = i
            if cneg == 0.0:
                neg_reset = i
            cusum_alarm = cpos > h or cneg > h
            window.append(float(y[i]))
            if len(window) > cfg.g1_ks_window:
                window.pop(0)
            ks_p = None
            ks_alarm = False
            if len(window) >= cfg.g1_ks_window:
                ks_p = float(ks_2samp(np.asarray(window), self.golden_).pvalue)
                ks_run = ks_run + 1 if ks_p < cfg.g1_ks_alpha else 0
                ks_alarm = ks_run >= cfg.g1_ks_persistence  # 連續 k 窗顯著才算（濾偶發）
            g1 = bool(cusum_alarm or ks_alarm)
            if g1 and first_alarm is None:
                first_alarm = i
                direction = "up" if (cpos > h or (ks_alarm and np.mean(window) > self.med_)) else "down"
                onset = pos_reset if cpos >= cneg else neg_reset
            points.append({"y": float(y[i]), "z": float(z), "cusum_pos": float(cpos), "cusum_neg": float(cneg),
                           "ks_p": ks_p, "ks_alarm": bool(ks_alarm), "cusum_alarm": bool(cusum_alarm),
                           "g1_alarm": g1})
        note = ("G1：Y 相對歷史已開始偏移（獨立於 X 與管制限）" if first_alarm is not None
                else "G1：未偵測到 Y-vs-歷史偏移")
        return {"points": points,
                "summary": {"alarm": first_alarm is not None,
                            "first_alarm_idx": first_alarm,
                            "onset_idx": onset,
                            "direction": direction,
                            "n_measured": measured,
                            "note": note},
                "channel": "G1"}
