"""batch-AVM 9 步建模精靈（INC-5，呈現殼）。

9 步：①挑製程+時間區間 → ②顯示區間內有資料的機台 → ③挑製程參數 → ④切批+修剪 Temporal（疊圖）
+勾選批次 → ⑤轉換 Indicator（[param×stat]，惰性計算+進度）→ ⑥DQI 資料品質/完整度 → ⑦建映射模型
→ ⑧選測試時間區間 → ⑨映射與監控結果（GSI/可信度 CP-band/隱性飄移，點擊下鑽粗→細）。

架構：本檔為**呈現殼**——計算全在已單元測試的 batch_avm/*（selection/quality/mapping）與
preprocess/batch_features；callback 為薄殼、核心為本檔可直呼的純函數（tests/test_batch_wizard.py）。
「轉換計算」採 **thread + dcc.Interval 輪詢**（使用者定案的輕量進度方案）；模型/評分等不可 JSON
物件放模組級快取、dcc.Store 只放 token。與現行 5 步精靈並存（Rule 3；驗證後汰換）。
呈現一律稱「可信度（CP-band）」，不得稱 RI。
"""

from __future__ import annotations

import itertools
import threading

import numpy as np
import plotly.graph_objects as go
from dash import Input, Output, State, ctx, dcc, html, no_update

from health_index.adapters import registry
from health_index.batch_avm.attribution import domain_exit_attribution, y_event_attribution
from health_index.batch_avm.mapping import fit_batch_model, score_batches
from health_index.batch_avm.quality import batch_quality_view
from health_index.batch_avm.residual import fit_residual_monitor, score_residuals
from health_index.batch_avm.selection import cut_batches, machines_in_interval
from health_index.config import DEFAULT
from health_index.preprocess.batch_features import batch_indicator_matrix, batch_temporal_overlay
from health_index.y_history import YHistoryMonitor

_ACCENT = "#4338ca"
_OK, _BAD = "#16a34a", "#dc2626"
_STATS_ALL = ("mean", "std", "min", "max", "range", "median", "count", "cv")
_META = ("batch", "start", "end", "len")

# 模組級快取（呈現層；不可 JSON 物件不入 dcc.Store，只存 token）
_token = itertools.count(1)
_DS: dict = {}      # dataset name → (ds, gt)
_CUT: dict = {}     # token → cut_batches 結果
_JOBS: dict = {}    # token → {progress, done, error, cells, xs_cols, xs}
_MODELS: dict = {}  # token → (BatchAvmModel, feat_cols)
_SCORES: dict = {}  # token → score_batches 結果 + meta


# ---------- 可測純函數（callback 薄殼呼叫） ----------

def load_dataset(name: str):
    """registry 建構 +（呈現層）快取；同名同參重複載入不重算。"""
    if name not in _DS:
        _DS[name] = registry.build(name)
    return _DS[name]


def do_cut(name: str, machine: str, start, end, batch_minutes: int) -> int:
    """切批並快取，回 token。"""
    ds, _ = load_dataset(name)
    res = cut_batches(ds.frame, ds.x_columns, machine=machine,
                      start=start or None, end=end or None, batch_minutes=int(batch_minutes))
    res["x_columns"] = list(ds.x_columns)
    tok = next(_token)
    _CUT[tok] = res
    return tok


def overlay_figure(cut_tok: int, param: str, trim_pct: float) -> go.Figure:
    """④ 疊圖：全批 trace + 中位/分位帶（display-only resample）+ trim 區。"""
    c = _CUT[cut_tok]
    j = c["x_columns"].index(param)
    ov = batch_temporal_overlay(c["X"], c["spans"], param=j, trim_frac=trim_pct / 100.0, resample_n=100)
    fig = go.Figure()
    for tr in ov.traces:
        fig.add_scatter(x=tr["t"], y=tr["values"], mode="lines", line={"width": 1, "color": "rgba(67,56,202,0.25)"},
                        name=f"P{tr['batch'] + 1}", showlegend=False, hovertemplate=f"P{tr['batch'] + 1}<extra></extra>")
    if ov.median is not None:
        fig.add_scatter(x=ov.grid, y=ov.band_hi, mode="lines", line={"width": 0}, showlegend=False, hoverinfo="skip")
        fig.add_scatter(x=ov.grid, y=ov.band_lo, mode="lines", line={"width": 0}, fill="tonexty",
                        fillcolor="rgba(21,101,192,0.15)", name="10–90% 帶", showlegend=True)
        fig.add_scatter(x=ov.grid, y=ov.median, mode="lines", line={"width": 2, "color": "#1565c0"}, name="中位軌跡")
    fig.update_layout(height=300, margin={"l": 40, "r": 10, "t": 28, "b": 30},
                      title={"text": f"{param}：{len(c['spans'])} 批疊圖（批內進度 0–100%，已修剪頭尾 {trim_pct:.0f}%）",
                             "font": {"size": 13}}, xaxis={"title": "批內進度"}, yaxis={"title": param})
    return fig


