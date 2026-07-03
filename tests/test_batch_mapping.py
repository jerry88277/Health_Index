"""INC-3 batch-AVM 映射模型 + X* MSPC WHY 測試（Rule 9）——精靈第 7/9 關計算核心。

marquee WHY：
- **PLS 主力**：X* 高維共線（模型分析裁決 GPR+PLS+split-CP、零新模型；p>30 路由 PLS）。
- **CV+ 是批次尺度唯一可信帶**：golden 批數（數十~百）遠低於 split-CP 的 cp_min_calibration=200，
  沒有 CV+ 批次路徑就沒有任何有保證的區間。
- **X* MSPC 必須走 highdim 預投影**（整合紅隊 must-fix #7）：naive cov 在 n<p 時奇異、λ floor 1e-12
  → T² 垃圾限。若小 n 寬 X* 不啟動預投影或算出非有限限值，本檔測試必須失敗。
- **RBC 僅在未降維時提供**：降維 score 空間的貢獻無法命名 [param×stat]——誠實回 None 而非錯誤歸因
  （風險稽核：指錯參數比不指更糟）。
"""

import numpy as np

from health_index.batch_avm.mapping import fit_batch_model, score_batches


def _xstar(n, p, seed=0):
    """潛因子共線 X* + 線性 y（chemometrics 典型形態）。"""
    rng = np.random.default_rng(seed)
    Z = rng.normal(size=(n, 3))
    L = rng.normal(size=(3, p))
    X = Z @ L + 0.1 * rng.normal(size=(n, p))
    y = Z @ rng.normal(size=3) + 0.05 * rng.normal(size=n)
    return X, y


def test_pls_selected_for_wide_xstar():
    X, y = _xstar(60, 40)
    m = fit_batch_model(X, y)
    assert m.mapping_kind == "pls"  # p=40>30 → PLS 主力（設計 §5）


def test_cvplus_band_available_at_batch_scale():
    # WHY：n=60 批 << cp_min_calibration=200 → split-CP 必不可用；CV+ 必須可用且區間有限。
    X, y = _xstar(60, 10, seed=1)
    m = fit_batch_model(X, y)
    res = score_batches(m, X)
    s = res["summary"]
    assert s["cv_available"] is True and s["band_kind"] == "CV+"
    assert abs(s["coverage_floor"] - 0.8) < 1e-12  # 誠實 worst-case ≥1−2α，非 ≥1−α
    b0 = res["batches"][0]
    assert b0["band_lo"] is not None and b0["band_hi"] > b0["band_lo"]


def test_mapping_recovers_y_heldout():
    X, y = _xstar(120, 20, seed=2)
    m = fit_batch_model(X[:80], y[:80])
    yhat = np.array([b["yhat"] for b in score_batches(m, X[80:])["batches"]])
    yt = y[80:]
    r2 = 1 - np.sum((yt - yhat) ** 2) / np.sum((yt - yt.mean()) ** 2)
    assert r2 > 0.5


def test_xstar_mspc_flags_shifted_batches():
    # WHY（第 9 關「隱性飄移」訊號）：X* 域偏移批必須被 fresh MSPC 抓到；golden 自身誤報率貼 α。
    X, y = _xstar(80, 12, seed=3)
    m = fit_batch_model(X, y)
    res_g = score_batches(m, X)
    fpr = np.mean([b["anomaly"] for b in res_g["batches"]])
    assert fpr <= 0.05  # 經驗限 α=0.01，容忍餘裕
    shifted = X[:10] + 6.0
    res_s = score_batches(m, shifted)
    hits = sum(b["anomaly"] for b in res_s["batches"])
    assert hits >= 9


def test_highdim_projection_engages_on_wide_small_n():
    # WHY（must-fix #7）：n=30 < p=80 → 必須預投影；限值/分數皆有限，RBC 誠實 None。
    X, y = _xstar(30, 80, seed=4)
    m = fit_batch_model(X, y)
    assert m.reduced_ is True
    res = score_batches(m, X)
    s = res["summary"]
    assert s["reduced"] is True
    assert np.isfinite(s["t2_lim"]) and np.isfinite(s["spe_lim"]) and s["t2_lim"] > 0
    for b in res["batches"]:
        assert np.isfinite(b["t2"]) and np.isfinite(b["spe"])
        assert b["rbc_top"] is None  # 降維空間不歸因（不指錯參數）


def test_rbc_names_offending_param_in_full_space():
    # WHY（第 9 關下鑽「哪個參數」）：全空間時 RBC top 必須命中被注入偏移的參數欄族。
    cols = ["a__mean", "a__std", "a__min", "a__max", "b__mean", "b__std", "b__min", "b__max"]
    X, y = _xstar(80, 8, seed=5)
    m = fit_batch_model(X, y, columns=cols)
    q = X[:6].copy()
    q[:, :4] += 6.0  # 只偏移參數 a 的統計欄
    res = score_batches(m, q)
    tops = [b["rbc_top"] for b in res["batches"] if b["anomaly"]]
    assert len(tops) >= 5
    assert sum(1 for t in tops if t and t.startswith("a__")) >= 4


def test_nan_column_dropped_consistently():
    X, y = _xstar(50, 10, seed=6)
    X[3, 7] = np.nan
    m = fit_batch_model(X, y, columns=[f"c{i}" for i in range(10)])
    assert m.dropped_columns == ["c7"]
    res = score_batches(m, X)  # 同形狀輸入照樣可評（fit 時的欄遮罩自動套用）
    assert len(res["batches"]) == 50


def test_deterministic():
    X, y = _xstar(60, 15, seed=7)
    r1 = score_batches(fit_batch_model(X, y), X)
    r2 = score_batches(fit_batch_model(X, y), X)
    assert r1 == r2
