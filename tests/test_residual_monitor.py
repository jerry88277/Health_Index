"""殘差 Y 漂移監控 WHY 測試（Rule 9，設計 §7/§10-4；G2 偵測線）。

marquee WHY——殘差 e=y−ŷ 的獨特價值＝**分離兩種情境**（G1 做不到）：
- 「製程移動、映射完好」：X 與 y 一起移（y 仍跟著 X）→ raw-Y 監控（G1）會響，**殘差必須安靜**
  ——此時該查製程，不是模型/量測關係。
- 「X→Y 關係斷裂」：X 分佈沒變、y 卻逐漸偏離 ŷ → **殘差必須響**（G2：接歸因查哪個 X）。
護欄：null 用 CV+ **out-of-fold 有號殘差**（in-sample null 偏窄→誤報，誠實分級 null_kind）；
**不對殘差差分**（Kaneko&Funatsu TD 會把漂移抵消——差分正是本監控的反面）；未量測≠正常。
"""

import numpy as np
import pytest

from health_index.batch_avm.mapping import fit_batch_model
from health_index.batch_avm.residual import fit_residual_monitor, score_residuals
from health_index.y_history import YHistoryMonitor

_COLS = [f"p{i}" for i in range(6)]


def _golden(n=80, seed=0):
    rng = np.random.default_rng(seed)
    X = rng.normal(size=(n, 6))
    y = 3.0 * X[:, 0] + 0.1 * rng.normal(size=n)
    return X, y


def test_mapping_break_alarms_residual():
    Xg, yg = _golden()
    m = fit_batch_model(Xg, yg, columns=_COLS)
    rm = fit_residual_monitor(m, Xg, yg)
    rng = np.random.default_rng(1)
    Xq = rng.normal(size=(120, 6))                        # X 分佈沒變
    creep = np.linspace(0.0, 0.8, 120)                    # y 逐漸偏離映射（8×σe）
    yq = 3.0 * Xq[:, 0] + 0.1 * rng.normal(size=120) + creep
    res = score_residuals(rm, m, Xq, yq)
    assert res["summary"]["alarm"] is True
    assert res["channel"] == "residual(G2)"


def test_process_move_with_intact_mapping_stays_quiet_but_g1_fires():
    # 分離性：X 整體移 +2（製程移動），y 完全跟著映射 → 殘差安靜；raw-Y（G1 視角）則會響。
    Xg, yg = _golden(seed=2)
    m = fit_batch_model(Xg, yg, columns=_COLS)
    rm = fit_residual_monitor(m, Xg, yg)
    rng = np.random.default_rng(3)
    Xq = rng.normal(size=(100, 6))
    Xq[:, 0] += 2.0                                       # 製程移動
    yq = 3.0 * Xq[:, 0] + 0.1 * rng.normal(size=100)      # 映射完好
    res = score_residuals(rm, m, Xq, yq)
    assert res["summary"]["alarm"] is False               # 殘差安靜＝關係沒斷
    g1 = YHistoryMonitor().fit(yg).score(yq)
    assert g1["summary"]["alarm"] is True                 # raw-Y 視角：製程確實移了


def test_null_kind_prefers_cv_out_of_fold():
    Xg, yg = _golden()
    m = fit_batch_model(Xg, yg, columns=_COLS)            # n=80 ≥ cv_plus_min_obs → CV+ 可用
    rm = fit_residual_monitor(m, Xg, yg)
    assert rm.null_kind == "cv_oof"                       # out-of-fold 有號殘差（誠實 null）


def test_unmeasured_positions_preserved():
    Xg, yg = _golden(seed=4)
    m = fit_batch_model(Xg, yg, columns=_COLS)
    rm = fit_residual_monitor(m, Xg, yg)
    rng = np.random.default_rng(5)
    Xq = rng.normal(size=(30, 6))
    yq = 3.0 * Xq[:, 0] + 0.1 * rng.normal(size=30)
    yq[::3] = np.nan                                      # 每三批一筆未量測
    res = score_residuals(rm, m, Xq, yq)
    pts = res["points"]
    assert len(pts) == 30
    assert pts[0]["y"] is None and pts[1]["y"] is not None  # 位置保留、未量測不評


def test_fail_loud_when_golden_y_insufficient():
    rng = np.random.default_rng(6)
    X = rng.normal(size=(30, 6))
    y = 3.0 * X[:, 0] + 0.1 * rng.normal(size=30)
    y[10:] = np.nan                                       # 有限 y 僅 10 筆 < g1_min_golden
    m = fit_batch_model(X, y, columns=_COLS)
    with pytest.raises(ValueError, match="歷史"):
        fit_residual_monitor(m, X, y)


def test_deterministic():
    Xg, yg = _golden(seed=7)
    m = fit_batch_model(Xg, yg, columns=_COLS)
    rm = fit_residual_monitor(m, Xg, yg)
    rng = np.random.default_rng(8)
    Xq = rng.normal(size=(40, 6))
    yq = 3.0 * Xq[:, 0] + 0.1 * rng.normal(size=40)
    assert score_residuals(rm, m, Xq, yq) == score_residuals(rm, m, Xq, yq)