def convert_cells(cut_tok: int, params: list, stats: list, trim_pct: float, progress_cb=None) -> dict:
    """⑤ 指標轉換核心：X*=[param×stat]（含進度回呼）。回 {cells, xs_cols, xs}。"""
    c = _CUT[cut_tok]
    cols = [p for p in c["x_columns"] if p in set(params)]
    Xsel = c["X"][:, [c["x_columns"].index(p) for p in cols]]
    xs = batch_indicator_matrix(Xsel, c["spans"], cols, stats=tuple(stats), trim_frac=trim_pct / 100.0)
    cells = []
    for i, p in enumerate(cols):
        for st in stats:
            col = f"{p}__{st}"
            cells.append({"param": p, "stat": st, "values": [None if not np.isfinite(v) else float(v)
                                                             for v in xs[col].to_numpy(dtype=float)]})
        if progress_cb:
            progress_cb(int((i + 1) / max(1, len(cols)) * 100))
    feat_cols = [cc for cc in xs.columns if cc not in _META]
    return {"cells": cells, "xs_cols": feat_cols, "xs": xs}


def start_convert_job(cut_tok: int, params: list, stats: list, trim_pct: float) -> int:
    """⑤ 惰性計算：背景 thread 算、_JOBS 回報進度（dcc.Interval 輪詢）。"""
    tok = next(_token)
    _JOBS[tok] = {"progress": 0, "done": False, "error": None}

    def _run():
        try:
            out = convert_cells(cut_tok, params, stats, trim_pct,
                                progress_cb=lambda p: _JOBS[tok].__setitem__("progress", p))
            _JOBS[tok].update(out)
            _JOBS[tok]["done"] = True
        except Exception as e:  # 呈現層：錯誤進面板、不炸 server
            _JOBS[tok]["error"] = f"{type(e).__name__}: {e}"
            _JOBS[tok]["done"] = True

    threading.Thread(target=_run, daemon=True).start()
    return tok


def quality_view_for(cut_tok: int, golden_batches: list, stats: list, trim_pct: float) -> dict:
    """⑥ DQI：golden=④ 勾選批。"""
    c = _CUT[cut_tok]
    return batch_quality_view(c["X"], c["y"], c["spans"], c["x_columns"],
                              golden_batches=golden_batches if golden_batches else None,
                              stats=tuple(stats), trim_frac=trim_pct / 100.0)


def fit_from_job(job_tok: int, cut_tok: int, golden_batches: list) -> int:
    """⑦ 建模：X*（⑤ 轉換結果）取 golden 批列 × 有限 y → fit，回 model token。

    Raises:
        ValueError: 轉換未完成、或 golden 批中有限 y 不足 2。
    """
    j = _JOBS.get(job_tok)
    if not j or not j.get("done") or j.get("error"):
        raise ValueError("請先完成 ⑤ 轉換計算")
    c = _CUT[cut_tok]
    xs = j["xs"]
    feat_cols = j["xs_cols"]
    rows = sorted(set(int(b) for b in golden_batches))
    Xg = xs[feat_cols].to_numpy(dtype=float)[rows]
    yg = c["y"][rows]
    ok = np.isfinite(yg)
    if int(ok.sum()) < 2:
        raise ValueError(f"golden 批有限 y 僅 {int(ok.sum())} 筆（<2），無法建映射模型")
    m = fit_batch_model(Xg[ok], yg[ok], columns=feat_cols)
    tok = next(_token)
    _MODELS[tok] = (m, feat_cols, Xg[ok], yg[ok])  # 存 golden (X*, y) 供殘差/G1 監控
    return tok


def attribute_batch(model_tok: int, xstar_row) -> dict:
    """⑨ 下鑽歸因：G2（哪個參數推動 Ŷ）+ G3（哪個參數推出適用域）。正確性見 test_attribution。"""
    m = _MODELS[model_tok][0]
    return {"g2": y_event_attribution(m, xstar_row), "g3": domain_exit_attribution(m, xstar_row)}


def monitor_y_channel(model, gx_golden, gy_golden, test_xstar, test_y) -> dict:
    """⑨ Y 側監控：殘差漂移（G2 偵測線）+ 純 Y-vs-歷史（G1）。不足則誠實標 unavailable。"""
    out: dict = {"residual": None, "g1": None}
    ty = np.asarray(test_y, dtype=float)
    try:
        rm = fit_residual_monitor(model, gx_golden, gy_golden)
        rres = score_residuals(rm, model, test_xstar, ty)
        out["residual"] = {**rres["summary"], "null_kind": rres["null_kind"]}
    except ValueError as e:
        out["residual"] = {"unavailable": str(e)}
    gy = np.asarray(gy_golden, dtype=float)
    gy = gy[np.isfinite(gy)]
    if gy.size >= DEFAULT.g1_min_golden:
        out["g1"] = YHistoryMonitor().fit(gy).score(ty)["summary"]
    else:
        out["g1"] = {"unavailable": f"歷史 Y 僅 {gy.size} 筆（< {DEFAULT.g1_min_golden}）"}
    return out


