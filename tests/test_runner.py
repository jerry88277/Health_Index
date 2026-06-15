"""G2 線上評分 runner + 資料源 WHY 測試（Rule 9）。

marquee WHY：線上模擬重放公開資料集，模型 fit 於 golden A，時間線必須體現三條 DoD——golden 段健康
不告警、換產品/殘留飄移段告警、且**乾淨回歸 A 與殘留飄移 A 可區分**。當 runner 退化成「全告警」或
「全不告警」時，下列測試失敗。resume-safe（重啟接續）與 persistence_k（濾單窗毛刺）為線上必需性質。
"""

import numpy as np
import pytest

from health_index.adapters import registry
from health_index.deploy.bundle import build_bundle
from health_index.deploy.runner import (
    RunnerState,
    load_state,
    poll_once,
    run_replay,
    save_state,
)
from health_index.deploy.sources import FrameSource, PISource, replay_from_dataset
from health_index.health import HealthIndex


def _model_and_source(seed=5, ds_strength=1.2):
    ds, gt = registry.build("synthetic", seed=seed, drift_strength=ds_strength)
    cols = list(gt.x_columns)
    Xg = ds.frame.loc[np.asarray(gt.golden_mask), cols].to_numpy()
    bundle = build_bundle("A", HealthIndex().fit(Xg), cols, golden=Xg, created_at="t")
    src = FrameSource(ds.frame, cols)
    return bundle, src, gt


def test_replay_timeline_reflects_dod():
    """marquee：重放整段——golden 窗健康不告警、換產品/殘留飄移窗告警（隱性飄移被抓）。"""
    bundle, src, gt = _model_and_source()
    scores = run_replay(bundle, src, window=60, compute_fwer=False)
    gm, dm = np.asarray(gt.golden_mask), np.asarray(gt.drift_mask)
    golden_w = [s for s in scores if gm[s.start : s.end].all()]
    drift_w = [s for s in scores if dm[s.start : s.end].any()]
    assert golden_w and drift_w
    assert all(s.health_index > 0.8 and not s.raw_alarm for s in golden_w)  # golden 健康
    assert all(s.health_index < 0.6 and s.raw_alarm for s in drift_w)  # 殘留飄移被抓


def test_clean_reentry_distinguished_from_drift_reentry():
    """marquee（DoD#3）：乾淨回歸 A（換產品後的同 grade A、非 drift）健康，而殘留飄移 A 告警——
    這是本系統存在的理由。當兩者無法區分時失敗。"""
    bundle, src, gt = _model_and_source()
    scores = run_replay(bundle, src, window=60, compute_fwer=False)
    gm, dm = np.asarray(gt.golden_mask), np.asarray(gt.drift_mask)
    grade = src.frame["grade_label"].to_numpy()
    # 乾淨回歸 A：grade==A、非 golden、非 drift
    clean = [s for s in scores if grade[s.start] == "A" and not gm[s.start : s.end].all() and not dm[s.start : s.end].any()]
    drift = [s for s in scores if dm[s.start : s.end].any()]
    assert clean and drift
    assert all(s.health_index > 0.8 and not s.raw_alarm for s in clean)  # 乾淨回歸不誤報
    assert all(s.raw_alarm for s in drift)  # 殘留飄移告警
    assert min(s.health_index for s in clean) - max(s.health_index for s in drift) > 0.3  # 明確分離


def test_poll_once_resume_safe():
    """WHY（重啟安全）：把整段拆成兩次 poll，游標續推、不重複處理、連續告警數跨 poll 保留——
    結果與一次跑完逐窗相同。"""
    bundle, src, _ = _model_and_source()
    full = run_replay(bundle, src, window=60, compute_fwer=False)
    # 兩段 poll：先處理一半資料量（用較短 source 模擬「資料尚未到齊」）
    half = FrameSource(src.frame.iloc[:600], src.x_columns)
    s1, st1 = poll_once(bundle, half, RunnerState(), window=60, compute_fwer=False)
    s2, st2 = poll_once(bundle, src, st1, window=60, compute_fwer=False)  # 餘下資料到齊
    merged = s1 + s2
    assert len(merged) == len(full)
    assert [w.start for w in merged] == [w.start for w in full]  # 無重疊無遺漏
    assert all(np.isclose(a.health_index, b.health_index) for a, b in zip(merged, full))
    # 連續告警數跨 poll 邊界保留（st1 的計數被 s2 接續）
    assert all(m.consecutive == f.consecutive for m, f in zip(merged, full))


def test_persistence_k_filters_single_window_blips():
    """WHY：連續 k 窗告警才 persisted（濾單窗毛刺）。第一個告警窗 consecutive=1 不 persisted；
    連續第 k 窗才 persisted。"""
    bundle, src, _ = _model_and_source()
    scores = run_replay(bundle, src, window=60, persistence_k=2, compute_fwer=False)
    first_alarm = next(s for s in scores if s.raw_alarm)
    assert first_alarm.consecutive == 1 and first_alarm.persisted_alarm is False
    # 其後連續第二個告警窗 → persisted
    idx = scores.index(first_alarm)
    assert scores[idx + 1].raw_alarm and scores[idx + 1].consecutive == 2 and scores[idx + 1].persisted_alarm is True


def test_state_json_roundtrip(tmp_path):
    """WHY：狀態存檔/載入逐欄保留（重啟接續）；檔不存在回初始狀態（首次啟動）。"""
    st = RunnerState(cursor=720, consecutive_alarm=3)
    p = save_state(st, str(tmp_path / "state.json"))
    st2 = load_state(p)
    assert st2.cursor == 720 and st2.consecutive_alarm == 3
    assert load_state(str(tmp_path / "missing.json")) == RunnerState()  # 首次啟動


def test_framesource_mismatch_fails_loud():
    """WHY：x_columns 不存在於 frame → fail-loud（線上接錯 tag 不靜默跑出垃圾）。"""
    _, src, _ = _model_and_source()
    with pytest.raises(ValueError, match="x_columns"):
        FrameSource(src.frame, ["no_such_col"])


def test_replay_from_dataset_and_delayed_y():
    """WHY：replay_from_dataset 便利建源；延遲 Y 語義——只回游標前已觀測的 Y（被動分析）。"""
    src, gt = replay_from_dataset("synthetic", seed=1)
    assert len(src) > 0 and src.x_columns == gt.x_columns
    early = src.y_arrivals_until(100)
    late = src.y_arrivals_until(len(src))
    assert len(late) >= len(early)  # 游標推進→更多 Y「到達」


def test_pisource_is_honest_stub():
    """WHY（Rule 12）：PISource 為 stub，建構即 NotImplementedError 並指向 checklist，不假裝可用。"""
    with pytest.raises(NotImplementedError, match="NOT VERIFIED|stub|現場"):
        PISource()
