"""Y 健康指標 WHY 測試（桶2b，Rule 9）。

marquee WHY：Y 從兩正交方向變壞——**X→Y 關係斷**（map，軟測量殘差升）與 **Y 分布移**（dist，
Y-MSPC）。融合才完整。誠實標（Rule 12）：
- map 健康可靠**需軟測量能泛化**（密集 golden Y）；稀疏 Y（TEP）下 GPR 殘差被泛化誤差主導、無法
  分離 drift，故 TEP 的注入 drift（X-關係斷、Y 分布不變）**本就不是 Y-訊號**，由 X 側 L2 SPE 抓——
  本測試**不**假裝 Y 健康會強烈旗標 TEP drift（那是造假）。
"""

import os

import numpy as np
import pytest

from health_index.adapters import synthetic as syn
from health_index.y_health import YHealthIndex

_TEP_DATA = os.path.join("data", "tep", "m1d00.mat")


def _syn_dense(seed=5):
    # 密集 Y（y_every=1）→ 軟測量可泛化，map 健康可靠
    ds, gt = syn.generate(seed=seed, y_every=1, drift_strength=1.2)
    fr, cols, b = ds.frame, list(ds.x_columns), gt.campaign_bounds
    Xg = fr.loc[gt.golden_mask, cols].to_numpy()
    yg = fr.loc[gt.golden_mask, "y_value"].to_numpy()
    seg = lambda i: (fr.iloc[b[i][0]:b[i][1]][cols].to_numpy(), fr.iloc[b[i][0]:b[i][1]]["y_value"].to_numpy())  # noqa
    return Xg, yg, seg


def test_map_health_catches_xy_break_on_dense_y():
    # marquee WHY：密集 Y 下，注入 drift 破壞 X→Y 關係 → 軟測量殘差升 → map 健康明顯低於 golden。
    Xg, yg, seg = _syn_dense()
    yh = YHealthIndex().fit(Xg, yg)               # 純量 Y → 僅 map 分量
    assert yh.y_mspc_ is None
    Xg0, yg0 = seg(0)
    Xd, yd = seg(4)
    assert yh.y_health(Xd, yd) < yh.y_health(Xg0, yg0) - 0.15   # drift Y 健康明顯低（映射斷）
    assert yh.subscores(Xd, yd)["dist"] is None                 # 純量品質 → 無分布分量


def test_y_health_raises_when_no_component_available():
    # WHY（Rule 12）：窗內 Y 觀測不足且無多維品質 → 無可用分量 → fail loud，不靜默回假值
    Xg, yg, _ = _syn_dense()
    yh = YHealthIndex().fit(Xg, yg)
    X = np.random.RandomState(0).standard_normal((10, 10))
    y_empty = np.full(10, np.nan)
    assert yh.map_health(X, y_empty) is None                    # 0 觀測 < y_map_min_obs
    with pytest.raises(ValueError, match="無可用"):
        yh.y_health(X, y_empty)


def test_map_health_in_band_is_one():
    # WHY：殘差全落帶內 → map=1（健康滿分）；golden 自身（in-sample 殘差小）應近 1
    Xg, yg, seg = _syn_dense()
    yh = YHealthIndex().fit(Xg, yg)
    Xg0, yg0 = seg(0)
    assert yh.map_health(Xg0, yg0) > 0.9


def test_y_health_deterministic():
    Xg, yg, seg = _syn_dense()
    yh = YHealthIndex().fit(Xg, yg)
    Xd, yd = seg(4)
    assert yh.y_health(Xd, yd) == yh.y_health(Xd, yd)


# --- TEP 多維品質：dist 抓換產品；honest 標 drift 非 Y-訊號 ---
def _tep():
    from health_index.adapters import tep

    ds, gt = tep.generate(seed=0, drift_strength=0.7)
    fr, cols, b = ds.frame, list(ds.x_columns), gt.campaign_bounds
    gm = gt.golden_mask
    Xg = fr.loc[gm, cols].to_numpy()
    yg = fr.loc[gm, "y_value"].to_numpy()
    Yqg = fr.loc[gm, ["yq_G", "yq_H"]].to_numpy()
    yh = YHealthIndex().fit(Xg, yg, Yqg)

    def seg(i):
        s, e, _ = b[i]
        return (fr.iloc[s:e][cols].to_numpy(), fr.iloc[s:e]["y_value"].to_numpy(),
                fr.iloc[s:e][["yq_G", "yq_H"]].to_numpy())

    return yh, seg


@pytest.mark.skipif(not os.path.exists(_TEP_DATA), reason="TEP .mat 未下載（data/tep/）")
def test_dist_health_catches_product_change_not_xy_drift():
    # marquee WHY（互補性）：換產品 B/C（G/H 比例變）→ dist 健康崩（≈0）；注入 drift（Y 分布不變、
    # 只 X→Y 斷）→ dist 健康**保持**（≈golden）——證 dist 抓「分布移」非「關係斷」。
    yh, seg = _tep()
    Xb, yb, Yqb = seg(1)   # B 換產品
    Xg0, yg0, Yqg0 = seg(0)  # golden
    Xd, yd, Yqd = seg(4)   # drift（X-關係斷、Y 分布不變）
    assert yh.dist_health(Yqb) < 0.2                     # B 產品分布大變 → dist 崩
    assert yh.dist_health(Yqg0) > 0.7                     # golden Y 分布健康
    assert yh.dist_health(Yqd) > 0.5                      # drift：Y 分布大致保持（非 Y-訊號，honest）


@pytest.mark.skipif(not os.path.exists(_TEP_DATA), reason="TEP .mat 未下載（data/tep/）")
def test_fused_y_health_ordering_tep():
    # WHY：融合 Y 健康序＝golden ≳ 乾淨回歸 > 注入 drift > 換產品 B/C。drift 與 golden 差距**小**
    # （誠實：TEP drift 是 X-關係問題、非 Y 問題，Y 健康只輕微反映；強烈偵測由 X 側 L2 負責）。
    yh, seg = _tep()
    h = lambda i: yh.y_health(*seg(i))  # noqa
    assert h(0) > h(1) + 0.3 and h(0) > h(3) + 0.3        # golden 遠高於 B/C（換產品被 dist 抓）
    assert h(0) >= h(4)                                    # golden ≥ drift（方向正確，差距小屬誠實）