def score_test_interval(name: str, machine: str, tstart, tend, batch_minutes: int,
                        model_tok: int, params: list, stats: list, trim_pct: float) -> int:
    """⑧→⑨ 測試區間切批 → X* → score_batches，回 score token。"""
    m, feat_cols, gx, gy = _MODELS[model_tok]
    cut_tok = do_cut(name, machine, tstart, tend, batch_minutes)
    out = convert_cells(cut_tok, params, stats, trim_pct)
    if list(out["xs_cols"]) != list(feat_cols):
        raise ValueError("測試區間的 X* 欄位與建模時不一致（參數/統計選擇需相同）")
    test_xstar = out["xs"][feat_cols].to_numpy(dtype=float)
    res = score_batches(m, test_xstar)
    c = _CUT[cut_tok]
    res["batch_start_times"] = c["batch_start_times"]
    res["y"] = [None if not np.isfinite(v) else float(v) for v in c["y"]]
    res["_model_tok"] = model_tok           # 供下鑽歸因（呈現層快取，不入 dcc.Store）
    res["_xstar"] = test_xstar
    res["y_monitor"] = monitor_y_channel(m, gx, gy, test_xstar, c["y"])  # 殘差(G2)+G1
    tok = next(_token)
    _SCORES[tok] = res
    return tok


def guard_next(step: int, flags: dict) -> tuple[int, str]:
    """步進守門：缺前置就留在原步並回提示（UX 稽核：精靈要有 step guard）。"""
    need = {1: ("loaded", "請先按「載入資料」"), 2: ("machine", "請先選一台機台"),
            3: ("params", "請至少勾選一個製程參數"), 4: ("cut", "請先按「切批」"),
            5: ("converted", "請先完成「轉換計算」"), 7: ("model", "請先按「建立模型」"),
            8: ("scored", "請先完成 ⑧ 的「評分」")}
    if step in need:
        key, msg = need[step]
        if not flags.get(key):
            return step, msg
    return min(step + 1, 9), ""


def score_figure(res: dict) -> go.Figure:
    """⑨ 每批監控圖：T²/limit 與 SPE/limit 比值（>1=超限）+ 異常標記；點擊下鑽。"""
    s = res["summary"]
    n = len(res["batches"])
    xs = list(range(1, n + 1))
    t2r = [b["t2"] / s["t2_lim"] for b in res["batches"]]
    sper = [b["spe"] / s["spe_lim"] for b in res["batches"]]
    colors = [_BAD if b["anomaly"] else _OK for b in res["batches"]]
    fig = go.Figure()
    fig.add_scatter(x=xs, y=t2r, mode="lines+markers", name="T²/限",
                    marker={"color": colors, "size": 9}, line={"color": "#94a3b8", "width": 1})
    fig.add_scatter(x=xs, y=sper, mode="lines+markers", name="SPE/限",
                    marker={"color": colors, "size": 9, "symbol": "diamond"}, line={"color": "#cbd5e1", "width": 1})
    fig.add_hline(y=1.0, line={"dash": "dash", "color": _BAD}, annotation_text="控制限")
    fig.update_layout(height=320, margin={"l": 40, "r": 10, "t": 24, "b": 30},
                      xaxis={"title": "批次（時間序）"}, yaxis={"title": "統計量 / 控制限"},
                      legend={"orientation": "h"})
    return fig


# ---------- 版面 ----------

def _card(children):
    return html.Div(children, style={"border": "1px solid #e3e8ef", "borderRadius": "12px",
                                     "padding": "14px 16px", "background": "#fff", "marginBottom": "12px"})


def _bbtn(label, bid, primary=False, **kw):
    st = {"padding": "8px 16px", "borderRadius": "9px", "border": f"1px solid {_ACCENT}", "cursor": "pointer",
          "background": _ACCENT if primary else "#fff", "color": "#fff" if primary else _ACCENT, "fontWeight": 500}
    return html.Button(label, id=bid, n_clicks=0, style={**st, **kw.pop("style", {})}, **kw)


_STEP_TITLES = ("① 製程與時間", "② 機台", "③ 製程參數", "④ 切批與修剪", "⑤ 指標轉換",
                "⑥ 資料品質", "⑦ 建立模型", "⑧ 測試區間", "⑨ 監控結果")


