"""G2/G3 X 歸因（batch-AVM 路徑；風險稽核 rank-3 must-fix 落地）。

兩個**不同**的歸因問題（Rule 7 分開、不混用）：
- **G2（Y 漂移→哪個 X）**：`y_event_attribution`——**敏感度×偏移** c_j=∂ŷ/∂x_j·(x_j−x̄_golden)，
  梯度以 central difference 對映射模型數值求得（PLS 線性下**精確**、Σc=Δŷ；GPR 為局部線性化，
  以 ``linearization_gap`` 誠實揭露）。歸因對象＝**Ŷ 的變化**——這才回答「哪個參數把 Y 推走」；
  既有 SPE-RBC 答的是「哪個 X 破壞 X 共變結構」，是另一個問題（誤用＝指錯儀器）。
- **G3（Ŷ 越適用域→哪個 X）**：`domain_exit_attribution`——T² 完整分解 c_j=x_s,j·(D x_s)_j
  （Σc=T²，D=P_kΛ⁻¹P_kᵀ）＋ SPE 的 RBC 排名；依哪個統計量超限取歸因來源。

誠實護欄（指錯比不指更糟）：
- **confidence gate**：查詢點離建模域（X* MSPC anomaly）→ 敏感度線性化/外推不可信 → reliable=False。
- **降維模型**：預投影空間無法命名 [param×stat] → available=False（不硬給）。
- param 級聚合（`a__mean`+`a__std`→`a`）回答使用者要的顆粒度「哪個**製程參數**」。
輸出全純 Python；確定性（central-diff 步長固定、無 RNG）。
"""

from __future__ import annotations

import numpy as np

_FD_REL = 1e-3  # central-diff 相對步長（× golden 欄標準差；固定 → 確定性）


def _param_of(feature: str) -> str:
    return feature.rsplit("__", 1)[0]


def _rank(cols, contrib) -> list[dict]:
    order = np.argsort(-np.abs(contrib))
    return [{"feature": cols[int(i)], "contribution": float(contrib[int(i)])} for i in order]


def _param_shares(cols, contrib) -> list[dict]:
    agg: dict[str, float] = {}
    for c, v in zip(cols, np.abs(contrib)):
        agg[_param_of(c)] = agg.get(_param_of(c), 0.0) + float(v)
    total = sum(agg.values()) + 1e-300
    return sorted(({"param": k, "share": v / total} for k, v in agg.items()),
                  key=lambda d: -d["share"])


def y_event_attribution(model, xstar_row) -> dict:
    """G2：此批的 Ŷ 相對 golden 基準的變化，逐 [param×stat] 歸因（敏感度×偏移）。

    Args:
        model: `fit_batch_model` 產出的 BatchAvmModel。
        xstar_row: (p,) 單批 X*（與 fit 同欄序；自動套 fit 時的欄遮罩）。

    Returns:
        dict：reliable / delta_yhat / ranking（signed 貢獻、|c| 排序）/ top_feature / top_param /
        param_shares / linearization_gap / method / note。離域時 reliable=False（貢獻仍列供參）。
    """
    x = np.asarray(xstar_row, dtype=float).reshape(1, -1)
    xk = model._kept(x)[0]
    cols = [model.columns_[i] for i in model.kept_idx_]
    ss = model.ss_
    base = ss.x_mean_.astype(float)
    yq = float(np.asarray(ss.predict(xk.reshape(1, -1))).ravel()[0])
    y0 = float(np.asarray(ss.predict(base.reshape(1, -1))).ravel()[0])
    delta = yq - y0

    # central-diff 梯度（在查詢點；PLS 線性 → 梯度全域常數、分解精確）
    h = _FD_REL * (ss.x_std_.astype(float) + 1e-12)
    p = xk.shape[0]
    P = np.repeat(xk.reshape(1, -1), 2 * p, axis=0)
    for j in range(p):
        P[2 * j, j] += h[j]
        P[2 * j + 1, j] -= h[j]
    preds = np.asarray(ss.predict(P)).ravel()
    grad = (preds[0::2] - preds[1::2]) / (2 * h)
    contrib = grad * (xk - base)
    gap = float(abs(contrib.sum() - delta) / max(1.0, abs(delta)))

    # confidence gate：X* 離建模域 → 線性化/外推不可信（GPR 回 prior、PLS 外推無憑）
    z = model._mspc_space(xk.reshape(1, -1))
    off = bool(model.mspc_.is_anomaly(z)[0])
    ranking = _rank(cols, contrib)
    shares = _param_shares(cols, contrib)
    note = ("⚠ 此批 X* 離建模域（T²/SPE 超限）——敏感度歸因不可信，先回 G3 域內診斷" if off
            else f"Ŷ 相對 golden 基準變化 {delta:+.3f}；top 貢獻 {ranking[0]['feature']}")
    return {"reliable": not off, "delta_yhat": float(delta), "ranking": ranking,
            "top_feature": ranking[0]["feature"], "top_param": shares[0]["param"],
            "param_shares": shares, "linearization_gap": gap,
            "method": "sensitivity(central-diff)", "note": note}


def domain_exit_attribution(model, xstar_row) -> dict:
    """G3：此批被哪個 [param×stat] 推出適用域（T² 完整分解 + SPE RBC，依超限來源取排名）。

    Returns:
        dict：available / anomaly / t2 / spe / t2_over / spe_over / t2_contributions /
        spe_rbc / ranking / top_feature / top_param / note。降維模型 available=False（誠實）。
    """
    x = np.asarray(xstar_row, dtype=float).reshape(1, -1)
    xk = model._kept(x)
    if model.reduce_V_ is not None:
        return {"available": False, "anomaly": None, "note":
                "X* 已預投影（高維小 n）——降維空間無法命名 [param×stat]，不歸因（指錯比不指更糟）"}
    cols = [model.columns_[i] for i in model.kept_idx_]
    m = model.mspc_
    t2 = float(m.t2(xk)[0])
    spe = float(m.spe(xk)[0])
    t2_over = t2 > m.t2_lim_
    spe_over = spe > m.spe_lim_
    xs = ((xk - m.mean_) / m.std_)[0]
    D = m.P_k_ @ np.diag(1.0 / m.lam_k_) @ m.P_k_.T
    t2_c = xs * (D @ xs)              # 完整分解：Σ = T²（可為小幅負值，正常）
    spe_rbc = m.rbc_spe(xk)[0]
    src = t2_c if (t2_over and not spe_over) else spe_rbc if (spe_over and not t2_over) \
        else (np.abs(t2_c) / (t2 + 1e-300) + spe_rbc / (spe + 1e-300))  # 兩者皆超→正規化合併
    ranking = _rank(cols, np.asarray(src, dtype=float))
    shares = _param_shares(cols, np.asarray(src, dtype=float))
    anomaly = bool(t2_over or spe_over)
    note = (f"域外（{'T²' if t2_over else ''}{'+' if t2_over and spe_over else ''}{'SPE' if spe_over else ''} 超限）"
            f"；top 推手 {ranking[0]['feature']}" if anomaly else "域內（未超限）——G3 未觸發")
    return {"available": True, "anomaly": anomaly,
            "t2": t2, "spe": spe, "t2_over": bool(t2_over), "spe_over": bool(spe_over),
            "t2_contributions": _rank(cols, t2_c),
            "spe_rbc": _rank(cols, np.asarray(spe_rbc, dtype=float)),
            "ranking": ranking, "top_feature": ranking[0]["feature"], "top_param": shares[0]["param"],
            "note": note}
