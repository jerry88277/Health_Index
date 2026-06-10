"""門檻可移植性哨兵 WHY 測試（桶5 調查產出，Rule 9）。

WHY：桶5 調查（docs/decision_threshold_calibration.md，≥2 紅隊複審）結論「per-dataset 門檻自動校準
not warranted」，但 dead-zone 是資料相依的。哨兵的存在理由＝**只用 golden** 在固定門檻可能不可移植時
fail-loud（Rule 12）。當哨兵在 floor 真的逼近門檻時**不警示**，它就失去意義 → 測試必須失敗。
"""

import warnings

import numpy as np
import pytest

from health_index.health import HealthIndex


def test_sentinel_silent_when_floor_far_above_threshold():
    """WHY：正常 golden（HI floor≫門檻，寬 dead-zone）→ 哨兵不應誤警（否則狼來了、使用者忽略）。"""
    rng = np.random.default_rng(1)
    G = rng.standard_normal((360, 6))  # 自正規化 → golden HI≈1，floor≫0.6
    hi = HealthIndex().fit(G)
    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)  # 任何警示即失敗
        floor = hi.check_threshold_portability(G)
    assert floor > hi.config.hi_alarm_threshold + 0.1  # 確認確實在安全帶外


def test_sentinel_warns_when_floor_approaches_threshold():
    """WHY（哨兵的存在理由）：當 golden floor 逼近門檻時必須 warn。用高 margin 強制觸發條件，
    證明「floor < 門檻+margin → 警示」的邏輯確實接線（floor 逼近門檻＝固定門檻不可移植的訊號）。"""
    rng = np.random.default_rng(2)
    G = rng.standard_normal((360, 6))  # golden HI≈1
    hi = HealthIndex().fit(G)
    floor = hi.check_threshold_portability(G, margin=0.0, window=60)  # 先取得實際 floor
    # 用 margin 使「門檻+margin」剛好高於 floor → 必觸發
    big_margin = float(floor - hi.config.hi_alarm_threshold + 0.05)
    with pytest.warns(RuntimeWarning, match="不可移植"):
        hi.check_threshold_portability(G, margin=big_margin, window=60)


def test_sentinel_returns_nan_when_golden_too_short():
    """WHY：golden 短於窗長無法切窗 → 回 nan 不檢（誠實，不硬給假 floor）。"""
    rng = np.random.default_rng(3)
    G = rng.standard_normal((30, 6))
    hi = HealthIndex().fit(G)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        floor = hi.check_threshold_portability(G, window=60)
    assert np.isnan(floor)


def test_sentinel_does_not_mutate_threshold():
    """WHY：哨兵只 surface、不自動改門檻（校準經 ≥2 紅隊驗證 not warranted）。呼叫後 is_alarm
    行為與未呼叫一致（無 _alarm_threshold_ 覆寫，固定門檻不被偷改）。"""
    rng = np.random.default_rng(4)
    G = rng.standard_normal((360, 6))
    hi = HealthIndex().fit(G)
    before = hi.is_alarm(G[:60])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        hi.check_threshold_portability(G, margin=0.5)  # 即使觸發警示
    assert not hasattr(hi, "_alarm_threshold_")  # 未引入任何門檻覆寫狀態
    assert hi.is_alarm(G[:60]) == before  # 決策行為不變
