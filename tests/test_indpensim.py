"""B4 / L5 批次 DTW WHY 測試（IndPenSim）。

marquee WHY（L5 存在理由）：批次製程每批**長度不一**（835–1450 點）→ 直接 Euclidean 不可比；**DTW
對齊**後量整段軌跡形變。對正常參考批校準門檻，**faulty 批（91–100）被旗標率明顯高於正常 hold-out**
（正常不退化 + 軌跡形變被抓）。資料未下載時整檔 skip（真實資料不入 repo）。

範圍誠實（Rule 12）：非所有 IndPenSim fault 都為全域軌跡形變（部分局部/瞬時）→ 只斷言「faulty 旗標率
明顯高於正常」，不要求 100% 偵測。成本（Rule 6）：降採樣 + Sakoe-Chiba band。
"""

import os

import numpy as np
import pytest

from health_index.adapters import indpensim as ip

try:
    _DS = ip.load()
except FileNotFoundError:
    pytest.skip("IndPenSim 資料未下載（data/indpensim/）", allow_module_level=True)

from health_index.detectors.batch_dtw import BatchDTW  # noqa: E402


@pytest.fixture(scope="module")
def fitted():
    # 正常參考批 1–20（idx 0–19）fit；module 範圍跑一次共用（DTW 較貴）
    return BatchDTW().fit([_DS.batches[i] for i in range(20)])


def test_adapter_contract():
    assert _DS.name == "indpensim"
    assert len(_DS.batches) == ip.N_BATCHES == 100
    assert len(_DS.x_columns) == 25
    assert _DS.labels.count("faulty") == 10
    assert all(_DS.labels[i] == "faulty" for i in range(90, 100))   # 91–100 faulty
    assert all(_DS.labels[i] == "normal" for i in range(90))        # 1–90 normal
    # x_columns 排除旗標/offline/Time（Rule 8 不臆測，用文件結構標籤）
    assert not any(("offline" in c.lower() or "Time" in c or "Fault" in c) for c in _DS.x_columns)
    assert _DS.batches[0].shape[1] == 25                            # 軌跡為 (T_i, p)


def test_batches_variable_length_and_dtw_comparable(fitted):
    # WHY（L5 存在理由）：批長不一，DTW 對齊後可比；score 對任意長度批皆可算（Euclidean 不可）
    lens = [len(b) for b in _DS.batches]
    assert max(lens) - min(lens) > 100                              # 確實長度不一
    s_short = fitted.score(min(_DS.batches, key=len))
    s_long = fitted.score(max(_DS.batches, key=len))
    assert np.isfinite(s_short) and np.isfinite(s_long)


def test_labels_match_fault_ref(fitted):
    # WHY（Rule 8 資料驅動標籤）：labels 由 CSV Fault_ref 欄逐批導出，恰標 91–100 為 faulty
    # （非硬編 batch index；防 survey 結構與資料漂移）。
    faulty_ids = [bid for bid, lab in zip(_DS.batch_ids, _DS.labels) if lab == "faulty"]
    assert faulty_ids == list(range(91, 101))


def test_dtw_beats_euclidean_on_phase_shift():
    # WHY（DTW 存在理由，合成證明，紅隊 Rule 9）：兩條同形狀但**相位錯位**的軌跡（尖峰 @0.5 vs @0.6），
    # DTW 對齊後距離極小，而等長 Euclidean 因峰錯位距離大 → DTW 在相位漂移下嚴格優於 resample-Euclidean。
    # 鎖死「把 DTW 換成 Euclidean」mutant（否則 L5 的 DTW 必要性無測試守護）。
    m = BatchDTW()
    tt = np.linspace(0, 1, 100)
    base = np.exp(-((tt - 0.5) ** 2) / 0.005)[:, None]
    shifted = np.exp(-((tt - 0.60) ** 2) / 0.005)[:, None]   # 位移 10 步（band 內）
    dtw_d = m._dtw(base, shifted)
    eucl_d = float(np.sqrt(((base - shifted) ** 2).sum()) / (len(base) + len(shifted)))
    assert dtw_d < eucl_d * 0.3        # DTW warping 大幅吃掉相位錯位，Euclidean 吃不掉


def test_l5_catches_faulty_not_normal(fitted):
    # marquee WHY：faulty 批被抓率 >> 正常 hold-out（正常不退化 + 軌跡形變被抓）。
    # 殺「全標異常（正常也爆）」「全不標（faulty 漏）」mutant。
    normal_rate = np.mean([fitted.is_deviation(_DS.batches[i]) for i in range(20, 40)])  # 正常 hold-out
    faulty_rate = np.mean([fitted.is_deviation(_DS.batches[i]) for i in range(90, 100)])  # faulty
    assert normal_rate < 0.15                  # 正常不退化（門檻 k=2 ≈ 5%）
    assert faulty_rate >= 0.5                   # faulty 被抓 ≥50%（實測 ~0.70）
    assert faulty_rate > normal_rate + 0.4      # 明顯分離


def test_faulty_scores_higher_than_normal(fitted):
    # WHY：faulty 批的 DTW 形變分數整體高於正常 hold-out（鎖鑑別方向，非門檻巧合）
    normal = [fitted.score(_DS.batches[i]) for i in range(20, 40)]
    faulty = [fitted.score(_DS.batches[i]) for i in range(90, 100)]
    assert np.mean(faulty) > np.mean(normal)


def test_resample_bounds_cost(fitted):
    # WHY（Rule 6 成本控制）：軌跡降採樣到固定點數（DTW O(n²) 不隨原始批長爆走）
    assert fitted._prep(_DS.batches[0]).shape[0] == fitted.config.dtw_resample_len


def test_deterministic(fitted):
    assert fitted.score(_DS.batches[95]) == fitted.score(_DS.batches[95])
    assert fitted.is_deviation(_DS.batches[95]) == fitted.is_deviation(_DS.batches[95])


def test_missing_data_raises():
    with pytest.raises(FileNotFoundError):
        ip.load(data_dir=os.path.join("data", "no_indpensim_here"))
