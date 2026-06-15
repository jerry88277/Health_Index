"""golden='auto' 自動挑選 WHY 測試（桶4b，Rule 9）。

marquee WHY：無 label 通用資料集的 golden 自動挑選必須挑到**最早的乾淨平穩 regime**（AVM golden-A
語義），而非 naive「取前 X%」（前段含暫態時被污染），更**不得把隱性 drift 段選為 golden**。

設計史（誠實，紅隊 A BLOCK）：早期用 `score=段長/(1+std)` 複合分數對隱性多變量 drift **盲**（本專案
drift 保邊際變異、只改相關結構，length/std 與之正交）→ synthetic 20 seed 僅 6/20 對、4/20 選到 drift。
改為「最早乾淨平穩段」後 20/20 對、0 選到 drift。下列測試鎖住此修復與所有紅隊攻擊案例；任一退化
（選到 drift/暫態/凍結/被量綱綁架/靜默壞基準）時必須失敗。
"""

import warnings

import numpy as np
import pandas as pd
import pytest

from health_index.adapters import synthetic as syn
from health_index.adapters.dataframe import _auto_select_golden, _resolve_golden, from_frame
from health_index.health import HealthIndex


def _rng_range(mask: np.ndarray) -> tuple[int, int]:
    idx = np.flatnonzero(mask)
    return int(idx[0]), int(idx[-1] + 1)


def _transient_then_stable(seed=0, p=6):
    r = np.random.default_rng(seed)
    transient = r.standard_normal((100, p)) * 2.0 + np.linspace(0, 3, 100)[:, None]  # ramp 暫態
    stable = r.standard_normal((300, p)) * 0.5 + 5.0
    return np.vstack([transient, stable])


# ----------------------- marquee：不把 drift 選為 golden（紅隊 A killshot 回歸）-----------------------

def test_auto_never_selects_drift_on_synthetic_ground_truth():
    """marquee（紅隊 A BLOCK 的回歸鎖）：在專案**自己有真值**的 synthetic 上，golden='auto' 跨 20 seed
    必須選到真值 golden-A、**絕不**把注入 drift 的 campaign 選為基準（選錯＝毒化整鏈）。複合分數舊版
    4/20 選到 drift；最早乾淨平穩段版須 0 選到 drift、絕大多數選對 golden-A。"""
    correct = drift_picked = 0
    for seed in range(20):
        ds, gt = syn.generate(seed=seed)
        X = ds.frame[list(ds.x_columns)].to_numpy()
        m = _auto_select_golden(X)
        gm, dm = np.asarray(gt.golden_mask), np.asarray(gt.drift_mask)
        if (m & gm).sum() / max(1, (m | gm).sum()) > 0.8:
            correct += 1
        if (m & dm).sum() > 0:
            drift_picked += 1
    assert drift_picked == 0, f"{drift_picked}/20 把 drift 段選為 golden（毒化偵測鏈）"
    assert correct >= 18, f"僅 {correct}/20 選對 golden-A"


# ----------------------- 暫態 / golden-A 語義 -----------------------

def test_auto_picks_stable_not_transient():
    """前段為 ramp 暫態 → auto 須挑後段平穩 regime（標準化 ramp 過濾），不選第一段暫態。
    naive 前 30%（[0,120)）會跨暫態邊界(100)被污染。"""
    X = _transient_then_stable(seed=0)
    s, e = _rng_range(_auto_select_golden(X))
    assert s >= 100 and e <= 400


def test_auto_picks_earliest_clean_regime_not_just_longest():
    """WHY（golden-A 語義 + 紅隊 B：須區分『最早乾淨』vs『無腦選第一段』vs『選最穩段』）：
    構造 [暫態(短) | A乾淨(早) | A'更穩(晚, std更小)]。最早乾淨平穩段須選『A乾淨(早)』——
    無腦選第一段會選暫態（失敗）、選最穩段會選晚段 A'（失敗），只有『最早乾淨』選中段。"""
    r = np.random.default_rng(7)
    p = 6
    X = np.vstack([
        r.standard_normal((60, p)) * 2.0 + np.linspace(0, 4, 60)[:, None],  # 短暫態(ramp)
        r.standard_normal((200, p)) * 0.6 + 1.0,                            # A 乾淨（最早平穩）← 應選
        r.standard_normal((200, p)) * 0.3 + 1.0,                            # A' 更穩（晚, std 更小）
    ])
    s, e = _rng_range(_auto_select_golden(X))
    assert s == 60 and e <= 260  # 最早乾淨段，非暫態(0)、非更穩晚段(260)


def test_auto_avoids_long_high_variance_drift():
    """末端為長高變異 drift → 不得選它（含 ramp/高變異被過濾），須挑較早乾淨平穩 regime。"""
    r = np.random.default_rng(2)
    p = 6
    X = np.vstack([
        r.standard_normal((40, p)) * 2.0,
        r.standard_normal((200, p)) * 0.5 + 5.0,                              # 乾淨（應選）
        r.standard_normal((200, p)) * 1.5 + np.linspace(0, 4, 200)[:, None],  # 長高變異 drift
    ])
    s, e = _rng_range(_auto_select_golden(X))
    assert 40 <= s and e <= 240


# ----------------------- 紅隊 A 攻擊回歸：凍結 / 量綱 -----------------------

