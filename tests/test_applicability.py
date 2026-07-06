"""G3 正式適用域（AD）WHY 測試（Rule 9，風險稽核 rank-4）。

marquee WHY：G3＝「Ŷ 越出模型認定範圍」。現行只有 T²/SPE 代理（量 X 共變結構），**完全無法**
偵測「Ŷ 落在合理 X 域內卻預測出訓練 Y 範圍外」——那是**響應空間外推**。正式 AD 兩個正交訊號：
(a) leverage h(x)=1/n+x_s^T(Xs^TXs)^+x_s（QSAR 慣例、限 3(rank+1)/n）＝X 結構外推；
(b) **宣告 Ŷ 有效範圍 [y_min,y_max]**＝響應外推（T²/SPE 盲）。G3＝任一觸發；歸因＝leverage 貢獻。
"""

import numpy as np
import pytest

from health_index.batch_avm.applicability import applicability_check, fit_applicability
from health_index.batch_avm.mapping import fit_batch_model, score_batches


def _model(n=60, p=5, seed=0):
    rng = np.random.default_rng(seed)
    X = rng.normal(size=(n, p))
    y = 3.0 * X[:, 0] + 0.1 * rng.normal(size=n)   # y 幾乎只由 c0 決定
    return fit_batch_model(X, y, columns=[f"c{i}" for i in range(p)]), X, y


def test_in_domain_passes():
    m, X, y = _model()
    ad = fit_applicability(m, X, y)
    r = applicability_check(ad, m, X[:10])
    assert all(not b["g3_alarm"] for b in r["per_batch"])
    assert all(b["leverage"] < ad.lev_limit_ and b["yhat_in_range"] for b in r["per_batch"])


def test_structural_extrapolation_flags_leverage_and_names_param():
    m, X, y = _model()
    ad = fit_applicability(m, X, y)
    q = X.mean(axis=0).copy()
    q[2] += 10.0                                     # c2 遠離（高 leverage，但 c2 不影響 y→Ŷ 仍在範圍）
    b = applicability_check(ad, m, q.reshape(1, -1))["per_batch"][0]
    assert b["leverage_over"] is True and b["g3_alarm"] is True
    assert b["yhat_in_range"] is True               # 純 X 結構外推、非響應外推
    assert b["top_param"] == "c2"                   # leverage 貢獻歸因命中


def test_yhat_out_of_range_is_orthogonal_signal():
    m, X, y = _model()
    ad = fit_applicability(m, X, y)
    q = X.mean(axis=0).copy()
    q[0] += 6.0                                      # y=3·c0 → Ŷ≈18 遠超 golden y 範圍（±[~-6,6]）
    b = applicability_check(ad, m, q.reshape(1, -1))["per_batch"][0]
    assert b["yhat_in_range"] is False              # T²/SPE 偵測不到的響應空間外推
    assert b["g3_alarm"] is True


def test_leverage_limit_is_qsar_3p_over_n():
    m, X, y = _model(n=60, p=5)
    ad = fit_applicability(m, X, y)
    assert ad.lev_limit_ == pytest.approx(3.0 * (ad.rank_ + 1) / ad.n_)


def test_fit_fail_loud_on_degenerate_y_range():
    m, X, y = _model()
    with pytest.raises(ValueError, match="Y 範圍"):
        fit_applicability(m, X, np.full(len(y), 5.0))  # y 全同→範圍退化


def test_deterministic():
    m, X, y = _model(seed=3)
    ad = fit_applicability(m, X, y)
    assert applicability_check(ad, m, X[:5]) == applicability_check(ad, m, X[:5])


def test_wired_into_fit_and_score():
    # WHY（must-fix R4 落地）：AD 於 build 時 fit（model.ad_），score_batches 每批帶正式 G3 訊號。
    m, X, y = _model(seed=4)
    assert m.ad_ is not None
    res = score_batches(m, X)
    s = res["summary"]["applicability"]
    assert s is not None and "lev_limit" in s and "y_range" in s and "leverage_informative" in s
    for b in res["batches"]:
        assert "g3_ad_alarm" in b and "leverage" in b and "yhat_in_range" in b
