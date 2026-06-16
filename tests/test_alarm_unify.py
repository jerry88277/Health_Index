"""A. ``HealthIndex.alarm()`` 單一權威告警 WHY 測試（Rule 9）。

WHY（is_alarm 統一）：線上實際出口的告警＝**is_alarm（H8 快路徑）∨ fwer_alarm（AC-6 嚴格 FWER）**。
此前該聯集由 runner.poll_once 自己拼（呼叫端各自重複），最弱飄移（ds≲0.3）只由 fwer leg 補。alarm()
把聯集收口為單一加法方法（不改 is_alarm 本體，保 sentinel/portability『只用 golden、零行為改變』契約）。

下列測試殺死 mutant：
- 把 alarm() 還原成「只回 is_alarm」→ test_alarm_includes_fwer_leg 失敗（fwer 觸發但 is_alarm 不觸發時漏報）。
- 拿掉 try/except fail-safe → test_alarm_degrades_when_fwer_raises 失敗。
- 拿掉 compute_fwer 快路徑 → test_alarm_compute_fwer_false_skips_fwer 失敗。
"""

import numpy as np
import pytest

from health_index.adapters import synthetic as syn
from health_index.deploy.bundle import build_bundle
from health_index.deploy.runner import RunnerState, poll_once
from health_index.deploy.sources import FrameSource
from health_index.health import HealthIndex


def _golden(seed=5, ds=0.8):
    d, gt = syn.generate(seed=seed, drift_strength=ds)
    cols = list(gt.x_columns)
    Xg = d.frame.loc[np.asarray(gt.golden_mask), cols].to_numpy()
    return HealthIndex().fit(Xg), Xg, d, gt, cols


def test_alarm_includes_fwer_leg():
    """marquee mutant-kill：is_alarm=False 但 fwer_alarm=True 時 alarm 必 True（證 fwer leg 納入）。
    用 monkeypatch 鎖定純聯集邏輯（不依資料）；revert 成『只回 is_alarm』→ 第一斷言失敗。"""
    hi, Xg, *_ = _golden()
    X = Xg[:60]
    hi.is_alarm = lambda _X: False                          # type: ignore[method-assign]
    hi.fwer_alarm = lambda _X, alpha=None, _pvalues=None: True   # type: ignore[method-assign]
    assert hi.alarm(X) is True               # 聯集納入 fwer leg
    hi.fwer_alarm = lambda _X, alpha=None, _pvalues=None: False  # type: ignore[method-assign]
    assert hi.alarm(X) is False              # 兩軌皆 False → False


def test_alarm_short_circuits_on_is_alarm():
    """WHY（Rule 6 成本）：is_alarm 已 True → 聯集必 True，不應再呼叫昂貴 fwer。以會炸的 fwer 證短路。"""
    hi, Xg, *_ = _golden()
    hi.is_alarm = lambda _X: True            # type: ignore[method-assign]

    def _boom(_X, alpha=None, _pvalues=None):
        raise AssertionError("is_alarm 已 True 時不該呼叫 fwer_alarm（短路失效）")

    hi.fwer_alarm = _boom                     # type: ignore[method-assign]
    assert hi.alarm(Xg[:60]) is True          # 未觸發 _boom 即代表短路


def test_alarm_compute_fwer_false_skips_fwer():
    """WHY：compute_fwer=False → 只跑 is_alarm 快路徑，完全不碰 fwer（省 permutation/bootstrap）。"""
    hi, Xg, *_ = _golden()
    hi.is_alarm = lambda _X: False           # type: ignore[method-assign]

    def _boom(_X, alpha=None, _pvalues=None):
        raise AssertionError("compute_fwer=False 時不該呼叫 fwer")

    hi.fwer_alarm = _boom                     # type: ignore[method-assign]
    assert hi.alarm(Xg[:60], compute_fwer=False) is False


def test_alarm_degrades_when_fwer_raises():
    """WHY（fail-safe，與 runner 既有韌性一致）：fwer 計算拋例外（校準不足/數值問題）→ 退回 is_alarm
    結果 + warn，不讓線上判決崩。拿掉 try/except → 本測試因未捕例外而失敗。"""
    hi, Xg, *_ = _golden()
    hi.is_alarm = lambda _X: False           # type: ignore[method-assign]

    def _raise(_X):
        raise RuntimeError("fwer 校準不可用")

    hi.fwer_pvalues = _raise                  # type: ignore[method-assign]
    with pytest.warns(RuntimeWarning):
        assert hi.alarm(Xg[:60]) is False     # 退回 is_alarm（False）


def test_alarm_is_superset_of_is_alarm_on_real_data():
    """WHY（聯集只增不減）：掃過 golden+drift 各窗，is_alarm 為 True 處 alarm 必為 True，且 alarm 觸發
    窗數 ≥ is_alarm（fwer leg 只會補抓）。確定性、不依 monkeypatch。"""
    hi, Xg, d, gt, cols = _golden()
    X = d.frame[cols].to_numpy()
    w = 60
    starts = range(0, len(X) - w + 1, w)
    is_a = [hi.is_alarm(X[s : s + w]) for s in starts]
    al = [hi.alarm(X[s : s + w], compute_fwer=True) for s in starts]
    for a, b in zip(is_a, al):
        if a:
            assert b                          # is_alarm True ⇒ alarm True
    assert sum(al) >= sum(is_a)               # 聯集只增不減


def test_score_single_pass_equivalent_to_methods():
    """WHY（效能 dedup 正確性）：hi.score() 單次掃描須與逐一呼叫 subscores/health_index/hard_gates/alarm **等價**
    （只是不重複算昂貴 L4）。若 score() 與個別方法偏離 → 本測試失敗（防 dedup 改錯語義）。"""
    hi, Xg, d, gt, cols = _golden()
    for X in (Xg[:60], d.frame[cols].to_numpy()[-60:]):
        r = hi.score(X, compute_fwer=False)
        assert abs(r["health_index"] - hi.health_index(X)) < 1e-9
        assert r["hard_gates"] == hi.hard_gates(X)
        assert r["is_alarm"] == hi.is_alarm(X)
        assert r["alarm"] == hi.alarm(X, compute_fwer=False)


def test_score_compute_fwer_equals_alarm():
    """WHY：score(compute_fwer=True).alarm 等價 hi.alarm(compute_fwer=True)（is_alarm ∨ fwer）；附 p-value。"""
    hi, Xg, d, gt, cols = _golden()
    X = d.frame[cols].to_numpy()[-60:]
    r = hi.score(X, compute_fwer=True)
    assert r["alarm"] == hi.alarm(X, compute_fwer=True)
    assert r["pvalues"] is None or set(r["pvalues"]) == {"L1", "L2", "L4"}


def test_runner_raw_alarm_uses_alarm_method():
    """WHY（DRY 收口）：runner.poll_once 的 raw_alarm 須等於 bundle.health.alarm(X)——聯集邏輯只存在
    alarm() 一處。若 runner 重新自拼聯集而與 alarm() 偏離 → 本測試失敗。"""
    hi, Xg, d, gt, cols = _golden()
    b = build_bundle("A", hi, cols, golden=Xg, created_at="t")
    src = FrameSource(d.frame, cols)
    w = 60
    scores, _ = poll_once(b, src, RunnerState(), window=w, compute_fwer=True)
    X = d.frame[cols].to_numpy()
    for s in scores:
        expected = hi.alarm(X[s.start : s.end], compute_fwer=True)
        assert s.raw_alarm == expected
