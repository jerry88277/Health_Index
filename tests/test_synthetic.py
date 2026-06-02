"""合成生成器 WHY 測試（Rule 9）。

核心 WHY：注入的隱性飄移必須**單變數不可見、多變量可見**——否則整個 Health_Index
存在的理由（抓單變數 SPC 漏掉的隱性飄移）就沒被測到。若哪天生成器讓飄移變成單變數
可見、或讓乾淨回歸看起來像飄移，以下測試必須失敗。
"""

import numpy as np
import pandas as pd

from health_index import interface as I
from health_index.adapters import synthetic as syn


def test_deterministic_same_seed():
    ds1, _ = syn.generate(seed=7)
    ds2, _ = syn.generate(seed=7)
    pd.testing.assert_frame_equal(ds1.frame, ds2.frame)


def test_produces_valid_contract():
    ds, gt = syn.generate(p=8)
    assert isinstance(ds, I.ProcessDataset)
    assert len(ds.x_columns) == 8
    assert ds.x_columns == gt.x_columns
    # 契約已在建構時驗證；再確認 reserved 欄齊備
    for col in I.RAW_REQUIRED:
        assert col in ds.frame.columns


def test_campaign_structure_A_B_A_C_A():
    ds, gt = syn.generate(n_per_campaign=100)
    grades = [g for _, _, g in gt.campaign_bounds]
    assert grades == ["A", "B", "A", "C", "A"]
    # golden 只標第一段 A；drift 只標最後一段 A
    assert gt.golden_mask[:100].all() and not gt.golden_mask[100:].any()
    assert gt.drift_mask[-100:].all() and not gt.drift_mask[:-100].any()


def test_sparse_y_ratio():
    ds, _ = syn.generate(n_per_campaign=200, y_every=20)
    y = ds.frame[I.Y_VALUE].to_numpy()
    observed = np.isfinite(y).mean()
    assert abs(observed - 1 / 20) < 0.02  # 約 5% 有實際量測


def _seg(frame, x_cols, mask):
    return frame.loc[mask, list(x_cols)].to_numpy()


def test_hidden_drift_is_univariate_invisible_but_multivariate_visible():
    ds, gt = syn.generate(seed=42)
    fr, xc = ds.frame, ds.x_columns
    golden = _seg(fr, xc, gt.golden_mask)
    drift = _seg(fr, xc, gt.drift_mask)
    # clean re-entry A = 第三段（index 2）
    s, e, g = gt.campaign_bounds[2]
    assert g == "A"
    clean = fr.iloc[s:e][list(xc)].to_numpy()

    gmean, gstd = golden.mean(0), golden.std(0)
    dmean, dstd = drift.mean(0), drift.std(0)

    # (1) 單變數不可見：每變數均值位移 < 0.3σ、變異比接近 1
    #     → 建在 golden-A 上的 3σ 單變數管制圖不會系統性告警（實測位移 ~0.21σ）
    assert np.max(np.abs(gmean - dmean) / gstd) < 0.3
    assert np.all((dstd / gstd > 0.75) & (dstd / gstd < 1.3))

    # (2) 多變量可見：相關結構改變，且【遠大於乾淨回歸】——後者才是真正扛 WHY 的斷言。
    # 註（紅隊 R1）：絕對門檻須定錨在抽樣噪聲地板之上。n=300 時「結構相同、僅差噪聲」
    # 的 Frobenius 距離已 ~0.5，故 >0.5 是假綠；實測 drift~4.5，定 >2.0 留足 headroom。
    # 此門檻相對 n_per_campaign=300 校準，改 n 須重校；相對斷言 (>3×clean) 則與 n 較無關。
    cg = np.corrcoef(golden, rowvar=False)
    cd = np.corrcoef(drift, rowvar=False)
    cc = np.corrcoef(clean, rowvar=False)
    fro_drift = np.linalg.norm(cg - cd)
    fro_clean = np.linalg.norm(cg - cc)
    assert fro_drift > 2.0            # 遠高於 n=300 噪聲地板(~0.5)
    assert fro_drift > 3 * fro_clean  # 飄移 ≫ 乾淨回歸（AC-3 種子；mutation-catching 主斷言）
