"""G2/G3 X 歸因 WHY 測試（Rule 9，風險稽核 rank-3 must-fix）。

marquee WHY：G2＝「Y 漂移→**哪個製程參數**」、G3＝「Ŷ 越域→哪個參數推出去的」。既有 SPE-RBC
答的是「哪個 X 破壞了 X 共變結構」——**另一個問題**；誤用＝指錯儀器、比不歸因更糟。本模組：
(a) G2 用**敏感度×偏移**（∂ŷ/∂x_j·Δx_j，central-diff，PLS 線性下精確）——歸因到 Y 的變化；
(b) G3 用 T²/SPE **逐變數貢獻分解**——歸因到域的離開；
(c) **precision@1 真值測試**：注入已知單變數肇因，top-1 必須命中（只驗排序遞減的測試會讓
    「永遠指錯」也綠燈——Rule 9 反例）；
(d) **confidence gate**：X* 離建模域→敏感度線性化不可信→reliable=False（誠實，不硬給）；
(e) 降維模型→誠實 None（降維空間無法命名 param×stat）。
"""

import numpy as np
import pytest

from health_index.batch_avm.attribution import domain_exit_attribution, y_event_attribution
from health_index.batch_avm.mapping import fit_batch_model


_COLS = ["a__mean", "a__std", "b__mean", "b__std", "c__mean", "c__std"]


def _model(n=80, seed=0, wide=False):
    """y 幾乎只由 a__mean 決定（真值肇因已知）。wide=True → p=40 觸發 PLS。"""
    rng = np.random.default_rng(seed)
    if wide:
        p = 40
        cols = [f"p{i // 2}__{'mean' if i % 2 == 0 else 'std'}" for i in range(p)]
        X = rng.normal(size=(n, p))
        y = 3.0 * X[:, 0] + 0.1 * rng.normal(size=n)   # 肇因 = p0__mean
        return fit_batch_model(X, y, columns=cols), X, cols[0]
    X = rng.normal(size=(n, len(_COLS)))
    y = 3.0 * X[:, 0] + 0.1 * rng.normal(size=n)        # 肇因 = a__mean
    return fit_batch_model(X, y, columns=_COLS), X, "a__mean"


def test_g2_precision_at_1_pls():
    m, X, truth_feat = _model(wide=True)
    assert m.mapping_kind == "pls"
    q = X.mean(axis=0).copy()
    q[0] += 2.0                                          # Y 漂移的真因：p0__mean 偏移
    r = y_event_attribution(m, q)
    assert r["reliable"] is True
    assert r["top_feature"] == truth_feat                # precision@1（feature 級）
    assert r["top_param"] == truth_feat.split("__")[0]   # param 級（使用者要的顆粒度）
    assert r["delta_yhat"] > 1.0                          # 歸因對象＝Ŷ 的變化量


def test_g2_precision_at_1_gpr():
    m, X, truth_feat = _model()
    assert m.mapping_kind == "gpr"
    q = X.mean(axis=0).copy()
    q[0] += 1.0
    r = y_event_attribution(m, q)
    assert r["top_feature"] == truth_feat and r["top_param"] == "a"


def test_g2_contributions_sum_matches_delta_for_linear():
    # PLS 線性 → Σ貢獻 ≈ ŷ(x)−ŷ(x̄golden)（精確性檢查；GPR 為局部線性化、以 gap 誠實揭露）
    m, X, _ = _model(wide=True)
    q = X.mean(axis=0) + 0.5
    r = y_event_attribution(m, q)
    total = sum(c["contribution"] for c in r["ranking"])
    assert abs(total - r["delta_yhat"]) <= 0.05 * max(1.0, abs(r["delta_yhat"]))
    assert r["linearization_gap"] <= 0.05


def test_g2_confidence_gate_off_domain():
    # X* 遠離建模域 → 線性化/外推不可信 → reliable=False（指錯比不指糟）
    m, X, _ = _model(wide=True)
    q = X.mean(axis=0) + 25.0
    r = y_event_attribution(m, q)
    assert r["reliable"] is False and "離建模域" in r["note"]


def test_g3_domain_exit_names_offending_feature():
    m, X, _ = _model()                                   # p=6、n=80 → 全空間（可歸因）
    q = X.mean(axis=0).copy()
    q[2] += 6.0                                          # b__mean 把批推出域
    r = domain_exit_attribution(m, q)
    assert r["available"] is True and r["anomaly"] is True
    assert r["top_feature"] == "b__mean" and r["top_param"] == "b"
    t2_c = r["t2_contributions"]
    assert abs(sum(c["contribution"] for c in t2_c) - r["t2"]) < 1e-6 * max(1.0, r["t2"])  # 完整分解


def test_g3_honest_none_when_reduced():
    rng = np.random.default_rng(3)
    X = rng.normal(size=(30, 80))
    y = X[:, 0] + 0.1 * rng.normal(size=30)
    m = fit_batch_model(X, y)                            # n<p → 預投影 → 不可命名
    assert m.reduced_ is True
    r = domain_exit_attribution(m, X.mean(axis=0) + 6.0)
    assert r["available"] is False and "降維" in r["note"]


def test_attribution_deterministic():
    m, X, _ = _model(wide=True)
    q = X.mean(axis=0) + 1.0
    assert y_event_attribution(m, q) == y_event_attribution(m, q)
    assert domain_exit_attribution(m, q) == domain_exit_attribution(m, q)
