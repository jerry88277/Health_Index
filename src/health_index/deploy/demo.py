"""線上模擬 demo 的可測 orchestration（4 步流程的邏輯核心；UI 殼只呼叫本層）。

四步（docs/deployment_plan.md §7）：選定資料範圍 → 建立模型 → 確認模擬資料 → 查看健康指標。
本層回傳**可序列化** dict（UI 框架無關、可單元測試）；UI（Dash）只負責呈現。

瓶子優先：資料源用公開資料集（registry），PI 為 stub。
"""

from __future__ import annotations

import os
import warnings

import numpy as np

from ..adapters import registry
from ..config import DEFAULT
from ..health import HealthIndex
from ..interface import GRADE_LABEL, Y_VALUE
from ..y_health import YHealthIndex
from .alarms import build_alarm_event
from .bundle import build_bundle, load, save
from .runner import WindowScore, run_replay
from .sources import FrameSource


def available_datasets() -> list[str]:
    """可選的公開資料集（registry 已註冊者）。"""
    return registry.available()


def _segments(gt) -> list[dict]:
    return [{"start": s.start, "end": s.end, "label": s.label} for s in gt.segments]


def dataset_overview(name: str, **build_kwargs) -> dict:
    """步驟1：資料集概覽——列數/維度/分段/golden 建議範圍（供使用者選定資料範圍）。"""
    ds, gt = registry.build(name, **build_kwargs)
    gm = np.asarray(gt.golden_mask)
    gidx = np.flatnonzero(gm)
    golden_range = [int(gidx[0]), int(gidx[-1] + 1)] if gidx.size else None
    return {
        "dataset": name,
        "n_rows": int(len(ds.frame)),
        "n_features": int(len(gt.x_columns)),
        "x_columns": list(gt.x_columns),
        "segments": _segments(gt),
        "golden_suggested": golden_range,  # 真值建議；UI 可讓使用者覆寫或選 'auto'
        "has_labeled_drift": bool(gt.drift_mask is not None),
    }


def build_and_save_model(
    name: str,
    *,
    golden=None,
    models_dir: str = "models",
    created_at: str,
    product: str | None = None,
    **build_kwargs,
) -> dict:
    """步驟2：以選定 golden 範圍建模 → bundle → 存檔。回傳 bundle 路徑與指紋摘要。

    Args:
        name: 資料集名。
        golden: golden 範圍——(start,end) | bool mask | float比例 | 'auto'（None→用真值 golden_mask）。
        models_dir: bundle 存放目錄（自動建立）。
        created_at: 建模時間字串（git 時間權威；UI 由呼叫端提供）。
        product: 模型/產品識別（None→用 name）。

    Returns:
        {bundle_path, product, golden_range, fingerprint_hi, n_golden}。
    """
    ds, gt = registry.build(name, **build_kwargs)
    cols = list(gt.x_columns)
    fr = ds.frame
    if golden is None:
        gm = np.asarray(gt.golden_mask)
    else:  # 使用者選 (start,end) / 'auto' / 比例 → 重用 from_frame 的 golden 解析
        from ..adapters.dataframe import _resolve_golden

        gm = _resolve_golden(golden, len(fr), x_arr=fr[cols].to_numpy(dtype=float), config=DEFAULT)
    Xg = fr.loc[gm, cols].to_numpy(dtype=float)
    hi = HealthIndex().fit(Xg)
    # C2：有軟量測 Y 時一併 fit YHealthIndex 存入 bundle（供 demo 顯示 Ŷ + Y-confirmed 可信度）。
    # 閘 n>p（非僅 ≥2）：避免退化軟測量（紅隊 RT2：n≤p 時 GPR/PLS 過擬合→band=0、has_y_health 過度承諾）。
    y_health = None
    if Y_VALUE in fr.columns:
        yg = fr.loc[gm, Y_VALUE].to_numpy(dtype=float)
        if int(np.isfinite(yg).sum()) >= max(2, Xg.shape[1] + 1):
            try:
                y_health = YHealthIndex().fit(Xg, yg)
            except (ValueError, RuntimeError) as e:  # 訓練不足/常數X等 → 無 Y 健康；warn surface 不靜默（Rule 12）
                warnings.warn(f"YHealthIndex fit 失敗（{e}）→ bundle 無 Y 健康", RuntimeWarning, stacklevel=2)
                y_health = None
    bundle = build_bundle(product or name, hi, cols, golden=Xg, created_at=created_at, y_health=y_health)
    os.makedirs(models_dir, exist_ok=True)
    path = os.path.join(models_dir, f"{product or name}.joblib")
    save(bundle, path)
    gidx = np.flatnonzero(np.asarray(gm))
    return {
        "bundle_path": path,
        "product": bundle.product,
        "golden_range": [int(gidx[0]), int(gidx[-1] + 1)] if gidx.size else None,
        "fingerprint_hi": float(bundle.fingerprint_hi),
        "n_golden": int(len(Xg)),
        "has_y_health": bundle.y_health is not None,  # 有軟量測→demo 可顯示 Ŷ + Y-confirmed 可信度
    }


