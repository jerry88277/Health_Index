"""線上模擬 demo 的可測 orchestration（4 步流程的邏輯核心；UI 殼只呼叫本層）。

四步（docs/deployment_plan.md §7）：選定資料範圍 → 建立模型 → 確認模擬資料 → 查看健康指標。
本層回傳**可序列化** dict（UI 框架無關、可單元測試）；UI（Dash）只負責呈現。

瓶子優先：資料源用公開資料集（registry），PI 為 stub。
"""

from __future__ import annotations

import glob
import os
import warnings

import numpy as np

from ..adapters import registry
from ..config import DEFAULT
from ..health import HealthIndex
from ..interface import GRADE_LABEL, TIMESTAMP, Y_VALUE
from ..y_health import YHealthIndex
from .acceptance import acceptance_from_dataset
from .alarms import build_alarm_event
from .bundle import build_bundle, load, save
from .events import IncidentStore
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
    yh = bundle.y_health  # L3 映射模組（軟測量）；有則每窗附 Ŷ vs 實際 Y（供對照子圖）
    yvals = ds.frame[Y_VALUE].to_numpy(dtype=float) if (yh is not None and Y_VALUE in ds.frame.columns) else None
    ts_col = ds.frame[TIMESTAMP] if TIMESTAMP in ds.frame.columns else None  # wall-clock（對齊 DCS/historian）
    points = []
    for s in scores:
        Xw = src.x_slice(s.start, s.end)
        pt = {
            "start": s.start,
            "end": s.end,
            "ts": str(ts_col.iloc[s.start]) if ts_col is not None else None,  # 窗起點真實時間戳
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
        if yh is not None:  # L3 映射：Ŷ + conformal 帶 + 實際 Y（窗內有觀測才有）→ Ŷ vs Y 對照
            yhat = yh.ss_.predict(Xw)
            pt["yhat_mean"] = round(float(np.mean(yhat)), 4)
            pt["yhat_band"] = round(float(np.mean(yh._band_half(Xw))), 4)
            yw = yvals[s.start : s.end]
            obs = np.isfinite(yw)
            pt["y_actual_mean"] = round(float(yw[obs].mean()), 4) if bool(obs.any()) else None
        points.append(pt)
    return {
        "product": bundle.product,
        "window": int(window),
        "points": points,
        "n_alarms": int(sum(p["persisted_alarm"] for p in points)),
        "has_y_mapping": yh is not None,  # 前端據此決定是否畫 Ŷ vs Y 子圖
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
    # 真偽一句話結論（現場工程師：把數字翻成判斷）。確定性規則（Rule 5）：可信度 + 多層一致 + 是否告警。
    n_bad = sum(1 for k in ("L1", "L2", "L4") if detail["layers"][k]["unhealthy"])
    conf, alarm = detail["confidence"], detail["alarm"]
    if not alarm:
        verdict = {"label": "正常", "tone": "ok", "reason": "未達告警門檻"}
    elif conf < 0.6:
        verdict = {"label": "存疑（外推）", "tone": "warn",
                   "reason": f"可信度 {conf} 偏低，操作點可能在建模域外；先觀察、對照歷史趨勢再判"}
    elif n_bad >= 2:
        verdict = {"label": "可信告警", "tone": "bad",
                   "reason": f"可信度 {conf} 高且 {n_bad} 層一致異常；建議現場查下列肇因參數"}
    else:
        verdict = {"label": "存疑（單層/邊緣）", "tone": "warn",
                   "reason": f"僅 {n_bad} 層異常；建議持續觀察、確認非雜訊"}
    detail["verdict"] = verdict
    return detail


def acceptance_summary(name: str, *, holdout_frac: float = 0.5, window: int = 60, **build_kwargs) -> dict:
    """建模後驗收摘要（製程工程師簽核依據）：時間連續 hold-out 的 golden FPR / drift recall / SPC-blind / 裁決。

    接 ``acceptance.acceptance_from_dataset``（取代前端寫死的「可上線」文案）；資料/驗收失敗回 available=False。
    compute_fwer=False 以維建模流程互動速度（Rule 6）。
    """
    try:
        r = acceptance_from_dataset(name, holdout_frac=holdout_frac, window=window, compute_fwer=False, **build_kwargs)
    except Exception as e:  # 資料缺/golden 太短等 → 誠實標不可驗收，不假裝可上線（Rule 12）
        return {"available": False, "error": str(e)}
    return {
        "available": True,
        "holdout_golden_fpr": round(float(r.holdout_golden_fpr), 4),
        "fpr_ok": bool(r.fpr_ok),
        "drift_recall": None if r.drift_recall is None else round(float(r.drift_recall), 4),
        "recall_ok": r.recall_ok,
        "spc_blind": r.spc_blind,
        "passed": bool(r.passed),
        "verdict": r.verdict(),
    }


def monitoring_overview(models_dir: str = "models", *, window: int = 60) -> list[dict]:
    """監控總覽（作業員/處長第一眼）：列出已建模型的**當前健康紅綠燈**（評最後一窗），非僅檔名。

    product==資料源名（demo 慣例）→ 重建資料集評最後一窗 health/alarm。資料源不可得則標 data_unavailable。
    """
    out: list[dict] = []
    for p in sorted(glob.glob(os.path.join(models_dir, "*.joblib"))):
        product = os.path.splitext(os.path.basename(p))[0]
        rec = {"product": product, "bundle_path": p, "health": None, "alarm": None, "status": "unknown"}
        try:
            b = load(p)
            ds, gt = registry.build(product)
            X = ds.frame[list(b.x_columns)].to_numpy(dtype=float)
            Xw = X[-window:] if len(X) >= window else X
            rec["health"] = round(float(b.health.health_index(Xw)), 3)
            rec["alarm"] = bool(b.health.alarm(Xw, compute_fwer=False))
            rec["status"] = "alarm" if rec["alarm"] else "healthy"
        except Exception:  # 資料源不在 registry / 檔損 → 誠實標，不杜撰健康度
            rec["status"] = "data_unavailable"
        out.append(rec)
    return out


def plant_overview(models_dir: str = "models", *, incidents_path: str | None = None, window: int = 60) -> dict:
    """全廠視圖（生產處長，P2）：各裝置（=模型/產品）當前健康燈 + 未結事件數，彙總成全廠總燈。

    全廠總燈：任一裝置告警→alarm；皆健康→healthy；無裝置→empty。incidents_path 提供時附各裝置 active 事件數。
    """
    assets = monitoring_overview(models_dir, window=window)
    if incidents_path:
        st = IncidentStore(incidents_path)
        for a in assets:
            a["active_incidents"] = sum(1 for i in st.list(product=a["product"]) if i["status"] in ("open", "ack"))
    n_alarm = sum(1 for a in assets if a["status"] == "alarm")
    plant_status = "empty" if not assets else ("alarm" if n_alarm else "healthy")
    return {"plant_status": plant_status, "n_assets": len(assets), "n_alarm": n_alarm, "assets": assets}


def incidents_to_csv(incidents: list[dict]) -> str:
    """事件清單 → CSV 字串（工程師/處長匯出、稽核留痕，P1）。"""
    import csv
    import io

    cols = ["id", "product", "detected_at", "severity", "status", "health", "confidence", "top_cause",
            "ack_by", "ack_at", "closed_at", "mttr_sec", "close_note"]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    for it in incidents:
        w.writerow(it)
    return buf.getvalue()


def timeline_to_csv(points: list[dict]) -> str:
    """健康時間線 → CSV 字串（匯出窗級指標，P1）。"""
    import csv
    import io

    cols = ["ts", "start", "end", "region", "health_index", "confidence", "spe_mean", "t2_mean", "gsi_mean",
            "raw_alarm", "persisted_alarm"]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    for p in points:
        w.writerow(p)
    return buf.getvalue()
