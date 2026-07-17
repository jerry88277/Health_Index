"""#5 映射模型比較 + conformal coverage CV harness WHY 測試（Rule 9）。

marquee WHY：本 harness 的價值＝**無洩漏**地回答「哪個映射模型更準」與「CV+ 帶是否真達覆蓋」。
測試鎖住三件本模組存在的理由：
(a) 模型比較是 **out-of-fold**——一個「背訓練資料」的估計器 in-sample RMSE≈0，但 harness 必須
    回報接近 std(y) 的誤差（若誤打 in-sample 分數＝假綠，測試要失敗）；
(b) conformal coverage 用**誠實 1−2α 底線**（非 split-CP 的 1−α），且量的是 held-out 覆蓋；
(c) nested CV 給**無偏選擇估計**——不得被 in-sample 完美的過擬合模型騙（選錯＝外層誤差爆高）。
確定性（Rule 5）：同輸入同輸出。
"""

import numpy as np
import pytest

from health_index.config import DEFAULT
from health_index.detectors.soft_sensor import make_soft_sensor
from health_index.validation.cv_harness import (
    compare_models,
    conformal_coverage,
    format_report,
    nested_cv_selection,
    repeated_kfold_score,
)


class _OLS:
    """輕量確定性線性估計器（測試用；泛化良好）。"""

    def fit(self, X, y):
        A = np.c_[np.ones(len(X)), X]
        self.coef_, *_ = np.linalg.lstsq(A, np.asarray(y, float), rcond=None)
        return self

    def predict(self, X):
        return np.c_[np.ones(len(X)), np.asarray(X, float)] @ self.coef_


class _Memorizer:
    """背訓練點的過擬合估計器：in-sample 完美、未見點回傳訓練均值（out-of-fold 慘）。"""

    def fit(self, X, y):
        self._m = {tuple(np.round(r, 6)): float(v) for r, v in zip(np.asarray(X, float), np.asarray(y, float))}
        self._mean = float(np.mean(y))
        return self

    def predict(self, X):
        return np.array([self._m.get(tuple(np.round(r, 6)), self._mean) for r in np.asarray(X, float)])


def _data(n=120, p=5, seed=0, noise=0.1):
    rng = np.random.default_rng(seed)
    X = rng.normal(size=(n, p))
    y = 2.0 * X[:, 0] + 0.5 * X[:, 1] + noise * rng.normal(size=n)
    return X, y


def test_score_is_out_of_fold_not_in_sample():
    # WHY(a)：背資料的估計器 in-sample RMSE≈0；harness 須揭穿其 out-of-fold 誤差≈std(y)。
    X, y = _data()
    s = repeated_kfold_score(lambda: _Memorizer(), X, y, k=5, repeats=2, label="memorizer")
    assert s.rmse > 0.5 * float(np.std(y))   # 遠非 0 → 確為 out-of-fold（誤打 in-sample 會 ≈0）


def test_compare_ranks_generalizing_model_above_overfitter():
    # WHY(a 續)：泛化的 OLS 應勝過只會背的 Memorizer（out-of-fold 語意下）。
    X, y = _data()
    r = compare_models({"ols": lambda: _OLS(), "memorizer": lambda: _Memorizer()}, X, y, k=5, repeats=2)
    assert r["best"] == "ols"
    assert r["scores"]["ols"].rmse < r["scores"]["memorizer"].rmse


def test_conformal_coverage_honest_floor_and_held_out():
    # WHY(b)：coverage 底線＝1−2α（誠實，非 1−α）；held-out 覆蓋須達底線且帶寬>0。
    X, y = _data(n=150)
    cov = conformal_coverage(lambda: _OLS(), X, y, outer_k=5)
    assert cov["floor"] == pytest.approx(1.0 - 2.0 * DEFAULT.cp_alpha)   # 0.80，非 0.90
    assert cov["nominal"] == pytest.approx(1.0 - DEFAULT.cp_alpha)       # 揭示但不宣稱
    assert cov["achieved"] >= cov["floor"]                              # held-out 覆蓋達底線
    assert cov["mean_width"] > 0 and cov["n_eval"] > 0


def test_nested_cv_not_fooled_by_overfitter():
    # WHY(c)：nested 選擇須無偏——inner CV 洩漏會選到 in-sample 完美的 Memorizer → 外層誤差爆高。
    X, y = _data(noise=0.1)
    r = nested_cv_selection({"ols": lambda: _OLS(), "memorizer": lambda: _Memorizer()},
                            X, y, outer_k=5, inner_k=4, repeats=1)
    assert r["selection_counts"]["ols"] >= r["selection_counts"].get("memorizer", 0)  # 多數選對
    assert r["mean_rmse"] < 0.5 * float(np.std(y))   # 選對→外層誤差低（洩漏選錯會≈std(y)）


def test_repeats_produce_distinct_partitions_and_distinct_point_count():
    # WHY（紅隊 must-fix）：舊版 offset 旋轉只重命名 fold 標籤→分割不變(no-op)、rmse_std≡0、n_eval 虛增。
    # 修正後 repeats 須產生**不同折分割**，且 n_eval=distinct 點數 n（非 n×repeats）。
    from health_index.validation.cv_harness import _fold_of

    n, k = 120, 5
    def part(f):  # 分割＝各折成員集合（與 fold 標籤命名無關）
        return frozenset(frozenset(np.where(f == j)[0].tolist()) for j in range(k))
    assert part(_fold_of(n, k, 0)) != part(_fold_of(n, k, 1))  # 分割確實不同（非 no-op 重命名）
    X, y = _data()
    s = repeated_kfold_score(lambda: _OLS(), X, y, k=k, repeats=3)
    assert s.n_eval == len(y)  # distinct 點數，非 n×repeats（不重複計數）


def test_deterministic():
    # WHY（Rule 5）：折分配確定性（index 旋轉，無 RNG）→ 同輸入同輸出。
    X, y = _data(seed=3)
    a = repeated_kfold_score(lambda: _OLS(), X, y, k=5, repeats=3)
    b = repeated_kfold_score(lambda: _OLS(), X, y, k=5, repeats=3)
    assert a.rmse == b.rmse and a.mae == b.mae and a.per_repeat_rmse == b.per_repeat_rmse


def test_integration_real_soft_sensors_and_report():
    # WHY：真映射基底（GPR/PLS 工廠）可走通，且報告含兩模型與覆蓋列（端到端不炸）。
    X, y = _data(n=90, p=6, seed=1)
    cands = {"gpr": lambda: make_soft_sensor(DEFAULT, n_samples=len(y), n_features=X.shape[1]),
             "pls_hi": lambda: make_soft_sensor(DEFAULT, n_samples=2000, n_features=X.shape[1])}
    r = compare_models(cands, X, y, k=4, repeats=1)
    cov = conformal_coverage(cands["gpr"], X, y, outer_k=4)
    rep = format_report(r, cov)
    assert "gpr" in rep and "pls_hi" in rep and "1−2α" in rep
    assert r["best"] in ("gpr", "pls_hi") and 0.0 <= cov["achieved"] <= 1.0
