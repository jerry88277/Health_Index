"""INC-4 批次/機台/時間選取 WHY 測試（Rule 9）——精靈第 1/2/4 關後端 + 多機台資料模型。

marquee WHY：
- **machine_id 僅 provenance**（Option A，使用者確認）：入 RESERVED 防未來 adapter 把它當 X 感測器
  （會把機台身分當製程訊號餵偵測器）；但**不是必要欄**——舊資料集不帶它照樣過契約（向後相容）。
- **generate_fleet**：TEP 原生無機台，以 seed+每機台系統偏移（M-2）合成「同產品×不同機台×不同時間」；
  偏移=X 側儀器/機台偏差（Y 不動）——正是池化護欄要暴露的異質情境。
- **cut_batches**：連續製程的「批」=固定時長窗（使用者 4h CSTR 生命週期）；跨批 y=批內實驗室
  量測平均、無則 NaN（未量測≠正常，接 quality 視圖）。
"""

import numpy as np
import pandas as pd
import pytest

from health_index.adapters import tep
from health_index.adapters.registry import available
from health_index.batch_avm.selection import cut_batches, machines_in_interval
from health_index.interface import MACHINE_ID, RESERVED, ContractError, validate_raw


def _fleet(**kw):
    kw.setdefault("n_per_campaign", 40)
    kw.setdefault("y_every", 5)
    kw.setdefault(
        "machines",
        (
            {"id": "A", "seed": 0, "offset_sigma": 0.0, "start": "2026-03-01"},
            {"id": "B", "seed": 1, "offset_sigma": 1.0, "start": "2026-04-01"},
        ),
    )
    return tep.generate_fleet(**kw)


# --- 契約（machine_id → RESERVED，additive） ---

def test_machine_id_reserved_but_optional():
    assert MACHINE_ID in RESERVED
    fr = pd.DataFrame({
        "timestamp": pd.date_range("2026-01-01", periods=5, freq="min"),
        "grade_label": ["A"] * 5,
        "y_value": [1.0] * 5,
        "y_timestamp": pd.date_range("2026-01-01", periods=5, freq="min"),
        "x1": np.arange(5.0),
    })
    validate_raw(fr, ("x1",))  # 不帶 machine_id 照樣過（向後相容）
    with pytest.raises(ContractError, match="保留欄名"):
        validate_raw(fr.assign(machine_id="M0"), ("x1", "machine_id"))  # 不得當 X 感測器


# --- generate_fleet ---

def test_fleet_has_machines_and_offset_shifts_B():
    ds, gt = _fleet()
    fr = ds.frame
    assert set(fr[MACHINE_ID].unique()) == {"A", "B"}
    # B 的 golden X 均值相對 A 系統性偏移（offset_sigma=1 → 每欄約 +1σ）
    gm = gt.golden_mask
    A_rows = (fr[MACHINE_ID] == "A").to_numpy()
    B_rows = (fr[MACHINE_ID] == "B").to_numpy()
    Xa = fr.loc[A_rows & gm, list(ds.x_columns)].to_numpy()
    Xb = fr.loc[B_rows & gm, list(ds.x_columns)].to_numpy()
    shift = (Xb.mean(axis=0) - Xa.mean(axis=0)) / (Xa.std(axis=0) + 1e-9)
    assert np.median(shift) > 0.5  # 系統偏移顯著（B 每欄 ≈ +1σ）
    # 時間：A 三月起、B 四月起
    assert fr.loc[A_rows, "timestamp"].min() == pd.Timestamp("2026-03-01")
    assert fr.loc[B_rows, "timestamp"].min() == pd.Timestamp("2026-04-01")


def test_fleet_fail_loud_on_duplicate_ids_and_registered():
    with pytest.raises(ValueError, match="重複"):
        tep.generate_fleet(machines=({"id": "A"}, {"id": "A"}), n_per_campaign=40)
    assert "tep_fleet" in available()


