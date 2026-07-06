"""池化 Golden 同質性閘 WHY 測試（Rule 9，設計 §8 / 整合紅隊 must-fix #10）。

marquee WHY：多機台/時段 union 進單一 Golden 會**撐寬基準→降隱性飄移靈敏度**——正好反噬本
專案存在的理由。閘必須：(a) **between-cell 置換檢定**（in-sample 自我參照 T²/SPE 必過＝假閘）；
(b) 異質時 **WARN（非硬擋，使用者定案）** 並指名差異最大的特徵（可行動）；(c) **1-cell＝
trivial pass**（無群可比不得偽造警告）；(d) 小 cell 誠實標低檢定力。若混入 +1σ 偏移機台而
不警告，本檔測試必須失敗。
"""

import numpy as np
import pytest

from health_index.batch_avm.homogeneity import golden_homogeneity_gate


def _cells_x(n_a=20, n_b=20, p=8, shift=0.0, seed=0):
    rng = np.random.default_rng(seed)
    Xa = rng.normal(size=(n_a, p))
    Xb = rng.normal(size=(n_b, p)) + shift
    return np.vstack([Xa, Xb]), ["A"] * n_a + ["B"] * n_b


def test_heterogeneous_cells_warn_and_name_worst_feature():
    X, cells = _cells_x(shift=1.5, seed=1)
    g = golden_homogeneity_gate(X, cells, columns=[f"c{i}" for i in range(8)])
    assert g["applicable"] is True and g["warn"] is True
    assert g["p_value"] <= 0.05
    assert g["max_shift_sigma"] > 1.0
    assert g["worst_feature"].startswith("c")
    assert g["is_advisory"] is True  # WARN-only：不硬擋、不入告警融合


def test_homogeneous_cells_pass():
    X, cells = _cells_x(shift=0.0, seed=2)
    g = golden_homogeneity_gate(X, cells)
    assert g["applicable"] is True and g["warn"] is False


def test_single_cell_is_trivial_no_op():
    X, _ = _cells_x(seed=3)
    g = golden_homogeneity_gate(X, ["A"] * len(X))
    assert g["applicable"] is False and g["warn"] is False
    assert "單一" in g["note"]


def test_small_cell_flags_low_power():
    X, cells = _cells_x(n_a=20, n_b=3, shift=0.0, seed=4)
    g = golden_homogeneity_gate(X, cells)
    assert g["low_power"] is True  # 非拒絕不得讀成「同質」——誠實標檢定力


def test_deterministic():
    X, cells = _cells_x(shift=0.8, seed=5)
    assert golden_homogeneity_gate(X, cells) == golden_homogeneity_gate(X, cells)


def test_fit_batch_model_surfaces_gate_in_summary():
    # WHY（must-fix #10）：閘要在 build 時跑、進治理流（score summary），不是浮動 UI banner。
    from health_index.batch_avm.mapping import fit_batch_model, score_batches

    rng = np.random.default_rng(6)
    n, p = 40, 6
    Z = rng.normal(size=(n, 2))
    X = Z @ rng.normal(size=(2, p)) + 0.1 * rng.normal(size=(n, p))
    X[n // 2:] += 1.2  # 後半＝另一台機台，系統偏移
    y = Z @ np.array([1.0, -0.5]) + 0.05 * rng.normal(size=n)
    cells = ["A"] * (n // 2) + ["B"] * (n // 2)
    m = fit_batch_model(X, y, cells=cells)
    res = score_batches(m, X)
    h = res["summary"]["homogeneity"]
    assert h is not None and h["warn"] is True
    m2 = fit_batch_model(X, y)  # 不給 cells → 閘不評（None），不偽造
    assert score_batches(m2, X)["summary"]["homogeneity"] is None