def layout() -> list:
    """batch-AVM 精靈畫面（掛在 demo_app 的 scr-batchwiz）。"""
    panels = [
        html.Div(id="bwp1", children=_card([
            html.H4(_STEP_TITLES[0], style={"margin": "0 0 8px"}),
            html.Div("選資料來源與要分析的時間區間（留空＝全部）", style={"fontSize": "13px", "color": "#51607a"}),
            html.Div(style={"display": "flex", "gap": "8px", "flexWrap": "wrap", "margin": "8px 0"}, children=[
                dcc.Dropdown(id="bw-dataset", value="tep_fleet", clearable=False, style={"width": "260px"},
                             options=[{"label": "TEP 多機台 fleet（示範）", "value": "tep_fleet"},
                                      {"label": "TEP（單機台）", "value": "tep"},
                                      {"label": "TEP 保時序", "value": "tep_tp"}]),
                dcc.Input(id="bw-start", type="text", placeholder="起（如 2026-03-01，可留空）", style={"width": "220px"}),
                dcc.Input(id="bw-end", type="text", placeholder="迄（不含，可留空）", style={"width": "220px"}),
                _bbtn("載入資料", "bw-load", primary=True),
            ]),
            html.Div(id="bw-msg1", style={"fontSize": "13px"}),
        ])),
        html.Div(id="bwp2", style={"display": "none"}, children=_card([
            html.H4(_STEP_TITLES[1], style={"margin": "0 0 8px"}),
            html.Div("此時間區間內有生產資料的機台（選一台建模；跨機台混 Golden 的護欄見設計 §8）",
                     style={"fontSize": "13px", "color": "#51607a", "marginBottom": "8px"}),
            html.Div(id="bw-machines"), html.Div(id="bw-msg2", style={"fontSize": "13px"}),
        ])),
        html.Div(id="bwp3", style={"display": "none"}, children=_card([
            html.H4(_STEP_TITLES[2], style={"margin": "0 0 8px"}),
            dcc.Checklist(id="bw-params", options=[], value=[], inline=True,
                          style={"fontSize": "13px", "maxHeight": "160px", "overflowY": "auto"}),
        ])),
        html.Div(id="bwp4", style={"display": "none"}, children=_card([
            html.H4(_STEP_TITLES[3], style={"margin": "0 0 8px"}),
            html.Div(style={"display": "flex", "gap": "8px", "alignItems": "center", "flexWrap": "wrap"}, children=[
                html.Span("每批時長（分鐘）", style={"fontSize": "13px"}),
                dcc.Input(id="bw-batchmin", type="number", value=60, min=1, style={"width": "90px"}),
                html.Span("修剪頭尾各 %", style={"fontSize": "13px", "marginLeft": "8px"}),
                dcc.Slider(id="bw-trim", min=0, max=20, step=1, value=5,
                           marks={0: "0", 5: "5", 10: "10", 20: "20"}),
                _bbtn("切批", "bw-cut", primary=True),
            ]),
            html.Div(id="bw-msg4", style={"fontSize": "13px", "margin": "6px 0"}),
            dcc.Dropdown(id="bw-ovparam", options=[], style={"width": "260px"}),
            dcc.Graph(id="bw-overlay", config={"displayModeBar": False}),
            html.Div("勾選要納入 Golden 的批次（剔除異常批）：", style={"fontSize": "13px", "margin": "6px 0"}),
            dcc.Checklist(id="bw-batches", options=[], value=[], inline=True,
                          style={"fontSize": "12px", "maxHeight": "120px", "overflowY": "auto"}),
        ])),
        html.Div(id="bwp5", style={"display": "none"}, children=_card([
            html.H4(_STEP_TITLES[4], style={"margin": "0 0 8px"}),
            html.Div("勾選統計指標後按「轉換計算」（惰性計算：按了才算，避免一次算滿 80 張）",
                     style={"fontSize": "13px", "color": "#51607a"}),
            dcc.Checklist(id="bw-stats", value=["mean", "std"], inline=True, style={"fontSize": "13px"},
                          options=[{"label": f" {s}", "value": s} for s in _STATS_ALL]),
            html.Div(style={"display": "flex", "gap": "8px", "alignItems": "center", "margin": "8px 0"}, children=[
                _bbtn("轉換計算", "bw-convert", primary=True),
                html.Div(id="bw-prog", style={"fontSize": "13px"}),
            ]),
            dcc.Interval(id="bw-poll", interval=500, disabled=True),
            dcc.Dropdown(id="bw-chart-stat", options=[], style={"width": "180px"}),
            html.Div(id="bw-runcharts"),
        ])),
        html.Div(id="bwp6", style={"display": "none"}, children=_card([
            html.H4(_STEP_TITLES[5], style={"margin": "0 0 8px"}),
            html.Div("建模前先看資料夠不夠好：X 側 DQI（對 golden 批）＋ Y 側准入閘（未量測≠正常）",
                     style={"fontSize": "13px", "color": "#51607a", "marginBottom": "6px"}),
            _bbtn("計算 DQI / 完整度", "bw-dqi-btn", primary=True),
            html.Div(id="bw-dqi-out", style={"marginTop": "8px"}),
        ])),
        html.Div(id="bwp7", style={"display": "none"}, children=_card([
            html.H4(_STEP_TITLES[6], style={"margin": "0 0 8px"}),
            html.Div("以 ④ 勾選的 golden 批建映射模型（X*→Ŷ；PLS/GPR 自動路由＋CV+ 可信帶）",
                     style={"fontSize": "13px", "color": "#51607a", "marginBottom": "6px"}),
            _bbtn("建立模型", "bw-fit", primary=True),
            html.Div(id="bw-fit-out", style={"marginTop": "8px", "fontSize": "13px"}),
        ])),
        html.Div(id="bwp8", style={"display": "none"}, children=_card([
            html.H4(_STEP_TITLES[7], style={"margin": "0 0 8px"}),
            html.Div(style={"display": "flex", "gap": "8px", "flexWrap": "wrap"}, children=[
                dcc.Input(id="bw-tstart", type="text", placeholder="測試起（可留空）", style={"width": "200px"}),
                dcc.Input(id="bw-tend", type="text", placeholder="測試迄（可留空）", style={"width": "200px"}),
                _bbtn("評分", "bw-score-btn", primary=True),
            ]),
            html.Div(id="bw-msg8", style={"fontSize": "13px", "marginTop": "6px"}),
        ])),
        html.Div(id="bwp9", style={"display": "none"}, children=_card([
            html.H4(_STEP_TITLES[8], style={"margin": "0 0 8px"}),
            html.Div(id="bw-score-summary"),
            dcc.Graph(id="bw-scoregraph", config={"displayModeBar": False}),
            html.Div("點上圖任一批 → 展開該批細節（粗→細）", style={"fontSize": "12px", "color": "#51607a"}),
            html.Div(id="bw-detail", style={"marginTop": "8px"}),
        ])),
    ]
    return [
        dcc.Store(id="bw-step", data=1),
        dcc.Store(id="bw-q1"), dcc.Store(id="bw-machine"), dcc.Store(id="bw-cut-token"),
        dcc.Store(id="bw-job"), dcc.Store(id="bw-model"), dcc.Store(id="bw-score-token"),
        html.Div(style={"display": "flex", "justifyContent": "space-between", "alignItems": "center"}, children=[
            html.H3("batch-AVM 建模精靈", style={"margin": "0"}),
            html.Div(id="bw-stepbar", style={"fontSize": "13px", "color": "#51607a"}),
        ]),
        html.Div(id="bw-navmsg", style={"color": _BAD, "fontSize": "13px", "minHeight": "18px"}),
        *panels,
        html.Div(style={"display": "flex", "gap": "8px"}, children=[
            _bbtn("← 上一步", "bw-prev"), _bbtn("下一步 →", "bw-next", primary=True),
        ]),
    ]