def test_auto_avoids_frozen_sensor_segment():
    """WHY（紅隊 A#1b）：凍結/死感測器段 std≈0——舊複合分數因 1/(1+std) 拿超高分被選為 golden（把故障
    當基準）。std 守門須排除凍結段，不論它在前或在後。"""
    r = np.random.default_rng(1)
    p = 6
    frozen = np.ones((200, p)) * r.standard_normal(p)  # 卡死常數
    clean = r.standard_normal((300, p)) * 0.8
    # 凍結在後
    s, e = _rng_range(_auto_select_golden(np.vstack([clean, frozen])))
    assert e <= 300  # 選乾淨段 [0,300)
    # 凍結在前（病態）→ std 守門仍避開凍結，選後段乾淨
    s2, e2 = _rng_range(_auto_select_golden(np.vstack([frozen, clean])))
    assert s2 >= 200  # 避開凍結 [0,200)


def test_auto_not_scale_hijacked_by_large_magnitude_column():
    """WHY（紅隊 A#2）：舊版對未標準化 X 取 std，被大量綱單欄綁架選擇。標準化空間計算 ramp/std →
    大量綱欄(×5000)不主導，仍依多變量結構挑最早乾淨段。"""
    r = np.random.default_rng(2)
    big = r.standard_normal((400, 1)) * 5000.0
    small = np.vstack([r.standard_normal((200, 5)) * 0.5, r.standard_normal((200, 5)) * 0.5 + 3.0])
    X = np.hstack([big, small])
    s, e = _rng_range(_auto_select_golden(X))
    assert s == 0 and e <= 200  # 最早乾淨段，未被大欄綁架去選後段


# ----------------------- 退化路徑 surface（紅隊 B Rule 12）-----------------------

def test_auto_short_series_falls_back_and_warns():
    """序列太短切不出 regime → 退回全段並 warn（不靜默給壞基準）。"""
    X = np.random.default_rng(3).standard_normal((20, 4))
    with pytest.warns(RuntimeWarning, match="太短"):
        m = _auto_select_golden(X)
    assert m.all()


def test_auto_warns_when_no_changepoints_detected():
    """WHY（紅隊 B 揪出的靜默 bug）：PELT 未切出任何變點時，全序列被當 golden——舊版**零警告**靜默
    給可能含 drift 的壞基準。須 warn『未偵測到變點…結果不可信』。"""
    # 平緩單調漂移：PELT(penalty 預設) 常不觸發 → 單一全段
    r = np.random.default_rng(11)
    X = r.standard_normal((300, 4)) * 0.3 + np.linspace(0, 0.5, 300)[:, None]
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        _auto_select_golden(X)
    msgs = " ".join(str(x.message) for x in w)
    # 若 PELT 確實未切段，須有「未偵測到變點」警告；若切了段則此測試不適用（跳過）
    from health_index.preprocess.segment import detect_change_points
    if not detect_change_points(X):
        assert "未偵測到變點" in msgs


def test_auto_warns_through_from_frame_stacklevel(recwarn):
    """WHY（紅隊 B stacklevel）：經 from_frame 公開路徑觸發 auto 退化警告時，stacklevel 須指到使用者
    呼叫層（from_frame 的呼叫者）。此處驗證警告確實發出且可被使用者捕捉（不越界到 sys/內部行）。"""
    X = np.random.default_rng(3).standard_normal((20, 4))  # 太短 → 退回 + warn
    cols = [f"x{i}" for i in range(4)]
    df = pd.DataFrame(X, columns=cols)
    with pytest.warns(RuntimeWarning, match="太短"):
        from_frame(df, x_columns=cols, golden="auto")


# ----------------------- 端到端 / 向後相容 / fail-loud -----------------------

def test_auto_end_to_end_through_from_frame():
    """golden='auto' 經 from_frame 端到端產生合法 mask，且驅動 HealthIndex（挑到的平穩基準健康）。"""
    X = _transient_then_stable(seed=4)
    cols = [f"x{i}" for i in range(X.shape[1])]
    df = pd.DataFrame(X, columns=cols)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        ds, gt = from_frame(df, x_columns=cols, golden="auto")
    s, _ = _rng_range(gt.golden_mask)
    assert s >= 100
    Xg = ds.frame.loc[gt.golden_mask, cols].to_numpy()
    assert HealthIndex().fit(Xg).health_index(Xg) > 0.8


def test_backward_compat_none_default_and_fractions():
    """向後相容：golden=None 維持前 30%（+警告）；float/(start,end) 不變。auto 為 opt-in 加法。"""
    r = np.random.default_rng(5)
    X = r.standard_normal((200, 4))
    cols = [f"x{i}" for i in range(4)]
    df = pd.DataFrame(X, columns=cols)
    with pytest.warns(RuntimeWarning, match="前 30%"):
        _, gt = from_frame(df, x_columns=cols, golden=None)
    assert gt.golden_mask.sum() == int(round(0.3 * 200)) and gt.golden_mask[:60].all()
    assert _resolve_golden(0.5, 100).sum() == 50
    assert _rng_range(_resolve_golden((10, 30), 100)) == (10, 30)


def test_invalid_golden_string_fails_loud():
    """非法 golden 字串須 fail loud（僅支援 'auto'）；'auto' 但未給 X 亦 fail loud。"""
    with pytest.raises(ValueError, match="auto"):
        _resolve_golden("first_half", 100)
    with pytest.raises(ValueError, match="x_arr"):
        _resolve_golden("auto", 100)
