"""G3 正式適用域（AD，advisory）：leverage(hat-matrix) + 宣告 Ŷ 有效範圍。

取代 T²/SPE 代理（那量 X 共變結構，不量預測外推/Ŷ 範圍）。兩個**正交**訊號：
- **leverage** h(x)=1/n + x_s^T (Xs^T Xs)^+ x_s（標準化特徵空間，pinv 容 p≥n）；限
  h*=3(rank+1)/n（QSAR 慣例）——X 結構外推。註：p≥n 時 lev_limit>1、leverage 幾乎不觸發
  （`leverage_informative=False` 誠實標），此時 Ŷ-範圍 carry G3。
- **宣告 Ŷ 有效範圍** [y_min,y_max]（golden y ±margin）——**T²/SPE 完全偵測不到的響應空間外推**。
G3 觸發＝leverage 超限 OR Ŷ 出範圍；歸因＝leverage 逐特徵貢獻（param 級聚合）。
確定性（無 RNG）；隔離：屬 batch_avm 套件，主告警路徑不得 import。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..config import DEFAULT, Config


def _param_of(feature: str) -> str:
    return feature.rsplit("__", 1)[0] if "__" in feature else feature


@dataclass
class ApplicabilityDomain:
    """已凍結的 AD（leverage 幾何 + Ŷ 範圍）。以 `fit_applicability` 建構。"""

    x_mean_: np.ndarray
    x_std_: np.ndarray
    Ginv_: np.ndarray      # (Xs^T Xs)^+（p_kept×p_kept）
    n_: int
    rank_: int
    lev_limit_: float      # 3(rank+1)/n
    y_min_: float
    y_max_: float
    columns_: list


def fit_applicability(model, Xstar_golden, y_golden, *, y_margin: float = 0.05, config: Config = DEFAULT) -> ApplicabilityDomain:
    """以 golden (X*, y) 建 AD：leverage 幾何（pinv Gram）+ Ŷ 有效範圍。

    Raises:
        ValueError: golden 有限 y < 2 或範圍退化（無法定義 Ŷ 有效範圍）。
    """
    Xk = model._kept(np.asarray(Xstar_golden, dtype=float))
    ss = model.ss_
    Xs = (Xk - ss.x_mean_) / ss.x_std_
    n = Xs.shape[0]
    Ginv = np.linalg.pinv(Xs.T @ Xs)
    rank = int(np.linalg.matrix_rank(Xs))
    lev_limit = 3.0 * (rank + 1) / n
    y = np.asarray(y_golden, dtype=float)
    y = y[np.isfinite(y)]
    if y.size < 2 or float(y.max() - y.min()) < 1e-12:
        raise ValueError("golden 有限 Y 範圍退化（<2 筆或全同），無法定義 Ŷ 有效範圍（Rule 12 不假評）")
    yr = float(y.max() - y.min())
    cols = [model.columns_[i] for i in model.kept_idx_]
    return ApplicabilityDomain(
        x_mean_=np.asarray(ss.x_mean_, dtype=float).copy(),
        x_std_=np.asarray(ss.x_std_, dtype=float).copy(),
        Ginv_=Ginv, n_=int(n), rank_=rank, lev_limit_=float(lev_limit),
        y_min_=float(y.min() - y_margin * yr), y_max_=float(y.max() + y_margin * yr), columns_=cols,
    )


def applicability_check(ad: ApplicabilityDomain, model, Xstar) -> dict:
    """對每批算 leverage 與 Ŷ-範圍，判 G3 適用域與逐批 leverage 歸因。

    Returns:
        dict：per_batch（leverage/leverage_over/yhat/yhat_in_range/g3_alarm/reason/top_param/
        top_feature）、summary（lev_limit/y_range/rank/n_g3_alarm/leverage_informative）、is_advisory。
    """
    Xk = model._kept(np.asarray(Xstar, dtype=float))
    Xs = (Xk - ad.x_mean_) / ad.x_std_
    proj = Xs @ ad.Ginv_
    lev = 1.0 / ad.n_ + np.einsum("ij,ij->i", Xs, proj)     # 逐批 leverage
    lev_over = lev > ad.lev_limit_
    yhat = np.asarray(model.ss_.predict(Xk), dtype=float).ravel()
    in_range = (yhat >= ad.y_min_) & (yhat <= ad.y_max_)
    g3 = lev_over | (~in_range)
    contrib = Xs * proj                                     # 逐特徵 leverage 貢獻
    per_batch = []
    for i in range(len(Xk)):
        top = ad.columns_[int(np.argmax(np.abs(contrib[i])))] if g3[i] else None
        reason = "＋".join(filter(None, ["leverage" if lev_over[i] else "", "Ŷ範圍" if not in_range[i] else ""])) or "域內"
        per_batch.append({
            "leverage": float(lev[i]), "leverage_over": bool(lev_over[i]),
            "yhat": float(yhat[i]), "yhat_in_range": bool(in_range[i]),
            "g3_alarm": bool(g3[i]), "reason": reason,
            "top_param": _param_of(top) if top else None, "top_feature": top,
        })
    return {"per_batch": per_batch, "is_advisory": True, "summary": {
        "lev_limit": float(ad.lev_limit_), "y_range": [ad.y_min_, ad.y_max_], "rank": ad.rank_,
        "n_g3_alarm": int(g3.sum()), "leverage_informative": bool(ad.lev_limit_ <= 1.0),
    }}