def test_fleet_deterministic():
    d1, g1 = _fleet()
    d2, g2 = _fleet()
    assert d1.frame.equals(d2.frame)
    assert np.array_equal(g1.golden_mask, g2.golden_mask)


# --- machines_in_interval（精靈第 2 關） ---

def test_machines_in_interval_filters_by_time():
    ds, _ = _fleet()
    all_m = machines_in_interval(ds.frame)
    assert [m["machine"] for m in all_m] == ["A", "B"]
    assert all(m["n_rows"] > 0 and m["n_y"] > 0 for m in all_m)
    only_a = machines_in_interval(ds.frame, start="2026-03-01", end="2026-03-05")
    assert [m["machine"] for m in only_a] == ["A"]


def test_machines_in_interval_defaults_single_machine():
    ds, _ = tep.generate(n_per_campaign=40, y_every=5)  # 無 machine_id 欄的舊資料
    out = machines_in_interval(ds.frame)
    assert [m["machine"] for m in out] == ["M0"]


# --- cut_batches（精靈第 4 關前置） ---

def test_cut_batches_fixed_duration_and_y_aggregation():
    ds, _ = _fleet()
    res = cut_batches(ds.frame, ds.x_columns, machine="A", batch_minutes=60)
    spans = res["spans"]
    assert len(spans) >= 3
    lens = [e - s for s, e in spans]
    assert all(l == 60 for l in lens[:-1])  # freq=1min → 每批 60 列
    assert res["X"].shape[1] == len(ds.x_columns)
    assert len(res["y"]) == len(spans)
    assert np.isfinite(res["y"]).sum() >= len(spans) - 1  # y_every=5 → 幾乎每批有實驗室樣本


def test_cut_batches_unknown_machine_fails_loud():
    ds, _ = _fleet()
    with pytest.raises(ValueError, match="machine"):
        cut_batches(ds.frame, ds.x_columns, machine="Z", batch_minutes=60)


def test_cut_batches_requires_machine_when_ambiguous():
    ds, _ = _fleet()
    with pytest.raises(ValueError, match="指定"):
        cut_batches(ds.frame, ds.x_columns, batch_minutes=60)  # 多機台未指定


def test_cut_batches_time_window_restricts_rows():
    ds, _ = _fleet()
    res = cut_batches(ds.frame, ds.x_columns, machine="A", start="2026-03-01 01:00", end="2026-03-01 03:00", batch_minutes=60)
    assert len(res["spans"]) == 2  # 兩小時 → 兩批


def test_e2e_selection_to_quality_and_mapping():
    # WHY（管線證明）：第 1-7 關後端串通——fleet→選機台→切批→X*→品質→建模評分。
    from health_index.batch_avm.mapping import fit_batch_model, score_batches
    from health_index.batch_avm.quality import batch_quality_view
    from health_index.preprocess.batch_features import batch_indicator_matrix

    ds, _ = _fleet()
    sel = cut_batches(ds.frame, ds.x_columns, machine="A", batch_minutes=10)
    q = batch_quality_view(sel["X"], sel["y"], sel["spans"], ds.x_columns, stats=("mean", "std"), trim_frac=0.0)
    assert q["summary"]["n_batches"] == len(sel["spans"])
    xs = batch_indicator_matrix(sel["X"], sel["spans"], ds.x_columns, stats=("mean", "std"), trim_frac=0.0)
    feat_cols = [c for c in xs.columns if c not in ("batch", "start", "end", "len")]
    ok = np.isfinite(sel["y"])
    m = fit_batch_model(xs[feat_cols].to_numpy()[ok], sel["y"][ok], columns=feat_cols)
    res = score_batches(m, xs[feat_cols].to_numpy())
    assert len(res["batches"]) == len(sel["spans"])
    assert res["summary"]["cv_available"] in (True, False)  # 誠實旗標存在（小 n 可能不足 20）
