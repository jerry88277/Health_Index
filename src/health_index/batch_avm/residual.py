"""殘差 Y 漂移監控（G2 偵測線；設計 §7/§10-4，advisory——不入主 HI 融合）。

監控 e=y−ŷ 相對**歷史殘差**的漂移：殘差安靜＝X→Y 關係完好（就算 y 隨 X 移動——那是「製程
移動」，歸 G1/raw-Y 視角）；殘差漂移＝**映射斷裂**（G2：接 `attribution.y_event_attribution`
查哪個參數）。與 G1 互補、**不是 G1**（e 經 ŷ 依賴 X——2026-07-02 使用者裁決明載）。

機制（DRY：復用 `YHistoryMonitor`——殘差也是單變量-vs-歷史，經驗 h 校準自動吸收殘差尺度）：
- **null 分級（誠實）**：優先用 CV+ 的 **out-of-fold 有號殘差**（`cv_resid_signed_`）當歷史
  基準——in-sample 殘差偏窄（過擬合吸走漂移空間）會虛增誤報；CV+ 不可用才退 in-sample
  （``null_kind`` 標示）。
- **域閘（A13 教訓）**：X* 離建模域（fresh MSPC T²/SPE 超限）的批，ŷ 是外推、殘差含模型誤差
  而非真漂移 → **不納入監控**（計數揭露 ``n_off_domain``，改查 X 側/G3）。
- **不對殘差差分**（Kaneko&Funatsu Time-Difference 會抵消漂移——差分正是本監控的反面）。
- 未量測（y=NaN）≠ 正常：位置保留、不評。
自相關校正（ARIMA 白化）依使用者定調隨驗收指標階段——批級殘差相依性弱於逐時刻，Rule 2 先簡。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..config import DEFAULT, Config
from ..y_history import YHistoryMonitor


@dataclass
class ResidualDriftMonitor:
    """已 fit 的殘差監控（monitor＝在歷史殘差上校準的 YHistoryMonitor）。"""

    monitor: YHistoryMonitor
    null_kind: str  # 'cv_oof'（CV+ out-of-fold 有號殘差）| 'in_sample'（偏窄，誠實降級）


def fit_residual_monitor(model, Xstar_golden, y_golden, *, config: Config = DEFAULT) -> ResidualDriftMonitor:
    """以 golden 批的歷史殘差建監控基準（凍結）。

    Args:
        model: `fit_batch_model` 產出的 BatchAvmModel（提供 ŷ 與 CV+ 殘差）。
        Xstar_golden, y_golden: 建模用的 golden (X*, y)（與 fit 同欄序）。

    Raises:
        ValueError: 有限歷史殘差 < g1_min_golden（承 YHistoryMonitor，不足不假評）。
    """
    y = np.asarray(y_golden, dtype=float)
    Xk = model._kept(np.asarray(Xstar_golden, dtype=float))
    ok = np.isfinite(y)
    cv = getattr(model, "cv_", None)
    signed = getattr(cv, "cv_resid_signed_", None) if (cv is not None and getattr(cv, "available", False)) else None
    if signed is not None and len(signed) == int(ok.sum()):
        e_g, null_kind = np.asarray(signed, dtype=float), "cv_oof"
    else:  # 誠實降級：in-sample 殘差偏窄（null 過緊 → 誤報偏高），null_kind 揭露
        pred = np.asarray(model.ss_.predict(Xk[ok]), dtype=float).ravel()
        e_g, null_kind = y[ok] - pred, "in_sample"
    return ResidualDriftMonitor(monitor=YHistoryMonitor(config).fit(e_g), null_kind=null_kind)


def score_residuals(rm: ResidualDriftMonitor, model, Xstar, y) -> dict:
    """對每批算 e=y−ŷ 並監控相對歷史殘差的漂移（域閘先行）。

    Returns:
        dict：points（承 YHistoryMonitor，另加 off_domain）、summary（另加 n_off_domain）、
        channel='residual(G2)'、null_kind。off_domain 批不評（殘差=外推誤差非漂移）。
    """
    X = np.asarray(Xstar, dtype=float)
    yq = np.asarray(y, dtype=float)
    Xk = model._kept(X)
    n = len(Xk)
    ok = np.isfinite(yq)
    off = np.asarray(model.mspc_.is_anomaly(model._mspc_space(Xk)), dtype=bool)  # 域閘（A13）
    e = np.full(n, np.nan)
    use = ok & ~off
    if use.any():
        pred = np.asarray(model.ss_.predict(Xk[use]), dtype=float).ravel()
        e[use] = yq[use] - pred
    res = rm.monitor.score(e)
    for i, p in enumerate(res["points"]):
        p["off_domain"] = bool(off[i])
    s = res["summary"]
    s["n_off_domain"] = int(off.sum())
    extra = f"；⚠ {int(off.sum())} 批 X* 離建模域（殘差不可信、未納入）——先查 X 側（G3）" if off.any() else ""
    s["note"] = (("殘差（X→Y 映射）相對歷史已偏移——接 G2 歸因查哪個參數" if s["alarm"]
                  else "殘差 vs 歷史未偵測到偏移（映射完好）") + extra)
    res["channel"] = "residual(G2)"
    res["null_kind"] = rm.null_kind
    return res
