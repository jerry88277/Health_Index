"""M0 煙霧測試。

WHY（Rule 9）：統一契約是五維度判斷鏈的骨架（Rule 3）。若契約驗證失效，
下游所有偵測器都建立在沙上——故這些測試在「契約不再擋壞資料」時必須失敗。
"""

import numpy as np
import pandas as pd
import pytest

import health_index
from health_index import interface as I
from health_index.config import Config, DEFAULT


def test_import_and_version():
    assert isinstance(health_index.__version__, str)


def test_config_defaults_sane():
    c = Config()
    assert 0 < c.cp_alpha < 1
    assert 0 < c.mspc_alpha < 1
    assert c.min_samples_per_dim >= 1
    assert c.cp_min_calibration >= 1
    assert c.drift_persistence_k >= 1
    assert c.random_state == DEFAULT.random_state == 42  # 可重現契約


def _valid_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            I.TIMESTAMP: pd.date_range("2026-01-01", periods=3, freq="s"),
            I.GRADE_LABEL: ["A", "A", "A"],
            I.Y_VALUE: [np.nan, 1.0, np.nan],  # 稀疏 Y
            I.Y_TIMESTAMP: [pd.NaT, pd.Timestamp("2026-01-01"), pd.NaT],
            "x_temp": [1.0, 2.0, 3.0],
            "x_pres": [4.0, 5.0, 6.0],
        }
    )


def test_contract_accepts_valid():
    ds = I.ProcessDataset(frame=_valid_frame(), x_columns=("x_temp", "x_pres"), name="unit")
    assert ds.x_columns == ("x_temp", "x_pres")
    assert ds.name == "unit"


def test_contract_rejects_missing_raw_column():
    df = pd.DataFrame({I.TIMESTAMP: [1], "x_temp": [1.0]})  # 缺 grade/y
    with pytest.raises(I.ContractError):
        I.ProcessDataset(frame=df, x_columns=("x_temp",), name="bad")


def test_contract_rejects_reserved_x_name():
    df = _valid_frame()
    df[I.MODE] = "steady"
    with pytest.raises(I.ContractError):
        I.ProcessDataset(frame=df, x_columns=(I.MODE,), name="bad")  # 用保留欄當 X


def test_contract_rejects_empty_x():
    with pytest.raises(I.ContractError):
        I.ProcessDataset(frame=_valid_frame(), x_columns=(), name="bad")


def test_mode_enum_values():
    assert {m.value for m in I.Mode} == {"steady", "transition", "maintenance"}
