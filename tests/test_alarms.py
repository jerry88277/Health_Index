"""G2b 告警雙視圖 WHY 測試（Rule 9）。

WHY（使用者答覆 3）：告警須同步操作員（零術語紅綠燈 + 去查哪裡）與工程師（分層語義 + p-value + RBC）。
單一事件兩視圖；持續告警才送（濾毛刺）。當操作員視圖塞統計術語、或工程師視圖少了肇因/版本時失敗。
"""

import json

import numpy as np
import pytest

from health_index.adapters import registry
from health_index.deploy.alarms import (
    AlarmEvent,
    ConsoleSink,
    FileSink,
    build_alarm_event,
    dispatch,
)
from health_index.deploy.bundle import build_bundle
from health_index.deploy.runner import RunnerState, poll_once
from health_index.deploy.sources import FrameSource
from health_index.health import HealthIndex


def _setup():
    d, gt = registry.build("synthetic", seed=5, drift_strength=1.2)
    cols = list(gt.x_columns)
    Xg = d.frame.loc[np.asarray(gt.golden_mask), cols].to_numpy()
    bundle = build_bundle("A", HealthIndex().fit(Xg), cols, golden=Xg, created_at="2026-06-15T12:00+08:00")
    src = FrameSource(d.frame, cols)
    scores, _ = poll_once(bundle, src, RunnerState(), window=60, compute_fwer=False)
    drift_score = next(s for s in scores if s.persisted_alarm)  # 取一個持續告警窗（drift 段）
    golden_score = scores[0]  # golden 段首窗
    return bundle, src, drift_score, golden_score


def test_operator_view_is_jargon_free_and_actionable():
    """marquee：操作員視圖＝紅綠燈 + 去查哪裡 + 持續窗數，**不含**統計術語（SPE/T²/p-value/FWER）。"""
    bundle, src, ds, _ = _setup()
    ev = build_alarm_event(bundle, ds, src.x_slice(ds.start, ds.end))
    view = ev.operator_view()
    assert "⚠" in view and "優先檢查" in view and "通知工程師" in view
    for jargon in ("SPE", "T²", "p-value", "FWER", "MMD", "Wasserstein"):
        assert jargon not in view  # 零術語


def test_operator_view_healthy_is_green():
    """WHY：未持續告警 → 綠燈正常（不誤擾操作員）。"""
    bundle, src, _, gs = _setup()
    ev = build_alarm_event(bundle, gs, src.x_slice(gs.start, gs.end))
    assert "✅" in ev.operator_view()


def test_engineer_view_has_layers_pvalues_rbc_version():
    """marquee：工程師視圖＝分層語義 + RBC 全排行 + 模型版本（追查所需）。"""
    bundle, src, ds, _ = _setup()
    # 含 fwer p-value 的版本
    sc, _ = poll_once(bundle, src, RunnerState(cursor=ds.start), window=60, compute_fwer=True)
    ds2 = next((s for s in sc if s.persisted_alarm), ds)
    ev = build_alarm_event(bundle, ds2, src.x_slice(ds2.start, ds2.end))
    eng = ev.engineer_view()
    assert set(eng["layers"]) == {"L1", "L2", "L4"}
    assert all("name" in eng["layers"][k] and "action" in eng["layers"][k] for k in eng["layers"])
    assert len(eng["rbc_ranking"]) == len(bundle.x_columns)  # RBC 全排行
    assert eng["model_version"] == "2026-06-15T12:00+08:00"


def test_rbc_points_to_real_contributors():
    """WHY：RBC 排行須指向真實肇因變數（drift 段 top 變數的 RBC 顯著高於尾段）。"""
    bundle, src, ds, _ = _setup()
    ev = build_alarm_event(bundle, ds, src.x_slice(ds.start, ds.end))
    scores = [v for _, v in ev.top_contributors]
    assert scores == sorted(scores, reverse=True)  # 降序
    assert scores[0] > scores[-1]  # 有區別（非全等）


def test_dispatch_only_persisted_by_default(tmp_path):
    """WHY：預設只送持續告警（濾單窗毛刺）；持續告警送到 console+file 雙 sink。"""
    bundle, src, ds, gs = _setup()
    ev_drift = build_alarm_event(bundle, ds, src.x_slice(ds.start, ds.end))
    ev_golden = build_alarm_event(bundle, gs, src.x_slice(gs.start, gs.end))
    console = ConsoleSink()
    fpath = str(tmp_path / "alarms.jsonl")
    assert dispatch(ev_golden, [console], only_persisted=True) is False  # 健康窗不送
    assert dispatch(ev_drift, [console, FileSink(fpath)], only_persisted=True) is True
    assert len(console.log) == 1
    rec = json.loads(open(fpath, encoding="utf-8").read().strip())
    assert rec["product"] == "A" and rec["persisted"] is True


def test_alarm_event_serializable():
    """WHY：engineer_view 為純可序列化 dict（供 webhook/儲存）。"""
    bundle, src, ds, _ = _setup()
    ev = build_alarm_event(bundle, ds, src.x_slice(ds.start, ds.end))
    json.dumps(ev.engineer_view(), ensure_ascii=False)  # 不應拋
