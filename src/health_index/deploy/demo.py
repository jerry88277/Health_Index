"""線上模擬 demo 的可測 orchestration（4 步流程的邏輯核心；UI 殼只呼叫本層）。

四步（docs/deployment_plan.md §7）：選定資料範圍 → 建立模型 → 確認模擬資料 → 查看健康指標。
本層回傳**可序列化** dict（UI 框架無關、可單元測試）；UI（Dash）只負責呈現。

瓶子優先：資料源用公開資料集（registry），PI 為 stub。
"""

from __future__ import annotations

import glob
import json
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
from .assets import AssetStore
from .bundle import build_bundle, load, save
from .events import IncidentStore
from .roi import estimate_roi
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


def dataset_preview(name: str, *, max_points: int = 500, **build_kwargs) -> dict:
    """步驟2 視覺化：資料的「標準化偏離度」時間線（每列 z-score 後的 RMS，越高＝越偏離全域平均）+ campaign
    分段 + 真值 golden 建議。供前端畫預覽圖讓使用者「看著選 golden」（非健康指標，僅選段輔助）。

    長資料集降採樣為 ≤max_points 個分箱均值（保互動）。確定性，無模型 fit（golden 尚未選，避免雞生蛋）。
    """
    ds, gt = registry.build(name, **build_kwargs)
    fr = ds.frame
    cols = list(gt.x_columns)
    X = fr[cols].to_numpy(dtype=float)
    mu = np.nanmean(X, axis=0)
    sd = np.nanstd(X, axis=0)
    sd[sd == 0] = 1.0
    z = (X - mu) / sd
    dev = np.sqrt(np.nanmean(z * z, axis=1))  # 每列偏離度（sigma 單位 RMS）；揭露暫態/位移
    n = len(dev)
    if n > max_points:  # 分箱均值降採樣
        edges = np.linspace(0, n, max_points + 1).astype(int)
        xs, vs = [], []
        for b in range(max_points):
            s, e = int(edges[b]), int(edges[b + 1])
            if e > s:
                xs.append((s + e) // 2)
                vs.append(round(float(np.nanmean(dev[s:e])), 3))
    else:
        xs = list(range(n))
        vs = [round(float(v), 3) for v in dev]
    ts_col = fr[TIMESTAMP] if TIMESTAMP in fr.columns else None
    xt = [str(ts_col.iloc[i]) for i in xs] if ts_col is not None else None
    gm = np.asarray(gt.golden_mask)
    gidx = np.flatnonzero(gm)
    segs = [{"id": s.id, "start": s.start, "end": s.end, "label": s.label} for s in gt.segments]
    return {
        "name": name, "n_rows": n, "series_x": xs, "series_v": vs, "series_t": xt,
        "segments": segs, "golden_suggested": [int(gidx[0]), int(gidx[-1] + 1)] if gidx.size else None,
    }


def golden_arg_from_spec(name: str, spec, **build_kwargs):
    """UI golden 規格 → ``build_and_save_model`` 接受的引數（接出後端 _resolve_golden 既有能力）。

    spec：``"auto"`` | ``(s,e)``/``[s,e]`` | ``{"range":[s,e]}`` | ``{"segments":[seg_id,...]}``（多段/非連續）。
    """
    if spec == "auto":
        return "auto"
    if isinstance(spec, dict) and "segments" in spec:
        ds, gt = registry.build(name, **build_kwargs)
        n = len(ds.frame)
        mask = np.zeros(n, dtype=bool)
        by_id = {s.id: s for s in gt.segments}
        for sid in spec["segments"]:
            seg = by_id.get(int(sid))
            if seg is not None:
                mask[seg.start : seg.end] = True
        if not mask.any():
            raise ValueError("未勾選任何有效 campaign 作為 golden")
        return mask
    if isinstance(spec, dict) and "range" in spec:
        return (int(spec["range"][0]), int(spec["range"][1]))
    if isinstance(spec, (list, tuple)) and len(spec) == 2:
        return (int(spec[0]), int(spec[1]))
    raise ValueError(f"非法 golden 規格: {spec!r}")


def resolve_golden_runs(name: str, spec, **build_kwargs) -> dict:
    """把 golden 規格解析為連續區間 runs（供前端預覽疊圖）+ 選取樣本數。auto 走變點切段。"""
    from ..adapters.dataframe import _resolve_golden

    arg = golden_arg_from_spec(name, spec, **build_kwargs)
    ds, gt = registry.build(name, **build_kwargs)
    n = len(ds.frame)
    x_arr = ds.frame[list(gt.x_columns)].to_numpy(dtype=float)
    m = np.asarray(_resolve_golden(arg, n, x_arr=x_arr, config=DEFAULT))
    runs, i = [], 0
    while i < n:
        if m[i]:
            j = i
            while j < n and m[j]:
                j += 1
            runs.append([int(i), int(j)])
            i = j
        else:
            i += 1
    return {"runs": runs, "n_selected": int(m.sum())}


def build_and_save_model(
    name: str,
    *,
    golden=None,
    models_dir: str = "models",
    created_at: str,
    product: str | None = None,
    features: list[str] | None = None,
    **build_kwargs,
) -> dict:
    """步驟2：以選定 golden 範圍建模 → bundle → 存檔。回傳 bundle 路徑與指紋摘要。

    Args:
        name: 資料集名。
        golden: golden 範圍——(start,end) | bool mask | float比例 | 'auto'（None→用真值 golden_mask）。
        models_dir: bundle 存放目錄（自動建立）。
        created_at: 建模時間字串（git 時間權威；UI 由呼叫端提供）。
        product: 模型/產品識別（None→用 name）。
        features: 監控特徵子集（None→全用）。存入 bundle.x_columns，scoring 自動只用這些欄（≥2，PCA 需求）。

    Returns:
        {bundle_path, product, golden_range, fingerprint_hi, n_golden, x_columns}。
    """
    ds, gt = registry.build(name, **build_kwargs)
    cols = list(gt.x_columns)
    if features:  # 特徵子集：保資料集原欄序，只取選定欄（≥2）
        sel = [c for c in cols if c in features]
        if len(sel) < 2:
            raise ValueError(f"監控特徵至少需 2 個（選到 {len(sel)}）；可用: {cols}")
        cols = sel
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
        "x_columns": list(cols),  # 實際監控的特徵子集（供前端顯示「監控 7/10 參數」）
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
    max_windows: int | None = None,
    **build_kwargs,
) -> dict:
    """步驟4：載入模型 → 重放資料集 → 回傳健康指標時間線（含已知 drift 標記供對照）。

    max_windows：時間線最多窗數（None→自動：高維 p>64 取 40、否則 150）。超過則加大 step **降採樣**，
    使高維資料集（如 uci p=128，逐窗 L4 permutation 昂貴）也能在互動時間內渲染，不卡 LOADING。

    Returns:
        {product, window, points:[...], n_alarms, has_y_mapping, subsampled, n_windows}。
    """
    bundle = load(bundle_path)  # verify=True：指紋不符即拒載
    ds, gt = registry.build(name, **build_kwargs)
    src = FrameSource(ds.frame, list(bundle.x_columns))  # 用模型實際監控的特徵子集（非全集）→ 子集模型維度對齊
    n = len(ds.frame)
    if max_windows is None:  # 高維逐窗評分昂貴 → 自動降採樣保互動（低維維持高解析）
        max_windows = 40 if len(bundle.x_columns) > 64 else 150
    full_windows = max(1, (n - window) // window + 1)
    step = window
    subsampled = False
    if full_windows > max_windows:
        step = max(window, n // max_windows)  # 加大 step → 非重疊抽樣，窗數受限
        subsampled = True
    scores = run_replay(bundle, src, window=window, step=step, compute_fwer=compute_fwer, persistence_k=persistence_k)
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
    cfg = bundle.config
    yvals = ds.frame[Y_VALUE].to_numpy(dtype=float) if (yh is not None and Y_VALUE in ds.frame.columns) else None
    ts_col = ds.frame[TIMESTAMP] if TIMESTAMP in ds.frame.columns else None  # wall-clock（對齊 DCS/historian）
    gy_mu = gy_sd = None  # 增量8：golden 期預測品質 Ŷ 基準（供 Ŷ 水準漂移 z）
    if yh is not None and gm.any():
        Xg = ds.frame.loc[gm, list(bundle.x_columns)].to_numpy(dtype=float)
        gyh = yh.ss_.predict(Xg)
        gy_mu, gy_sd = float(np.mean(gyh)), float(np.std(gyh))
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
            wy_mean = float(np.mean(yhat))
            pt["yhat_mean"] = round(wy_mean, 4)
            pt["yhat_band"] = round(float(np.mean(yh._band_half(Xw))), 4)
            yw = yvals[s.start : s.end] if yvals is not None else np.array([])
            obs = np.isfinite(yw)
            pt["y_actual_mean"] = round(float(yw[obs].mean()), 4) if bool(obs.any()) else None
            # 增量8 品質維度——① Ŷ 水準漂移（預測品質飄，半隱性）：窗均值相對 golden Ŷ 的 z（golden-σ）
            z = (wy_mean - gy_mu) / (gy_sd + 1e-9) if (gy_mu is not None and gy_sd is not None) else None
            pt["yhat_drift_z"] = round(z, 3) if z is not None else None
            # ② X→Y 殘差超界（真隱性：X 正常、實際 Y 偏）——需窗內有足夠 Y 觀測才可判，否則誠實標 None/False
            mh, yflag = None, False
            if int(obs.sum()) >= cfg.y_map_min_obs:
                mh = yh.map_health(Xw, yw)
                yflag = bool(yh.y_flagged(Xw, yw))
            pt["y_map_health"] = round(mh, 4) if mh is not None else None
            pt["y_flagged"] = yflag
            pt["y_observed"] = bool(obs.any())
            level_drift = z is not None and abs(z) >= cfg.y_trend_z_max
            pt["y_quality_raw"] = bool(level_drift or yflag)  # 任一品質訊號（Ŷ 漂移 或 殘差超界）
        points.append(pt)
    if yh is not None:  # Y 品質持續告警：連續 k 窗 raw（濾單點，類比 X 側 persistence）
        k, run = cfg.drift_persistence_k, 0
        for pt in points:
            run = run + 1 if pt.get("y_quality_raw") else 0
            pt["y_quality_persisted"] = bool(run >= k)
    return {
        "product": bundle.product,
        "window": int(window),
        "points": points,
        "n_alarms": int(sum(p["persisted_alarm"] for p in points)),
        "has_y_mapping": yh is not None,  # 前端據此決定是否畫 Ŷ vs Y 子圖
        "n_quality_alarms": int(sum(p.get("y_quality_persisted", False) for p in points)),  # 增量8 品質飄移持續告警窗
        "golden_yhat_mean": round(gy_mu, 4) if gy_mu is not None else None,
        "golden_yhat_std": round(gy_sd, 4) if gy_sd is not None else None,
        "subsampled": subsampled,         # 高維/長資料集降採樣顯示（前端標示）
        "n_windows": len(points),
    }


def tag_map_for(models_dir: str, product: str) -> dict:
    """讀 ``{models_dir}/tags/{product}.json``（x_column → 現場 DCS 位號）；無則回 {}（識別映射）。

    現場位號為客戶 DCS/historian 專有 → 以可放置的 config 檔承載（NOT VERIFIED stub），讓 RBC 肇因能顯示
    工程師認得的位號（如 xmeas07 → TIC-205）而非資料集內部欄名（紅隊現場工程師「最後一哩」）。
    """
    p = os.path.join(models_dir, "tags", f"{product}.json")
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def window_detail(
    bundle_path: str,
    name: str,
    start: int,
    end: int,
    *,
    compute_fwer: bool = True,
    tag_map: dict | None = None,
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
    tm = tag_map or {}  # 位號對照：RBC 肇因欄名 → 現場 DCS 位號（無 config 則維持欄名）
    detail["rbc_ranking"] = [[tm.get(v, v), s] for v, s in detail["rbc_ranking"]]
    detail["tag_mapped"] = bool(tm)
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
        # 誠實揭露品質維度涵蓋（紅隊 blocker：勿隱含「全品質涵蓋」）：純量 Y 只有 map(X→Y 關係)分量，
        # 無 dist(多維品質分布)分量——y_mspc_ 為 None 即代表此資料集為純量品質。
        dist_avail = yh.y_mspc_ is not None
        coverage = ("含 X→Y 關係(map) + 多維品質分布(dist)" if dist_avail
                    else "純量品質：僅監控 X→Y 關係(map)；無多維品質分布(dist)維度")
        ss_block: dict = {"available": True, "n_y_obs": n_obs, "cp_available": bool(yh.ss_.cp_available),
                          "y_flagged": False, "dist_available": dist_avail, "coverage": coverage}
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
                    "y_flagged": bool(yh.y_flagged(X, yw)),  # 增量8：品質旗標（殘差超界＝X→Y 斷，隱性品質飄移）
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


def acceptance_summary(name: str, *, holdout_frac: float = 0.5, window: int = 60,
                       features: list[str] | None = None, golden=None, **build_kwargs) -> dict:
    """建模後驗收摘要（製程工程師簽核依據）：時間連續 hold-out 的 golden FPR / drift recall / SPC-blind / 裁決。

    接 ``acceptance.acceptance_from_dataset``（取代前端寫死的「可上線」文案）；資料/驗收失敗回 available=False。
    compute_fwer=False 以維建模流程互動速度（Rule 6）。features：與建模對齊的監控特徵子集（None→全用）。
    golden：與建模對齊的 golden 規格（None→資料集真值段）——驗收即驗實際上線的模型（季節性資料選平穩段過關）。
    """
    try:
        r = acceptance_from_dataset(name, holdout_frac=holdout_frac, window=window, compute_fwer=False,
                                    features=features, golden=golden, **build_kwargs)
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


def ingest_incidents(bundle_path: str, name: str, store_path: str, *, window: int = 60, **build_kwargs) -> dict:
    """增量5：把評分發現的 persisted-alarm 開成**事件**（同裝置防重複）。回傳 {opened, incident_id}。

    取最嚴重（health 最低）的持續告警窗開案；top_cause 取該窗 RBC 首位（一次 window_detail）。供事件閉環。
    """
    tl = score_timeline(bundle_path, name, window=window, **build_kwargs)
    store = IncidentStore(store_path)
    alarmed = [p for p in tl["points"] if p["persisted_alarm"]]
    if not alarmed:
        return {"opened": False, "incident_id": None}
    worst = min(alarmed, key=lambda p: p["health_index"])
    try:
        d = window_detail(bundle_path, name, worst["start"], worst["end"], compute_fwer=False, **build_kwargs)
        top = d["rbc_ranking"][0][0] if d.get("rbc_ranking") else "(見窗下鑽)"
    except Exception:
        top = "(見窗下鑽)"
    inc = store.open_incident(product=tl["product"], window=[worst["start"], worst["end"]],
                              health=worst["health_index"], confidence=worst["confidence"],
                              top_cause=top, detected_at=worst.get("ts"))
    return {"opened": True, "incident_id": inc.id}


def event_overview(store_path: str, *, avg_loss_per_unplanned_stop: float = 1_000_000.0) -> dict:
    """事件頁資料（現場工程師閉環 + 處長 KPI/ROI）：事件清單 + stats(含 MTTR) + ROI 估算。"""
    store = IncidentStore(store_path)
    incs = store.list()
    return {"incidents": incs, "stats": store.stats(),
            "roi": estimate_roi(incs, avg_loss_per_unplanned_stop=avg_loss_per_unplanned_stop)}


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


def plant_hierarchy(models_dir: str = "models", *, incidents_path: str | None = None, window: int = 60) -> dict:
    """廠區階層視圖（處長 P2）：依 ``{models_dir}/plant.json``（product→區域）把裝置分組成區域。

    無 config → 全部歸「未分區」（與扁平等價）。真實 廠→區→裝置 拓樸為客戶專有，以 config 承載（stub）。
    """
    pv = plant_overview(models_dir, incidents_path=incidents_path, window=window)
    try:
        with open(os.path.join(models_dir, "plant.json"), encoding="utf-8") as f:
            amap = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        amap = {}
    groups: dict = {}
    for a in pv["assets"]:
        groups.setdefault(amap.get(a["product"], "未分區"), []).append(a)
    areas = [{"area": k, "assets": v, "n_alarm": sum(1 for x in v if x["status"] == "alarm")}
             for k, v in groups.items()]
    return {**pv, "areas": areas, "configured": bool(amap)}


def incidents_to_csv(incidents: list[dict]) -> str:
    """事件清單 → CSV 字串（工程師/處長匯出、稽核留痕，P1）。"""
    import csv
    import io

    cols = ["id", "product", "kind", "detected_at", "opened_at", "severity", "status", "health", "confidence",
            "top_cause", "ack_by", "ack_at", "closed_at", "mttr_sec", "close_reason", "close_note"]
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


# ====== 增量7：模型 registry orchestration（製程/模型解耦；UI 殼只呼叫本層）======
# 設計與不變式見 docs/model_registry_design.md（已 3 紅隊複審）。assets.AssetStore 管狀態，本層接資料集評分。

def create_process(registry_path: str, *, display_name: str, dataset: str, by: str = "未具名",
                   at: str, area: str | None = None) -> dict:
    """建立製程（placeholder，先無模型）。dataset 必須已註冊。回傳 process record。"""
    return AssetStore(registry_path).create_process(display_name=display_name, dataset=dataset, by=by, at=at, area=area)


def build_model_for_process(registry_path: str, models_dir: str, process_id: str, *, golden, window: int,
                            by: str = "未具名", at: str, holdout_frac: float = 0.5,
                            features: list[str] | None = None) -> dict:
    """為製程建立/更換模型（重建基準）：先驗收 gate（FAIL 不存檔不登錄）→ 存版本化 bundle → 登錄 registry。

    更換模型＝同製程再呼一次（version 單調+1、舊版自動成歷史、current 指新版）。acceptance 快照存入 model record
    供歷史頁判 rollback（紅隊 RT-3）。golden 可為 (s,e) / "auto" / {"segments":[...]}（接出 mask/auto 選法）。
    features：監控特徵子集（None→全用）；驗收與建模同步用此子集。回傳 {saved, acceptance, model?, build?}。
    """
    store = AssetStore(registry_path)
    p = store.get_process(process_id)
    dataset = p["dataset"]
    garg = golden_arg_from_spec(dataset, golden)  # spec → build 引數（連續/勾選 mask/自動）
    version = int(p["next_version"])  # peek：build_and_save_model 不動 registry，record_build 會給同號（下方 assert）
    # 驗收對齊使用者選的 golden + 子集（非固定真值段）→ 季節性/時序資料圈平穩段即可過 FPR gate
    acc = acceptance_summary(dataset, holdout_frac=holdout_frac, window=int(window), features=features, golden=garg)
    # 治理 gate（Rule 7：兩準則風險不同，不平均成一個硬擋）：
    #   FPR 過高＝誤報→操作員警報疲勞→危險，**硬擋不存檔**；
    #   recall 偏低＝漏抓部分 drift，多半是「監控子集」時丟掉帶訊號的參數——是使用者**知情的靈敏度取捨**，
    #   **警告不擋**（fpr 合格仍允許上線，前端顯著標示偵測力下降）。
    if acc.get("available") and not acc.get("fpr_ok", True):
        return {"saved": False, "acceptance": acc, "process_id": process_id, "block_reason": "fpr"}
    stem = f"{process_id}__v{version}"
    m = build_and_save_model(dataset, golden=garg, models_dir=models_dir, created_at=at, product=stem, features=features)
    rec = store.record_build(process_id, path=f"{stem}.joblib", dataset=dataset, golden_range=m["golden_range"],
                             fingerprint_hi=m["fingerprint_hi"], has_y_health=m["has_y_health"],
                             acceptance=acc if acc.get("available") else None, by=by, at=at)
    if rec["version"] != version:  # fail-loud：版本 peek 與登錄不一致（registry 被並發改動）
        raise RuntimeError(f"版本不一致：peek v{version} vs 登錄 v{rec['version']}")
    return {"saved": True, "acceptance": acc, "model": rec, "build": m, "process_id": process_id}


def delete_model(registry_path: str, model_id: str, *, reason: str = "", by: str = "未具名", at: str) -> dict:
    """軟刪除單一模型版本（只翻旗標不刪檔；若為現役→current 退回最高版未刪）。"""
    return AssetStore(registry_path).soft_delete_model(model_id, reason=reason, by=by, at=at)


def delete_process(registry_path: str, process_id: str, *, reason: str = "", by: str = "未具名", at: str,
                   incidents_path: str | None = None) -> dict:
    """軟刪除製程（完全隱藏，只在歷史可見）；給 incidents_path 則強制關閉其孤兒 active 事件。"""
    store = IncidentStore(incidents_path) if incidents_path else None
    return AssetStore(registry_path).soft_delete_process(process_id, reason=reason, by=by, at=at, incident_store=store)


def restore_process(registry_path: str, process_id: str, *, by: str = "未具名", at: str) -> dict:
    """還原被軟刪除的製程（入口在歷史/稽核頁）。"""
    return AssetStore(registry_path).restore_process(process_id, by=by, at=at)


def model_history(registry_path: str, process_id: str, *, incidents_path: str | None = None) -> dict:
    """模型歷史監控紀錄：版本清單(含 acceptance 快照) + 稽核 log + 該製程服役期 incidents（紅隊 RT-3）。"""
    h = AssetStore(registry_path).history(process_id)
    incs = IncidentStore(incidents_path).list(product=process_id) if incidents_path else []
    return {**h, "incidents": incs}


def _score_current(models_dir: str, model_rec: dict, window: int) -> tuple:
    """評現役模型最後一窗的健康燈。回傳 (health, alarm, status)；資料源/檔不可得→(None,None,'data_unavailable')。"""
    try:
        b = load(os.path.join(models_dir, model_rec["path"]))
        ds, _gt = registry.build(model_rec["dataset"])
        X = ds.frame[list(b.x_columns)].to_numpy(dtype=float)
        Xw = X[-window:] if len(X) >= window else X
        alarm = bool(b.health.alarm(Xw, compute_fwer=False))
        return round(float(b.health.health_index(Xw)), 3), alarm, ("alarm" if alarm else "healthy")
    except Exception:  # 檔損/指紋漂移/資料源不可得 → 誠實標，不杜撰健康度
        return None, None, "data_unavailable"


def assets_overview(registry_path: str, models_dir: str, *, incidents_path: str | None = None, window: int = 60) -> dict:
    """總覽資料源（取代 plant_hierarchy 接 registry）：列非刪製程（含 placeholder「待建模」），健康燈**三態**
    （綠健康/紅告警/灰待建模或不可得），依 area 分組。placeholder 不進綠紅分母（紅隊：避免污染全廠健康語意）。

    回傳 {plant_status, n_assets, n_monitored, n_alarm, n_placeholder, configured, areas, assets}。
    無 registry 檔 → 空 registry（n_assets=0），前端顯「尚無製程」。
    """
    store = AssetStore(registry_path)
    inc_store = IncidentStore(incidents_path) if incidents_path else None
    assets = []
    for p in store.list_processes():  # 預設不含已軟刪除（完全隱藏）
        cur = store.current_model(p["id"])
        a = {"process_id": p["id"], "display_name": p["display_name"], "dataset": p["dataset"],
             "area": p["area"], "current_model_id": p["current_model_id"], "version": None,
             "health": None, "alarm": None, "status": "placeholder", "bundle_path": None,
             "active_incidents": 0}
        if cur is not None:
            a["version"] = cur["version"]
            a["bundle_path"] = os.path.join(models_dir, cur["path"])
            a["health"], a["alarm"], a["status"] = _score_current(models_dir, cur, window)
        if inc_store is not None:
            a["active_incidents"] = sum(1 for i in inc_store.list(product=p["id"]) if i["status"] in ("open", "ack"))
        assets.append(a)
    n_alarm = sum(1 for a in assets if a["status"] == "alarm")
    n_monitored = sum(1 for a in assets if a["status"] in ("healthy", "alarm"))
    n_placeholder = sum(1 for a in assets if a["status"] in ("placeholder", "data_unavailable"))
    plant_status = "alarm" if n_alarm else ("healthy" if n_monitored else "empty")  # 只看已監控者，灰不進分母
    groups: dict = {}
    for a in assets:
        groups.setdefault(a["area"] or "未分區", []).append(a)
    areas = [{"area": k, "assets": v, "n_alarm": sum(1 for x in v if x["status"] == "alarm")}
             for k, v in groups.items()]
    return {"plant_status": plant_status, "n_assets": len(assets), "n_monitored": n_monitored,
            "n_alarm": n_alarm, "n_placeholder": n_placeholder, "configured": any(a["area"] for a in assets),
            "areas": areas, "assets": assets}
