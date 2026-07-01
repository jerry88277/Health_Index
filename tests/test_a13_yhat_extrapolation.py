"""Ŷ 外推漏報揭露 WHY 測試（Rule 9；紅隊 A13）。

WHY：X 大幅離建模域（最該擔心的 re-entry）時 GPR 軟測量外推回 prior mean → 預測品質 Ŷ 反趨中、Ŷ-drift z
**縮小** → 過不了門檻 → 隱性品質**漏報**（與直覺相反）。系統不可把「z 小」在外推下當「品質健康」憑據——
須以 confidence（域相似度）標該窗 Ŷ-drift 不可信。當外推窗被靜默當健康時，本測試失敗。
"""

import numpy as np

from health_index.deploy.demo import build_and_save_model, score_timeline


def test_yhat_drift_marked_unreliable_when_extrapolating(tmp_path):
    """X 域外（低 confidence）+ 窗內無足夠實際 Y → 該窗 Ŷ-drift 標不可信、計入 n_quality_unreliable；
    域內窗（高 confidence）則可信。避免 GPR 外推 z 縮小被誤讀為品質穩定。"""
    import pandas as pd

    from health_index.adapters import registry
    from health_index.adapters.dataframe import from_frame

    name = "_a13_extrap"

    def _b(**kw):
        rng = np.random.default_rng(0)
        w = np.array([1.0, 0.5, -0.3])
        Xg = rng.normal(0, 1, (300, 3))      # golden：建模域內
        Xd = rng.normal(6, 1, (300, 3))      # drift：域外（GPR 外推、confidence 崩）
        X = np.vstack([Xg, Xd])
        y = X @ w + rng.normal(0, 0.05, 600)
        ys = y.copy()
        idx = np.arange(600)
        # golden Y dense（供 fit）；drift 段 Y 稀疏（每 60 列才 1 筆 < y_map_min_obs → map_health None）
        ys[(idx >= 300) & (idx % 60 != 0)] = np.nan
        df = pd.DataFrame(X, columns=["a", "b", "c"])
        df["yq"] = ys
        return from_frame(df, x_columns=["a", "b", "c"], y_value="yq", golden=(0, 300), name=name)

    registry.register(name, _b, overwrite=True)
    try:
        r = build_and_save_model(name, golden=(0, 300), models_dir=str(tmp_path), created_at="t")
        tl = score_timeline(r["bundle_path"], name, window=60)
        drift_pts = [p for p in tl["points"] if p["start"] >= 300]
        golden_pts = [p for p in tl["points"] if p["end"] <= 300]
        assert drift_pts and golden_pts
        # 域外窗：Ŷ-drift 判讀不可信（不以 z 縮小當健康）
        assert any(p.get("yhat_drift_reliable") is False for p in drift_pts), "域外窗應標 Ŷ 外推不可信"
        assert tl["n_quality_unreliable"] > 0
        # 域內窗：可信
        assert all(p.get("yhat_drift_reliable") is not False for p in golden_pts), "域內窗應可信"
    finally:
        registry._BUILDERS.pop(name, None)


def test_no_unreliable_flag_when_no_y_mapping(tmp_path):
    """無軟量測 Y（無 y_health）→ 不涉 Ŷ-drift → n_quality_unreliable=0（不過度標註）。"""
    r = build_and_save_model("synthetic", golden=(0, 300), models_dir=str(tmp_path), created_at="t", seed=5)
    tl = score_timeline(r["bundle_path"], "synthetic", window=60, seed=5)
    # synthetic 稀疏 Y——若無 y_mapping 則 unreliable 恆 0
    if not tl["has_y_mapping"]:
        assert tl["n_quality_unreliable"] == 0
