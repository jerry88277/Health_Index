"""增量8 Y 側品質飄移預警 WHY 測試（Rule 9）：品質標的隱性飄移時提前警告，防量產次級品/報廢。

核心 WHY：X 都正常、實際 Y 卻偏（X→Y 關係斷）＝**真隱性品質飄移**——單變數 SPC 看 X 抓不到，正是本維度
存在的理由。當 Y 殘差超界時本維度仍不告警的測試是錯的。誠實邊界：Y 稀疏時不可判，標 None 不假綠。
"""

import numpy as np
import pandas as pd
import pytest

from health_index.adapters import registry
from health_index.adapters.dataframe import from_frame
from health_index.deploy import demo


@pytest.fixture
def broken_xy():
    """golden：Y=X·w；後段：X 同分佈但 Y 偏移 +5（X→Y 斷裂、dense Y）→ 觸發殘差超界。用後清掉 builder。"""
    name = "_qtest_broken_xy"

    def _b(**kw):
        rng = np.random.default_rng(0)
        w = np.array([1.0, 0.5, -0.3])
        Xg = rng.normal(0, 1, (240, 3)); yg = Xg @ w + rng.normal(0, 0.05, 240)
        Xt = rng.normal(0, 1, (120, 3)); yt = Xt @ w + 5.0 + rng.normal(0, 0.05, 120)  # Y 偏移、X 不變
        df = pd.DataFrame(np.vstack([Xg, Xt]), columns=["a", "b", "c"])
        df["yq"] = np.concatenate([yg, yt])
        return from_frame(df, x_columns=["a", "b", "c"], y_value="yq", golden=(0, 240), name=name)

    registry.register(name, _b, overwrite=True)
    try:
        yield name
    finally:
        registry._BUILDERS.pop(name, None)  # 不污染全域 registry（catalog 測試等）


def test_hidden_quality_drift_raises_quality_alarm(broken_xy, tmp_path):
    """X→Y 斷裂（X 正常、Y 偏）→ 殘差超界 → 品質維度告警；golden 不誤報。"""
    m = demo.build_and_save_model(broken_xy, models_dir=str(tmp_path), created_at="t")
    tl = demo.score_timeline(m["bundle_path"], broken_xy, window=60)
    assert tl["has_y_mapping"] and tl["n_quality_alarms"] >= 1   # 隱性品質飄移被抓
    golden = [p for p in tl["points"] if p["region"] == "golden"]
    after = [p for p in tl["points"] if p["region"] != "golden"]
    assert golden and all(not p["y_flagged"] for p in golden)   # golden 殘差正常→不旗標
    assert any(p["y_flagged"] for p in after)                   # 斷裂段→旗標
    assert all("yhat_drift_z" in p and "y_observed" in p for p in tl["points"])


def test_sparse_y_honest_none_not_fake_green(tmp_path):
    """誠實邊界：Y 稀疏（synthetic 5%）→ 窗觀測不足 → y_map_health=None、y_flagged=False（不假綠）。"""
    m = demo.build_and_save_model("synthetic", models_dir=str(tmp_path), created_at="t", seed=5, drift_strength=1.2)
    tl = demo.score_timeline(m["bundle_path"], "synthetic", window=60, seed=5, drift_strength=1.2)
    assert tl["has_y_mapping"]
    insufficient = [p for p in tl["points"] if (not p["y_observed"]) or p["y_map_health"] is None]
    assert insufficient and all(p["y_flagged"] is False for p in insufficient)  # 不可判時不旗標


def test_no_y_no_quality_dimension(tmp_path):
    """無 Y 軟量測 → has_y_mapping False、n_quality_alarms 0、點無 yhat（不杜撰品質維度）。"""
    name = "_qtest_noy"

    def _b(**kw):
        rng = np.random.default_rng(1)
        df = pd.DataFrame(rng.normal(0, 1, (300, 3)), columns=["a", "b", "c"])
        return from_frame(df, x_columns=["a", "b", "c"], golden=(0, 150), name=name)  # 不給 y_value → 無 Y

    registry.register(name, _b, overwrite=True)
    try:
        m = demo.build_and_save_model(name, models_dir=str(tmp_path), created_at="t")
        tl = demo.score_timeline(m["bundle_path"], name, window=60)
        assert tl["has_y_mapping"] is False and tl["n_quality_alarms"] == 0
        assert "yhat_mean" not in tl["points"][0]
    finally:
        registry._BUILDERS.pop(name, None)