# ---------- callbacks（薄殼） ----------

def register(app) -> None:
    """把精靈 callbacks 掛上 app（demo_app 呼叫）。"""

    @app.callback(Output("bw-q1", "data"), Output("bw-machines", "children"), Output("bw-msg1", "children"),
                  Output("bw-params", "options"), Output("bw-params", "value"), Output("bw-ovparam", "options"),
                  Input("bw-load", "n_clicks"),
                  State("bw-dataset", "value"), State("bw-start", "value"), State("bw-end", "value"),
                  prevent_initial_call=True)
    def _bw_load(_, name, start, end):
        try:
            ds, _gt = load_dataset(name)
            ms = machines_in_interval(ds.frame, start=start or None, end=end or None)
            if not ms:
                return no_update, no_update, "⛔ 此時間區間無資料，請放寬區間", no_update, no_update, no_update
            radio = dcc.RadioItems(
                id="bw-machine-radio", value=ms[0]["machine"],
                options=[{"label": f" {m['machine']}｜{m['n_rows']} 筆｜Y {m['n_y']} 筆｜{m['first'][:10]}~{m['last'][:10]}",
                          "value": m["machine"]} for m in ms],
                style={"fontSize": "13px"})
            popt = [{"label": f" {c}", "value": c} for c in ds.x_columns]
            oopt = [{"label": c, "value": c} for c in ds.x_columns]
            return ({"name": name, "start": start, "end": end}, radio,
                    f"✓ 已載入，共 {len(ms)} 台機台有資料", popt, list(ds.x_columns), oopt)
        except Exception as e:
            return no_update, no_update, f"⛔ {e}", no_update, no_update, no_update

    @app.callback(Output("bw-machine", "data"), Input("bw-machine-radio", "value"), prevent_initial_call=True)
    def _bw_machine(v):
        return v

    @app.callback(Output("bw-cut-token", "data"), Output("bw-msg4", "children"),
                  Output("bw-batches", "options"), Output("bw-batches", "value"), Output("bw-ovparam", "value"),
                  Input("bw-cut", "n_clicks"),
                  State("bw-q1", "data"), State("bw-machine", "data"), State("bw-batchmin", "value"),
                  State("bw-params", "value"),
                  prevent_initial_call=True)
    def _bw_cut(_, q1, machine, bmin, params):
        try:
            tok = do_cut(q1["name"], machine, q1.get("start"), q1.get("end"), bmin)
            c = _CUT[tok]
            opts = [{"label": f" P{i + 1}（{t[:16]}）", "value": i} for i, t in enumerate(c["batch_start_times"])]
            msg = (f"✓ 切出 {len(c['spans'])} 批（每批 {bmin} 分鐘；丟棄不完整尾批 {c['n_dropped_partial']}）；"
                   f"Y 覆蓋 {int(np.isfinite(c['y']).sum())}/{len(c['y'])} 批")
            ovp = (params or c["x_columns"])[0]
            return tok, msg, opts, [o["value"] for o in opts], ovp
        except Exception as e:
            return no_update, f"⛔ {e}", no_update, no_update, no_update

    @app.callback(Output("bw-overlay", "figure"),
                  Input("bw-ovparam", "value"), Input("bw-trim", "value"), Input("bw-cut-token", "data"),
                  prevent_initial_call=True)
    def _bw_overlay(param, trim, tok):
        if not tok or not param:
            return no_update
        return overlay_figure(tok, param, float(trim or 0))

    @app.callback(Output("bw-job", "data"), Output("bw-poll", "disabled"), Output("bw-chart-stat", "options"),
                  Output("bw-chart-stat", "value"),
                  Input("bw-convert", "n_clicks"),
                  State("bw-cut-token", "data"), State("bw-params", "value"), State("bw-stats", "value"),
                  State("bw-trim", "value"),
                  prevent_initial_call=True)
    def _bw_convert(_, tok, params, stats, trim):
        if not tok or not params or not stats:
            return no_update, no_update, no_update, no_update
        job = start_convert_job(tok, params, stats, float(trim or 0))
        return job, False, [{"label": s, "value": s} for s in stats], stats[0]

    @app.callback(Output("bw-prog", "children"), Output("bw-poll", "disabled", allow_duplicate=True),
                  Output("bw-runcharts", "children"),
                  Input("bw-poll", "n_intervals"), Input("bw-chart-stat", "value"),
                  State("bw-job", "data"),
                  prevent_initial_call=True)
    def _bw_poll(_n, chart_stat, job):
        j = _JOBS.get(job or -1)
        if not j:
            return no_update, no_update, no_update
        if j.get("error"):
            return f"⛔ {j['error']}", True, no_update
        if not j["done"]:
            return f"計算中… {j['progress']}%", False, no_update
        cells = [c for c in j["cells"] if c["stat"] == (chart_stat or "mean")]
        shown = cells[:12]
        charts = []
        for c in shown:
            xs_axis = list(range(1, len(c["values"]) + 1))
            f = go.Figure(go.Scatter(x=xs_axis, y=c["values"], mode="lines+markers", marker={"size": 5}))
            f.update_layout(height=120, margin={"l": 34, "r": 6, "t": 22, "b": 18},
                            title={"text": f"{c['param']}__{c['stat']}", "font": {"size": 11}},
                            xaxis={"visible": False}, yaxis={"tickfont": {"size": 9}})
            charts.append(dcc.Graph(figure=f, config={"displayModeBar": False}))
        note = (f"共 {len(j['cells'])} 張（param×stat）已計算；此頁顯示 {chart_stat} 前 {len(shown)} 張，"
                f"其餘以上方下拉切換") if len(j["cells"]) > len(shown) else f"共 {len(j['cells'])} 張已計算"
        grid = html.Div([html.Div(f"✓ 轉換完成。{note}", style={"fontSize": "12px", "color": "#51607a"}),
                         html.Div(charts, className="pg-grid",
                                  style={"display": "grid", "gridTemplateColumns": "repeat(3,1fr)", "gap": "6px"})])
        return "✓ 100%", True, grid

    @app.callback(Output("bw-dqi-out", "children"),
                  Input("bw-dqi-btn", "n_clicks"),
                  State("bw-cut-token", "data"), State("bw-batches", "value"),
                  State("bw-stats", "value"), State("bw-trim", "value"),
                  prevent_initial_call=True)
    def _bw_dqi(_, tok, golden, stats, trim):
        if not tok:
            return "⛔ 請先在 ④ 切批"
        v = quality_view_for(tok, golden or [], stats or ["mean", "std"], float(trim or 0))
        s = v["summary"]
        badges = html.Div(style={"display": "flex", "gap": "12px", "flexWrap": "wrap", "fontSize": "13px"}, children=[
            html.Span(f"批數 {s['n_batches']}"),
            html.Span(f"Y 覆蓋 {s['n_y_present']}/{s['n_batches']}（{s['y_coverage']:.0%}）"),
            html.Span("✓ Y 足以建模" if s["y_enough_for_mapping"] else "⚠ Y 少於 CV+ 門檻（可信帶可能不可用）",
                      style={"color": _OK if s["y_enough_for_mapping"] else "#b45309"}),
            html.Span("DQI ✓" if s["dqi_available"] else "DQI —（golden <4 批不評）"),
        ])
        warn = html.Div([html.Div(f"⚠ {w}", style={"color": "#b45309", "fontSize": "12px"}) for w in s["warnings"]])
        head = ["批", "n", "批長異常", "DQI 超限", "Y", "Y 界外", "Y 卡值"]
        rows = [html.Tr([html.Th(h, style={"textAlign": "left", "padding": "2px 8px"}) for h in head])]
        for b in v["per_batch"]:
            mark = lambda f: "—" if f is None else ("⚠" if f else "✓")
            rows.append(html.Tr([
                html.Td(f"P{b['batch'] + 1}", style={"padding": "2px 8px"}), html.Td(b["n"]),
                html.Td(mark(b["n_out_of_family"])), html.Td(mark(b["dqi_x_over"])),
                html.Td("✓" if b["y_present"] else "未量測"),
                html.Td(mark(b["y_out_of_bounds"])), html.Td(mark(b["y_stuck"])),
            ], style={"fontSize": "12px"}))
        return html.Div([badges, warn, html.Table(rows, style={"marginTop": "6px", "borderCollapse": "collapse"})])

    @app.callback(Output("bw-model", "data"), Output("bw-fit-out", "children"),
                  Input("bw-fit", "n_clicks"),
                  State("bw-job", "data"), State("bw-cut-token", "data"), State("bw-batches", "value"),
                  prevent_initial_call=True)
    def _bw_fit(_, job, tok, golden):
        try:
            mtok = fit_from_job(job, tok, golden or [])
            m, feat_cols, _gx, _gy = _MODELS[mtok]
            info = [html.Div(f"✓ 模型建立完成：{('PLS（高維共線）' if m.mapping_kind == 'pls' else 'GPR（小維度非線性）')}"
                             f"，特徵 {len(feat_cols)} 欄、golden {m.n_golden_} 批", style={"color": _OK}),
                    html.Div(("✓ 可信帶：CV+（誠實最壞覆蓋 ≥80%）" if m.cv_.available
                              else "⚠ golden 批的有效 Y 不足 CV+ 門檻——Ŷ 無可信帶，僅點預測"),
                             style={"color": "#0f172a" if m.cv_.available else "#b45309"})]
            if m.reduced_:
                info.append(html.Div(f"⚠ X* 高維小 n：已預投影至 {m.r_} 維（批次下鑽歸因暫不可用）"
                                     + ("；且變異匱乏（degraded），建議增加 golden 批" if m.degraded_ else ""),
                            style={"color": "#b45309"}))
            return mtok, html.Div(info)
        except Exception as e:
            return no_update, html.Div(f"⛔ {e}", style={"color": _BAD})

    @app.callback(Output("bw-score-token", "data"), Output("bw-msg8", "children"),
                  Output("bw-score-summary", "children"), Output("bw-scoregraph", "figure"),
                  Input("bw-score-btn", "n_clicks"),
                  State("bw-q1", "data"), State("bw-machine", "data"), State("bw-tstart", "value"),
                  State("bw-tend", "value"), State("bw-batchmin", "value"), State("bw-model", "data"),
                  State("bw-params", "value"), State("bw-stats", "value"), State("bw-trim", "value"),
                  prevent_initial_call=True)
    def _bw_score(_, q1, machine, ts, te, bmin, mtok, params, stats, trim):
        try:
            stok = score_test_interval(q1["name"], machine, ts or None, te or None, bmin, mtok,
                                       params, stats, float(trim or 0))
            res = _SCORES[stok]
            n_anom = sum(b["anomaly"] for b in res["batches"])
            s = res["summary"]
            gsi_mean = float(np.mean([b["gsi"] for b in res["batches"]]))
            ym = res.get("y_monitor") or {}
            rd = ym.get("residual") or {}
            g1 = ym.get("g1") or {}
            yflag = lambda d: "—" if "unavailable" in d else ("⚠" if d.get("alarm") else "✓")
            cards = html.Div(style={"display": "flex", "gap": "16px", "flexWrap": "wrap", "fontSize": "14px"}, children=[
                html.Span(f"批數 {len(res['batches'])}"),
                html.Span(f"X* 域偏移批 {n_anom}", style={"color": _BAD if n_anom else _OK, "fontWeight": 500}),
                html.Span(f"GSI 均值 {gsi_mean:.2f}"),
                html.Span(f"可信度：{'CP-band（最壞覆蓋 ≥' + format(s['coverage_floor'], '.0%') + '）' if s['cv_available'] else '無帶（Y 不足）'}"),
                html.Span(f"殘差漂移 G2：{yflag(rd)}" + ("　映射斷裂" if rd.get("alarm") else ""),
                          style={"color": _BAD if rd.get("alarm") else _OK, "fontWeight": 500}),
                html.Span(f"Y-vs-歷史 G1：{yflag(g1)}" + ("　Y 偏移" if g1.get("alarm") else ""),
                          style={"color": _BAD if g1.get("alarm") else _OK, "fontWeight": 500}),
            ])
            return stok, "✓ 評分完成", cards, score_figure(res)
        except Exception as e:
            return no_update, f"⛔ {e}", no_update, no_update

    @app.callback(Output("bw-detail", "children"),
                  Input("bw-scoregraph", "clickData"), State("bw-score-token", "data"),
                  prevent_initial_call=True)
    def _bw_detail(click, stok):
        if not click or stok not in _SCORES:
            return no_update
        i = int(click["points"][0]["x"]) - 1
        res = _SCORES[stok]
        b = res["batches"][i]
        s = res["summary"]
        y_obs = res["y"][i] if i < len(res.get("y", [])) else None
        band = (f"[{b['band_lo']:.3f}, {b['band_hi']:.3f}]" if b["band_lo"] is not None else "—（無帶）")
        attr = attribute_batch(res["_model_tok"], res["_xstar"][i])  # 新 G2/G3 歸因（取代舊 rbc_top）
        g2, g3 = attr["g2"], attr["g3"]
        g2_cause = (f"{g2['top_param']}（推動 Ŷ {g2['delta_yhat']:+.3f}）" if g2["reliable"]
                    else "⚠ X* 離域，Ŷ 敏感度歸因不可信")
        g3_cause = (f"{g3['top_param']}（{g3['top_feature']}）" if g3.get("available") and g3.get("anomaly")
                    else ("域內未觸發" if g3.get("available") else "—（X* 降維中，暫不歸因）"))
        rows = [("時間", res["batch_start_times"][i][:16]),
                ("Ŷ（虛擬量測）", f"{b['yhat']:.3f}　可信帶 {band}"),
                ("實際 Y", f"{y_obs:.3f}" if y_obs is not None else "未量測"),
                ("T² / 限", f"{b['t2']:.2f} / {s['t2_lim']:.2f}" + ("　⚠ 超限" if b["t2_over"] else "")),
                ("SPE / 限", f"{b['spe']:.2f} / {s['spe_lim']:.2f}" + ("　⚠ 超限" if b["spe_over"] else "")),
                ("GSI", f"{b['gsi']:.2f}"),
                ("Ŷ 可信", "✓ 域內" if b["yhat_reliable"] else "⚠ X* 離建模域（Ŷ 不可信）"),
                ("G2 哪個參數推動 Ŷ", g2_cause),
                ("G3 哪個參數推出域", g3_cause)]
        return _card([html.Div(f"批 P{i + 1} 細節", style={"fontWeight": 500, "marginBottom": "6px"}),
                      html.Table([html.Tr([html.Td(k, style={"color": "#51607a", "padding": "2px 10px 2px 0"}),
                                           html.Td(v)]) for k, v in rows], style={"fontSize": "13px"})])

    @app.callback(Output("bw-step", "data"), Output("bw-navmsg", "children"),
                  Input("bw-next", "n_clicks"), Input("bw-prev", "n_clicks"),
                  State("bw-step", "data"), State("bw-q1", "data"), State("bw-machine", "data"),
                  State("bw-params", "value"), State("bw-cut-token", "data"), State("bw-job", "data"),
                  State("bw-model", "data"), State("bw-score-token", "data"),
                  prevent_initial_call=True)
    def _bw_nav(_n, _p, step, q1, machine, params, cut, job, model, score):
        if ctx.triggered_id == "bw-prev":
            return max(1, (step or 1) - 1), ""
        j = _JOBS.get(job or -1)
        flags = {"loaded": bool(q1), "machine": bool(machine), "params": bool(params), "cut": bool(cut),
                 "converted": bool(j and j.get("done") and not j.get("error")),
                 "model": bool(model), "scored": bool(score)}
        return guard_next(step or 1, flags)

    @app.callback([Output(f"bwp{i}", "style") for i in range(1, 10)] + [Output("bw-stepbar", "children")],
                  Input("bw-step", "data"))
    def _bw_panels(step):
        step = step or 1
        styles = [{"display": "block"} if i == step else {"display": "none"} for i in range(1, 10)]
        bar = "　".join(f"[{t}]" if i + 1 == step else t for i, t in enumerate(_STEP_TITLES))
        return (*styles, bar)
