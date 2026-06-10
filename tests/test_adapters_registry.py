"""統一 adapter 協定 WHY 測試（桶1，Rule 9）。

marquee WHY：桶1 的價值是「**任一資料集經統一協定即可驅動同一判斷鏈**」。故核心測試＝用 registry
建出的**共用 GroundTruth**（非 bespoke 真值）餵 HealthIndex，仍能區分 drift vs golden。當協定喪失此
可消費性（golden_mask 接錯、segments 越界、轉換器漏欄）時，測試必須失敗。
"""

import os

import numpy as np
import pandas as pd
import pytest

from health_index.adapters import dataframe, registry, synthetic
from health_index.adapters.base import GroundTruth, Segment
from health_index.health import HealthIndex
from health_index.interface import GRADE_LABEL, Y_VALUE, ContractError, ProcessDataset

_TEP_DATA = os.path.join("data", "tep", "m1d00.mat")


def test_registry_lists_builtin_datasets():
    assert {"synthetic", "tep", "tep_tp", "uci_gas_drift"} <= set(registry.available())


def test_registry_build_synthetic_common_groundtruth():
    ds, gt = registry.build("synthetic", seed=5)
    assert isinstance(ds, ProcessDataset) and isinstance(gt, GroundTruth)
    assert gt.n == len(ds.frame) == len(gt.golden_mask)
    assert gt.golden_mask.sum() > 0 and gt.has_labeled_drift  # 合成有逐列漂移真值
    # segments 依時間序、不重疊、覆蓋 [0, n)
    assert gt.segments[0].start == 0 and gt.segments[-1].end == gt.n
    for a, b in zip(gt.segments, gt.segments[1:]):
        assert a.end == b.start
    assert [s.label for s in gt.segments] == ["A", "B", "A", "C", "A"]


def test_registry_converter_preserves_bespoke_masks():
    # WHY（向後相容）：轉換器不得竄改既有 bespoke 真值——golden/drift mask 須與原 adapter 逐位元一致
    ds_b, gt_b = synthetic.generate(seed=5)
    _, gt_c = registry.build("synthetic", seed=5)
    assert np.array_equal(gt_c.golden_mask, gt_b.golden_mask)
    assert np.array_equal(gt_c.drift_mask, gt_b.drift_mask)


def test_registry_marquee_common_groundtruth_drives_chain():
    # marquee WHY（桶1 存在理由）：只用**共用 GroundTruth** 的 golden_mask 餵判斷鏈，drift 段健康度
    # 仍 < golden 段。證「統一協定可驅動偵測」——協定接錯則此測試崩。
    ds, gt = registry.build("synthetic", seed=5, drift_strength=1.2)
    cols = list(gt.x_columns)
    hi = HealthIndex().fit(ds.frame.loc[gt.golden_mask, cols].to_numpy())
    seg = {s.id: s for s in gt.segments}
    golden_seg, drift_seg = seg[0], seg[4]  # C0=golden、C4=drift（注入）
    Xg = ds.frame.iloc[golden_seg.start : golden_seg.end][cols].to_numpy()
    Xd = ds.frame.iloc[drift_seg.start : drift_seg.end][cols].to_numpy()
    assert hi.health_index(Xd) < hi.health_index(Xg) - 0.1


def test_registry_unknown_raises_with_listing():
    with pytest.raises(KeyError, match="未知資料集"):
        registry.build("does_not_exist")


def test_register_rejects_silent_overwrite():
    with pytest.raises(ValueError, match="已註冊"):
        registry.register("synthetic", lambda **k: None)
    # overwrite=True 才允許（用後即還原，避免污染其他測試）
    orig = registry._BUILDERS["synthetic"]
    registry.register("synthetic", orig, overwrite=True)
    assert registry._BUILDERS["synthetic"] is orig


# --- 通用 dataframe adapter ---
def test_dataframe_xonly_autofills_grade_and_nan_y():
    raw = pd.DataFrame(np.random.RandomState(0).standard_normal((100, 4)), columns=list("abcd"))
    ds, gt = dataframe.from_frame(raw, x_columns=list("abcd"), golden=0.3, name="toy")
    assert ds.frame[GRADE_LABEL].nunique() == 1                 # 無 grade → 常數單模態
    assert ds.frame[Y_VALUE].isna().all()                       # 無 Y → 全 NaN
    assert gt.golden_mask.sum() == 30 and not gt.golden_mask[30:].any()  # 前 30%
    assert len(gt.segments) == 1 and gt.drift_mask is None


