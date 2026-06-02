"""B2 真實集 adapter WHY 測試（UCI Gas Sensor Array Drift）。

marquee WHY（AC-4，紅隊 D2 / dev_plan §2）：**同一偵測邏輯（核心 L2 MSPC，零 per-dataset 調參）**在
真實感測器漂移資料上，golden(batch1) hold-out **不退化（不誤報）**、後續老化 batch 的**真實多變量
漂移被抓**——破除「合成自證」循環論證。資料未下載時整檔 skip（真實資料不入 repo）。

範圍誠實（Rule 6/12）：p=128 時 L1 FastMCD（需 n>2p）與 L4 全 permutation 超出線上成本，本層以可
轉移的 L2 MSPC 為證；全鏈 PCA-score 降級列 backlog。真實漂移**非單調**（資料集有重校事件），故只
斷言「存在被抓的漂移 batch」，不斷言逐 batch 單調升（那會是對真實資料造假，Rule 12）。
"""

import os

import pytest

from health_index.adapters import uci_gas_drift as gas

try:
    _DS, _GT = gas.load()
except FileNotFoundError:
    pytest.skip("UCI Gas Drift 資料未下載（data/uci_gas_drift/Dataset）", allow_module_level=True)

from health_index.interface import validate_raw  # noqa: E402
from health_index.validation.real_set import evaluate_gas_drift  # noqa: E402


def test_adapter_contract_and_shape():
    assert _DS.name == "uci_gas_drift"
    assert len(_DS.x_columns) == gas.N_FEATURES == 128
    assert len(_DS.frame) == 13910
    assert int(_GT.golden_mask.sum()) == 445            # batch1
    assert len(_GT.batch_bounds) == gas.N_BATCHES == 10
    validate_raw(_DS.frame, _DS.x_columns)              # 符合統一 raw 契約（不拋）


def test_parse_batch_dims():
    X, gasc = gas.parse_batch(os.path.join(gas.DEFAULT_DATA_DIR, "batch1.dat"))
    assert X.shape[1] == 128 and X.shape[0] == len(gasc)
    assert set(gasc.tolist()) <= {1, 2, 3, 4, 5, 6}


def test_ac4_golden_not_degrade_and_real_drift_caught():
    # marquee WHY（AC-4）：零 per-dataset 調參，golden hold-out 不誤報 + 真實漂移被抓。
    # mutant：MSPC 全標異常 → ac4a 破；MSPC 全不標 → ac4b 破。
    r = evaluate_gas_drift()
    assert r.ac4a_golden_not_degrade                    # golden 不退化（holdout anom < 0.10）
    assert r.golden_holdout_anom < 0.10
    assert r.ac4b_drift_detected                        # 真實漂移被抓
    assert max(r.batch_anom.values()) > r.golden_holdout_anom + 0.2  # 漂移段明顯高於 golden
    assert r.all_pass


def test_ac4_discriminates_not_all_flagging():
    # WHY（鑑別非全標，Rule 9）：若偵測器把所有 batch 都標異常（含 golden），AC-4 無意義。
    # golden hold-out 必須明顯低於最漂移的 batch。
    r = evaluate_gas_drift()
    assert r.golden_holdout_anom < 0.1 < max(r.batch_anom.values())


def test_evaluate_deterministic():
    a = evaluate_gas_drift(seed=0)
    b = evaluate_gas_drift(seed=0)
    assert (a.golden_holdout_anom, a.batch_anom) == (b.golden_holdout_anom, b.batch_anom)


def test_seed_actually_wired():
    # WHY（堵「seed 被忽略」假綠）：不同 split seed 應給出不同 golden hold-out 異常率
    # → 證明 seed 真的影響 split（否則 determinism 測試會在 seed 被忽略時仍假綠通過）。
    assert evaluate_gas_drift(seed=0).golden_holdout_anom != evaluate_gas_drift(seed=1).golden_holdout_anom


def test_missing_data_raises():
    with pytest.raises(FileNotFoundError):
        gas.load(data_dir=os.path.join("data", "does_not_exist"))