def replay_preview(name: str, *, window: int = 60, **build_kwargs) -> dict:
    """步驟3：確認將被重放的模擬資料——列數/分段/預估窗數（讓使用者確認再跑）。"""
    ds, gt = registry.build(name, **build_kwargs)
    n = len(ds.frame)
    return {
        "dataset": name,
        "n_rows": int(n),
        "window": int(window),
        "n_windows_est": int(max(0, n // window)),
        "segments": _segments(gt),
        "has_labeled_drift": bool(gt.drift_mask is not None),
    }


def score_timeline(
    bundle_path: str,
    name: str,
    *,
    window: int = 60,
    compute_fwer: bool = False,
    persistence_k: int | None = None,
    **build_kwargs,
) -> dict:
    """步驟4：載入模型 → 重放資料集 → 回傳健康指標時間線（含已知 drift 標記供對照）。

    Returns:
        {product, window, points:[{start,end,health_index,raw_alarm,persisted_alarm,region,...}],
         golden_range, drift_ranges}。region∈{golden,clean_reentry,drift,other}。
    """
    bundle = load(bundle_path)  # verify=True：指紋不符即拒載
    ds, gt = registry.build(name, **build_kwargs)
    src = FrameSource(ds.frame, list(gt.x_columns))
    scores = run_replay(bundle, src, window=window, compute_fwer=compute_fwer, persistence_k=persistence_k)
    gm = np.asarray(gt.golden_mask)
    dm = np.asarray(gt.drift_mask) if gt.drift_mask is not None else np.zeros(len(ds.frame), bool)
    grade = ds.frame[GRADE_LABEL].to_numpy() if GRADE_LABEL in ds.frame.columns else None
    golden_label = grade[np.flatnonzero(gm)[0]] if (grade is not None and gm.any()) else None

    def region(s, e):
        if gm[s:e].all():
            return "golden"
        if dm[s:e].any():
            return "drift"
        if grade is not None and golden_label is not None and grade[s] == golden_label:
            return "clean_reentry"  # 同 golden grade、非 golden 段、非 drift＝乾淨回歸
        return "other"

    m = bundle.health.mspc_
    points = []
    for s in scores:
        Xw = src.x_slice(s.start, s.end)
        points.append(
            {
                "start": s.start,
                "end": s.end,
                "health_index": round(s.health_index, 4),
                "raw_alarm": s.raw_alarm,
                "persisted_alarm": s.persisted_alarm,
                "consecutive": s.consecutive,
                "region": region(s.start, s.end),
                "subscores": {k: round(v, 3) for k, v in s.subscores.items()},
                # X-only 多變量指標（cheap，無 permutation）：供時間線呈現「SPE 升起」等 AVM 細節（C1）
                "spe_mean": round(float(m.spe(Xw).mean()), 4),
                "t2_mean": round(float(m.t2(Xw).mean()), 4),
                "gsi_mean": round(float(m.gsi(Xw).mean()), 4),
                "confidence": round(float(bundle.health.confidence(Xw)), 4),  # C2：HI 判讀可信度（域相似度）
            }
        )
    return {
        "product": bundle.product,
        "window": int(window),
        "points": points,
        "n_alarms": int(sum(p["persisted_alarm"] for p in points)),
    }


def window_detail(
    bundle_path: str,
    name: str,
    start: int,
    end: int,
    *,
    compute_fwer: bool = True,
    **build_kwargs,
) -> dict:
    """單一窗的**詳細 AVM 指標**（點選時間線某窗時的下鑽，C1）：GSI/T²/SPE 原始值與控制限、RBC 肇因
    排行、各層 p-value 與分層語義（重用 alarms.engineer_view）。

    回答使用者「demo 看不到 GSI/RI 等詳細指標」：本函式把偵測器內部量（原 subscores 摺疊掉的 GSI/T²/SPE/
    RBC/p-value）攤開供工程師下鑽。Y 側（軟測量 Ŷ + 可信度）在 C2 另接（需 bundle.y_health）。

    Args:
        bundle_path: 已存檔 bundle 路徑（載入走指紋 verify）。
        name: 資料集名（重建以取該窗 X）。
        start, end: 窗的列區間 [start, end)。
        compute_fwer: 是否算各層 p-value（較貴；False 則 p_value 全 None）。

    Returns:
        dict：engineer_view（layers/rbc_ranking/model_version）+ ``mspc``（GSI/T²/SPE 原始與限、越限比例）
        + ``subscores`` + ``fwer_pvalues`` + ``alarm``/``is_alarm``。
    """
    bundle = load(bundle_path)
    ds, _gt = registry.build(name, **build_kwargs)
    cols = list(bundle.x_columns)
    X = ds.frame.iloc[int(start) : int(end)][cols].to_numpy(dtype=float)
    hi = bundle.health
    m = hi.mspc_
    t2, spe, gsi = m.t2(X), m.spe(X), m.gsi(X)
    fwer = None
    if compute_fwer:
        try:
            fwer = {k: float(v) for k, v in hi.fwer_pvalues(X).items()}
        except Exception:  # 校準不可用（golden 太小等）→ p_value 留 None，不中斷下鑽
            fwer = None
    score = WindowScore(
        start=int(start),
        end=int(end),
        health_index=float(hi.health_index(X)),
        subscores={k: float(v) for k, v in hi.subscores(X).items()},
        hard_gates={k: bool(v) for k, v in hi.hard_gates(X).items()},
        raw_alarm=bool(hi.alarm(X, compute_fwer=compute_fwer, _pvalues=fwer)),
        persisted_alarm=False,
        consecutive=0,
        fwer=fwer,
    )
    detail = build_alarm_event(bundle, score, X).engineer_view()  # layers + rbc_ranking + model_version
    detail["alarm"] = score.raw_alarm
    detail["is_alarm"] = bool(hi.is_alarm(X))
    detail["subscores"] = {k: round(v, 4) for k, v in score.subscores.items()}
    detail["fwer_pvalues"] = {k: round(float(v), 4) for k, v in fwer.items()} if fwer else None
    detail["mspc"] = {  # AVM 原始量（subscores 摺疊掉的細節）
        "GSI_mean": round(float(gsi.mean()), 4),
        "T2_mean": round(float(t2.mean()), 4),
        "T2_limit": round(float(m.t2_lim_), 4),
        "T2_exceed_frac": round(float((t2 > m.t2_lim_).mean()), 4),
        "SPE_mean": round(float(spe.mean()), 4),
        "SPE_limit": round(float(m.spe_lim_), 4),
        "SPE_exceed_frac": round(float((spe > m.spe_lim_).mean()), 4),
    }
    detail["confidence"] = round(float(hi.confidence(X)), 4)  # C2：HI 判讀可信度（T² 操作域相似度）
    # 軟測量區塊（Y 側）：Ŷ + conformal 帶 + Y-confirmed 可信度（X→Y 模型是否還成立，正交於 X 側 HI）。
    yh = bundle.y_health
    if yh is None:
        detail["soft_sensor"] = {"available": False}
    else:
        yw = ds.frame.iloc[int(start) : int(end)][Y_VALUE].to_numpy(dtype=float)
        obs = np.isfinite(yw)
        n_obs = int(obs.sum())
        ss_block: dict = {"available": True, "n_y_obs": n_obs, "cp_available": bool(yh.ss_.cp_available)}
        if n_obs > 0:
            Xo = X[obs]
            yhat = yh.ss_.predict(Xo)
            band = yh._band_half(Xo)  # CP 半寬 or 2×std（與 /softsensor 同邏輯，內部 helper 重用）
            mh = yh.map_health(X, yw)  # Y-confirmed 可信度（殘差相對可信帶）；觀測 < y_map_min_obs 回 None
            ss_block.update(
                {
                    "yhat_mean": round(float(np.mean(yhat)), 4),
                    "y_actual_mean": round(float(np.mean(yw[obs])), 4),
                    "band_half_mean": round(float(np.mean(band)), 4),
                    "map_health": round(float(mh), 4) if mh is not None else None,
                }
            )
        detail["soft_sensor"] = ss_block
    return detail