def test_dataframe_grade_splits_segments_and_y_observed():
    raw = pd.DataFrame(np.random.RandomState(1).standard_normal((100, 3)), columns=list("xyz"))
    raw["mode"] = ["A"] * 60 + ["B"] * 40
    raw["q"] = np.r_[np.full(95, np.nan), np.arange(5.0)]
    ds, gt = dataframe.from_frame(raw, x_columns=list("xyz"), grade="mode", y_value="q", golden=(0, 50))
    assert [(s.label, s.start, s.end) for s in gt.segments] == [("A", 0, 60), ("B", 60, 100)]
    assert ds.frame[Y_VALUE].notna().sum() == 5                 # Y 觀測處保留
    assert ds.frame["y_timestamp"].notna().sum() == 5          # Y timestamp 對齊觀測
    assert gt.golden_mask.sum() == 50


@pytest.mark.parametrize(
    "golden,expect",
    [(0.5, 50), ((10, 30), 20), (np.r_[np.ones(40, bool), np.zeros(60, bool)], 40)],
)
def test_dataframe_golden_specs(golden, expect):
    raw = pd.DataFrame(np.zeros((100, 2)), columns=["a", "b"])
    _, gt = dataframe.from_frame(raw, x_columns=["a", "b"], golden=golden)
    assert gt.golden_mask.sum() == expect


def test_dataframe_bad_golden_and_reserved_column_fail_loud():
    raw = pd.DataFrame(np.zeros((20, 2)), columns=["a", "b"])
    with pytest.raises(ValueError, match="golden"):
        dataframe.from_frame(raw, x_columns=["a", "b"], golden=1.5)        # 比例越界
    bad = pd.DataFrame(np.zeros((20, 1)), columns=["timestamp"])           # 保留欄當 X
    with pytest.raises(ContractError):
        dataframe.from_frame(bad, x_columns=["timestamp"])


def test_dataframe_output_drives_chain():
    # WHY：通用 adapter 的輸出同樣能餵判斷鏈（golden fit → 健康度）——證真接得上，非僅格式對
    rng = np.random.RandomState(2)
    raw = pd.DataFrame(rng.standard_normal((400, 5)), columns=list("vwxyz"))
    ds, gt = dataframe.from_frame(raw, x_columns=list("vwxyz"), golden=0.5)
    hi = HealthIndex().fit(ds.frame.loc[gt.golden_mask, list(gt.x_columns)].to_numpy())
    # golden 自身應健康（同分佈 iid）
    Xg = ds.frame.loc[gt.golden_mask, list(gt.x_columns)].to_numpy()
    assert hi.health_index(Xg) > 0.8


def test_groundtruth_validation_fails_loud():
    with pytest.raises(ValueError, match="長度"):
        GroundTruth(x_columns=("a",), golden_mask=np.zeros(10, bool),
                    segments=(Segment(0, 0, 10, "A"),), drift_mask=np.zeros(5, bool))
    with pytest.raises(ValueError, match="越界"):
        GroundTruth(x_columns=("a",), golden_mask=np.zeros(10, bool),
                    segments=(Segment(0, 0, 20, "A"),))


@pytest.mark.skipif(not os.path.exists(_TEP_DATA), reason="TEP .mat 未下載（data/tep/）")
def test_registry_tep_variants_distinct_and_consumable():
    # WHY：tep（iid）與 tep_tp（保時序）皆經統一協定建出；tep_tp 預設啟用 time_preserving
    _, gt_iid = registry.build("tep", seed=0, drift_strength=1.0)
    _, gt_tp = registry.build("tep_tp", seed=0, drift_strength=0.7)
    assert [s.label for s in gt_iid.segments] == ["A", "B", "A", "C", "A"]
    assert gt_tp.n != gt_iid.n  # 保時序 golden 較寬 → 總長不同（結構確實切換）
