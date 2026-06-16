"""製程健康監控 — 產品 UI（總覽 → 新建精靈 → 結果下鑽）。

依 docs/frontend_design_guide.md（design-advisor）：三屏對應 Shneiderman overview→zoom→details。
瓶子優先：公開資料集線上模擬，PI 為 stub。本檔為**呈現殼**——所有邏輯在已單元測試的
``health_index.deploy.demo``；UI 不含演算法。直接展示系統前端（無銷售頁，使用者 2026-06-16 定）。

啟動：``PYTHONPATH=src python frontend/demo_app.py``，開 http://127.0.0.1:8051
注意：UI 視覺/點擊未在本環境渲染驗證（NOT VERIFIED-visual）；callback 邏輯由 tests/test_demo.py + 直呼驗證。
"""

from __future__ import annotations

import datetime as _dt
import glob
import os
import tempfile

import plotly.graph_objects as go
from dash import ALL, Dash, Input, Output, State, ctx, dcc, html, no_update

from health_index.deploy import demo
from health_index.deploy.events import IncidentStore

_MODELS_DIR = os.path.join(tempfile.gettempdir(), "health_index_demo_models")
_INCIDENTS = os.path.join(_MODELS_DIR, "incidents.json")  # 事件閉環持久化
_ACCENT = "#4338ca"  # 單一品牌 accent（taste-skill：靛藍）
_OK, _BAD, _CONF = "#16a34a", "#dc2626", "#1565c0"  # 語義狀態色：綠健康/紅告警/藍可信度
_REGION_COLOR = {"golden": _OK, "clean_reentry": "#66bb6a", "drift": _BAD, "other": "#ef6c00"}
_REGION_ZH = {"golden": "黃金基準", "clean_reentry": "乾淨回歸", "drift": "殘留飄移", "other": "換產品/其他"}

app = Dash(__name__, title="ProcessGuard 製程健康監控")


def _card(children, style=None):
    base = {"border": "1px solid #e3e8ef", "borderRadius": "12px", "padding": "16px 18px", "background": "#fff"}
    return html.Div(children, style={**base, **(style or {})})


def _btn(label, bid, primary=False, **kw):
    st = {"padding": "9px 18px", "borderRadius": "9px", "border": f"1px solid {_ACCENT}", "cursor": "pointer",
          "background": _ACCENT if primary else "#fff", "color": "#fff" if primary else _ACCENT, "fontWeight": 500}
    return html.Button(label, id=bid, n_clicks=0, style={**st, **kw.pop("style", {})}, **kw)


_LEGEND = html.Div([
    html.Span("圖例：", style={"color": "#51607a"}),
    html.Span("● 健康", style={"color": _OK, "marginRight": "12px"}),
    html.Span("● 告警", style={"color": _BAD, "marginRight": "12px"}),
    html.Span("┈ 可信度", style={"color": _CONF}),
], style={"fontSize": "13px", "margin": "6px 0"})

app.layout = html.Div(
    style={"maxWidth": "1040px", "margin": "0 auto", "fontFamily": "-apple-system,'Segoe UI',Inter,system-ui,sans-serif",
           "padding": "20px", "color": "#0f172a"},
    children=[
        dcc.Store(id="screen", data="home"),
        dcc.Store(id="wstep", data=1),
        dcc.Store(id="bundle-store"),
        dcc.Store(id="nrows", data=1500),
        dcc.Store(id="events-refresh", data=0),
        dcc.Interval(id="tick", interval=60000, n_intervals=0),  # 自動刷新（60s）——盤面不需手動戳
        html.Div(style={"display": "flex", "alignItems": "center", "justifyContent": "space-between",
                        "borderBottom": "1px solid #e3e8ef", "paddingBottom": "12px", "marginBottom": "16px"},
                 children=[
                     html.Div([html.Span("P", style={"background": _ACCENT, "color": "#fff", "borderRadius": "7px",
                               "padding": "2px 8px", "marginRight": "8px", "fontWeight": 500}), "ProcessGuard ",
                               html.Span("製程健康監控", style={"color": "#51607a", "fontSize": "14px"})],
                              style={"fontWeight": 500, "fontSize": "17px"}),
                     html.Div([_btn("事件", "nav-events", style={"marginRight": "8px"}), _btn("總覽", "nav-home")]),
                 ]),
        html.Div(id="scr-home"),
        html.Div(id="scr-wizard", style={"display": "none"}),
        html.Div(id="scr-results", style={"display": "none"}),
        html.Div(id="scr-events", style={"display": "none"}),
        dcc.Download(id="dl-incidents"),
        dcc.Download(id="dl-timeline"),
    ],
)


# ---------- Home（監控總覽）----------
def _home_view():
    return [
        html.Div(style={"display": "flex", "justifyContent": "space-between", "alignItems": "flex-start"}, children=[
            html.Div([html.H2("監控總覽", style={"margin": "0 0 4px", "fontWeight": 500}),
                      html.Div("目前線上的監控模型與健康狀態", style={"color": "#51607a", "fontSize": "14px"})]),
            _btn("＋ 新建監控模型", "btn-new", primary=True),
        ]),
        html.Div(id="home-metrics", style={"margin": "16px 0"}),
        _LEGEND,
    ]


_STATUS = {"healthy": ("● 健康", _OK), "alarm": ("● 告警", _BAD), "data_unavailable": ("○ 資料源不可得", "#888"),
           "unknown": ("○ 未知", "#888")}


@app.callback(Output("home-metrics", "children"), Input("screen", "data"), Input("events-refresh", "data"),
              Input("tick", "n_intervals"))
def _home_metrics(screen, _r, _t):
    pv = demo.plant_overview(_MODELS_DIR, incidents_path=_INCIDENTS)  # 全廠視圖 + 各裝置未結事件
    ov = pv["assets"]
    n_alarm = pv["n_alarm"]
    sources = demo.available_datasets()
    pcol = {"alarm": _BAD, "healthy": _OK, "empty": "#888"}[pv["plant_status"]]
    ptxt = {"alarm": "⚠ 有裝置告警", "healthy": "✅ 全廠健康", "empty": "尚無模型"}[pv["plant_status"]]
    banner = html.Div(f"全廠狀態：{ptxt}　·　{pv['n_assets']} 裝置／{n_alarm} 告警中",
                      style={"borderLeft": f"4px solid {pcol}", "background": "#f6f7f9", "padding": "10px 14px",
                             "color": pcol, "fontWeight": 500, "marginBottom": "12px"})
    tiles = html.Div(style={"display": "grid", "gridTemplateColumns": "repeat(3,1fr)", "gap": "12px"}, children=[
        _tile("監控中模型", str(len(ov))),
        _tile("告警中", str(n_alarm)),
        _tile("可監控資料源", str(len(sources))),
    ])
    if ov:
        cards = []
        for r in ov:
            txt, col = _STATUS.get(r["status"], _STATUS["unknown"])
            openable = r["status"] in ("healthy", "alarm")  # 可評分才可點進結果
            hp = f"健康度 {r['health']}" if r["health"] is not None else "（需該資料源才能評分）"
            ai = r.get("active_incidents", 0)
            children = [
                html.Div(r["product"], style={"fontWeight": 500}),
                html.Div(txt, style={"color": col, "fontSize": "14px", "margin": "4px 0"}),
                html.Div(hp, style={"color": "#51607a", "fontSize": "12px"}),
                html.Div(f"未結事件 {ai}" if ai else "", style={"color": _BAD, "fontSize": "12px"}),
                html.Div("點此查看 →" if openable else "—",
                         style={"color": _ACCENT if openable else "#bbb", "fontSize": "12px", "marginTop": "6px"}),
            ]
            style = {"display": "inline-block", "width": "190px", "marginRight": "10px", "verticalAlign": "top",
                     "border": f"1px solid {col if r['status'] == 'alarm' else '#e3e8ef'}",
                     "borderRadius": "12px", "padding": "16px 18px", "background": "#fff",
                     "cursor": "pointer" if openable else "default"}
            cards.append(html.Div(children, id={"type": "open-model", "product": r["product"]},
                                  n_clicks=0, style=style) if openable
                         else html.Div(children, style=style))
        body = html.Div([html.Div("已建立模型（當前健康）— 點卡片查看結果", style={"fontWeight": 500, "margin": "8px 0"}),
                         html.Div(cards)])
    else:
        body = html.Div("尚無模型。點右上「＋ 新建監控模型」開始，選一段正常時期當基準。",
                        style={"color": "#51607a", "background": "#f6f7f9", "padding": "14px", "borderRadius": "10px"})
    return html.Div([banner, tiles, html.Div(body, style={"marginTop": "14px"})])


def _tile(k, v, small=False):
    return html.Div([html.Div(k, style={"fontSize": "13px", "color": "#51607a"}),
                     html.Div(v, style={"fontSize": "15px" if small else "24px", "fontWeight": 500,
                                        "marginTop": "4px", "color": "#51607a" if small else "#0f172a"})],
                    style={"background": "#f6f7f9", "borderRadius": "10px", "padding": "14px"})


# ---------- Wizard（新建精靈）----------
_STEPS = ["選資料源", "訓練資料範圍", "測試資料範圍", "建立模型", "完成"]


def _wizard_view():
    return [
        html.Div(style={"display": "flex", "justifyContent": "space-between", "alignItems": "center"}, children=[
            html.H2("新建監控模型", style={"margin": 0, "fontWeight": 500}),
            html.Span(id="wstep-left", style={"background": "#eef2ff", "color": _ACCENT, "padding": "4px 12px",
                      "borderRadius": "999px", "fontSize": "13px"}),
        ]),
        html.Div(id="stepper", style={"display": "flex", "alignItems": "center", "gap": "6px", "margin": "14px 0"}),
        _card([
            html.Div(id="wp1", children=[
                html.Div("① 選擇要監控的產品 / 資料源", style={"fontWeight": 500, "marginBottom": "8px"}),
                dcc.Dropdown(id="dataset", options=[{"label": d, "value": d} for d in demo.available_datasets()],
                             value="synthetic", clearable=False, style={"width": "340px"}),
                html.Div(id="overview", style={"marginTop": "10px", "fontSize": "14px", "color": "#51607a"}),
            ]),
            html.Div(id="wp2", style={"display": "none"}, children=[
                html.Div("② 圈選訓練資料時間範圍（黃金期，代表正常）", style={"fontWeight": 500, "marginBottom": "10px"}),
                dcc.RangeSlider(id="golden-range", min=0, max=1500, value=[0, 600], allowCross=False,
                                tooltip={"placement": "bottom", "always_visible": True}),
                html.Div(id="golden-readout", style={"fontSize": "13px", "color": _OK, "marginTop": "6px"}),
            ]),
            html.Div(id="wp3", style={"display": "none"}, children=[
                html.Div("③ 測試資料範圍與評分窗長", style={"fontWeight": 500, "marginBottom": "10px"}),
                html.Div("測試＝全程重放（含訓練段外的後續資料），模型在其上找隱性飄移。",
                         style={"fontSize": "13px", "color": "#51607a", "marginBottom": "10px"}),
                html.Label("評分窗長：", style={"marginRight": "8px"}),
                dcc.Input(id="window", type="number", value=60, min=10, step=10, style={"width": "100px"}),
            ]),
            html.Div(id="wp4", style={"display": "none"}, children=[
                html.Div("④ 建立模型並自動驗收", style={"fontWeight": 500, "marginBottom": "10px"}),
                _btn("建立模型", "btn-build", primary=True),
                dcc.Loading(html.Div(id="build-result", style={"marginTop": "12px", "fontSize": "14px"})),
            ]),
            html.Div(id="wp5", style={"display": "none"}, children=[
                html.Div("⑤ 完成", style={"fontWeight": 500, "marginBottom": "8px"}),
                html.Div("模型已上線。點下方查看它套用在測試資料上的健康指標。",
                         style={"fontSize": "14px", "color": "#51607a", "marginBottom": "12px"}),
                _btn("查看健康指標 →", "go-results", primary=True),
            ]),
        ], style={"minHeight": "180px", "margin": "12px 0"}),
        html.Div(style={"display": "flex", "justifyContent": "space-between"}, children=[
            _btn("← 上一關", "btn-back"), _btn("下一關 →", "btn-next"),
        ]),
    ]


def _results_view():
    return [
        html.Div(style={"display": "flex", "justifyContent": "space-between", "alignItems": "center"}, children=[
            html.Div([html.H2("健康指標", style={"margin": "0 0 4px", "fontWeight": 500}),
                      html.Div("綠＝健康　紅＝超標告警　虛線＝可信度", style={"color": "#51607a", "fontSize": "14px"})]),
            _btn("← 回總覽", "btn-results-home"),
        ]),
        _LEGEND,
        dcc.Loading(html.Div(id="run-status", style={"margin": "8px 0", "fontSize": "18px", "fontWeight": 500})),
        dcc.Loading(dcc.Graph(id="timeline")),
        dcc.Loading(dcc.Graph(id="ymap")),
        html.P("點選時間線上任一窗 → 下方顯示該窗超標的製程參數（GSI/T²/SPE、RBC 肇因、各層 p-value、Ŷ vs 實際 Y）。",
               style={"color": "#51607a", "fontSize": "13px"}),
        _btn("匯出時間線 CSV", "btn-export-timeline"),
        dcc.Loading(html.Div(id="window-detail")),
    ]


def _events_view():
    return [
        html.Div(style={"display": "flex", "justifyContent": "space-between", "alignItems": "center"}, children=[
            html.Div([html.H2("事件", style={"margin": "0 0 4px", "fontWeight": 500}),
                      html.Div("告警事件閉環：偵測 → 認領 → 關閉（含 MTTR、處置留痕）",
                               style={"color": "#51607a", "fontSize": "14px"})]),
            html.Div([_btn("匯出事件 CSV", "btn-export-incidents", style={"marginRight": "8px"}),
                      _btn("← 回總覽", "btn-events-home")]),
        ]),
        html.Div(style={"margin": "10px 0"}, children=[
            html.Label("操作者（記入稽核軌跡）：", style={"fontSize": "13px", "color": "#51607a"}),
            dcc.Input(id="event-actor", type="text", placeholder="姓名 / 工號",
                      style={"width": "200px", "marginLeft": "8px"}),
            html.Span("　處置記錄填在各事件卡上再按「關閉」。", style={"fontSize": "12px", "color": "#888"}),
        ]),
        dcc.Loading(html.Div(id="events-body")),
    ]


# 初始填入各屏內容（依 id 對應，避免索引脆弱）
_VIEWS = {"scr-home": _home_view, "scr-wizard": _wizard_view, "scr-results": _results_view, "scr-events": _events_view}
for _child in app.layout.children:
    if getattr(_child, "id", None) in _VIEWS:
        _child.children = _VIEWS[_child.id]()


# ---------- 路由與步進 ----------
@app.callback(Output("screen", "data"),
              Input("nav-home", "n_clicks"), Input("btn-new", "n_clicks"),
              Input("go-results", "n_clicks"), Input("btn-results-home", "n_clicks"),
              Input("nav-events", "n_clicks"), Input("btn-events-home", "n_clicks"),
              prevent_initial_call=True)
def _route(*_):
    t = ctx.triggered_id
    return {"nav-home": "home", "btn-results-home": "home", "btn-new": "wizard",
            "go-results": "results", "nav-events": "events", "btn-events-home": "home"}.get(t, no_update)


@app.callback(Output("bundle-store", "data", allow_duplicate=True), Output("screen", "data", allow_duplicate=True),
              Input({"type": "open-model", "product": ALL}, "n_clicks"), prevent_initial_call=True)
def _open_model(clicks):
    """點總覽模型卡 → 載入該模型 bundle + 進結果頁（解決『只能看燈、不能查看模型』）。"""
    t = ctx.triggered_id
    if not t or not clicks or not any(c for c in clicks if c):
        return no_update, no_update
    product = t["product"]
    return {"bundle_path": os.path.join(_MODELS_DIR, f"{product}.joblib"), "product": product}, "results"


@app.callback(Output("wstep", "data"),
              Input("btn-new", "n_clicks"), Input("btn-next", "n_clicks"), Input("btn-back", "n_clicks"),
              State("wstep", "data"), prevent_initial_call=True)
def _wstep(_n, _nx, _bk, cur):
    t = ctx.triggered_id
    if t == "btn-new":
        return 1
    if t == "btn-next":
        return min(len(_STEPS), (cur or 1) + 1)
    return max(1, (cur or 1) - 1)


@app.callback(Output("scr-home", "style"), Output("scr-wizard", "style"), Output("scr-results", "style"),
              Output("scr-events", "style"), Input("screen", "data"))
def _show_screen(screen):
    vis, hid = {"display": "block"}, {"display": "none"}
    return (vis if screen == "home" else hid, vis if screen == "wizard" else hid,
            vis if screen == "results" else hid, vis if screen == "events" else hid)


@app.callback(Output("stepper", "children"), Output("wstep-left", "children"),
              Output("wp1", "style"), Output("wp2", "style"), Output("wp3", "style"),
              Output("wp4", "style"), Output("wp5", "style"), Input("wstep", "data"))
def _render_steps(step):
    step = step or 1
    dots = []
    for i, name in enumerate(_STEPS, 1):
        done, cur = i < step, i == step
        col = _OK if done else (_ACCENT if cur else "#b4b2a9")
        n = html.Span("✓" if done else str(i), style={"display": "inline-flex", "width": "22px", "height": "22px",
            "borderRadius": "50%", "alignItems": "center", "justifyContent": "center", "fontSize": "12px",
            "border": f"1px solid {col}", "color": "#fff" if (done or cur) else col,
            "background": col if (done or cur) else "#fff", "marginRight": "5px"})
        dots.append(html.Span([n, html.Span(name, style={"color": "#0f172a" if cur else "#51607a"})],
                              style={"fontSize": "13px", "display": "inline-flex", "alignItems": "center"}))
        if i < len(_STEPS):
            dots.append(html.Span(style={"flex": 1, "height": "1px", "background": "#e3e8ef", "minWidth": "8px"}))
    left = f"第 {step} 關／共 {len(_STEPS)} 關，還剩 {len(_STEPS) - step} 關"
    sty = [{"display": "block"} if i == step else {"display": "none"} for i in range(1, 6)]
    return dots, left, *sty


# ---------- 資料源 → 時間軸 ----------
@app.callback(Output("overview", "children"), Output("golden-range", "max"), Output("golden-range", "value"),
              Output("golden-range", "marks"), Output("golden-readout", "children"), Output("nrows", "data"),
              Input("dataset", "value"))
def _on_dataset(name):
    try:
        ov = demo.dataset_overview(name)
    except Exception as e:
        return html.Span(f"無法載入資料集：{e}", style={"color": _BAD}), 1500, [0, 600], {}, "", 1500
    n = ov["n_rows"]
    g = ov["golden_suggested"] or [0, int(0.4 * n)]
    marks = {0: "0", n: str(n), n // 2: str(n // 2)}
    txt = html.Div([html.Div(f"列數 {n}，變數 {ov['n_features']} 維，建議 golden 段 {ov['golden_suggested']}"),
                    html.Div(f"分段：" + "、".join(f"{s['label']}[{s['start']}:{s['end']}]" for s in ov["segments"]),
                             style={"color": "#51607a"})])
    return txt, n, g, marks, f"已選訓練段 [{g[0]}:{g[1]}]　約 {g[1] - g[0]} 筆", n


@app.callback(Output("golden-readout", "children", allow_duplicate=True), Input("golden-range", "value"),
              prevent_initial_call=True)
def _golden_readout(v):
    return f"已選訓練段 [{v[0]}:{v[1]}]　約 {v[1] - v[0]} 筆"


# ---------- 建模 ----------
@app.callback(Output("bundle-store", "data"), Output("build-result", "children"),
              Input("btn-build", "n_clicks"), State("dataset", "value"), State("golden-range", "value"),
              prevent_initial_call=True)
def _build(_n, name, grange):
    try:
        # 先驗收（gate）：FAIL → 不存檔（不落地），修複審揪出的「先 save 後驗收、FAIL 仍落地」治理漏洞。
        acc = demo.acceptance_summary(name, window=60)
        recall_txt = (f"、事故 recall {acc['drift_recall']}" if acc.get("drift_recall") is not None else "")
        if acc.get("available") and not acc["passed"]:
            return no_update, html.Div([
                html.Div("⛔ 驗收未過，未存檔：" + acc["verdict"], style={"color": _BAD, "fontWeight": 500}),
                html.Div(f"hold-out golden 誤報率 {acc['holdout_golden_fpr']}"
                         f"（{'≤ 目標' if acc['fpr_ok'] else '過高'}）{recall_txt}",
                         style={"fontSize": "13px", "color": "#51607a"}),
                html.Div("請改選更平穩的黃金期、或檢查資料源後重建（不合格模型不予上線）。",
                         style={"fontSize": "13px", "color": "#51607a"}),
            ])
        m = demo.build_and_save_model(name, golden=tuple(grange), models_dir=_MODELS_DIR,
                                      created_at=_dt.datetime.now().isoformat())
        if acc.get("available"):
            acc_line = html.Div([
                html.Div("✅ 驗收通過：" + acc["verdict"], style={"color": _OK, "fontWeight": 500}),
                html.Div(f"hold-out golden 誤報率 {acc['holdout_golden_fpr']}"
                         f"（{'≤ 目標' if acc['fpr_ok'] else '過高'}）{recall_txt}",
                         style={"fontSize": "13px", "color": "#51607a"}),
            ])
        else:
            acc_line = html.Div(f"（驗收未跑：{acc.get('error', '資料不足')}）", style={"fontSize": "13px", "color": "#888"})
        msg = html.Div([
            html.Div(f"✅ 模型已建立並存檔：{m['product']}", style={"color": _OK, "fontWeight": 500}),
            html.Div(f"golden {m['golden_range']}，{m['n_golden']} 樣本，指紋健康度 {m['fingerprint_hi']:.3f}"
                     + ("，含軟測量 Ŷ" if m.get("has_y_health") else ""), style={"fontSize": "13px", "color": "#51607a"}),
            acc_line,
            html.Div("按「下一關」查看健康指標。", style={"fontSize": "13px", "color": "#51607a", "marginTop": "4px"}),
        ])
        return m, msg
    except Exception as e:
        return no_update, html.Span(f"❌ 建模失敗：{e}", style={"color": _BAD})


# ---------- 結果（進入 results 屏時評分）----------
@app.callback(Output("run-status", "children"), Output("timeline", "figure"), Output("ymap", "figure"),
              Input("screen", "data"), State("bundle-store", "data"), State("dataset", "value"),
              State("window", "value"), prevent_initial_call=True)
def _run(screen, bundle, name, window):
    if screen != "results":
        return no_update, no_update, no_update
    if not bundle:
        return html.Span("⚠ 請先建立模型", style={"color": "#ef6c00"}), go.Figure(), go.Figure()
    name = bundle.get("product") or name  # 從總覽開啟既有模型時，資料源＝該模型 product（非 dropdown）
    try:
        tl = demo.score_timeline(bundle["bundle_path"], name, window=int(window or 60))
    except Exception as e:
        return html.Span(f"❌ 模擬失敗：{e}", style={"color": _BAD}), go.Figure(), go.Figure()
    pts = tl["points"]
    # 增量5：持續告警 → 開事件（同裝置防重複；reuse 已算 pts，不重複評分）。最嚴重窗取 RBC 首位當肇因。
    alarmed = [p for p in pts if p["persisted_alarm"]]
    if alarmed:
        worst = min(alarmed, key=lambda p: p["health_index"])
        try:
            dd = demo.window_detail(bundle["bundle_path"], name, worst["start"], worst["end"], compute_fwer=False)
            top = dd["rbc_ranking"][0][0] if dd.get("rbc_ranking") else "(見窗下鑽)"
        except Exception:
            top = "(見窗下鑽)"
        IncidentStore(_INCIDENTS).open_incident(product=name, window=[worst["start"], worst["end"]],
            health=worst["health_index"], confidence=worst["confidence"], top_cause=top, detected_at=worst.get("ts"))
    xs = [p.get("ts") or p["start"] for p in pts]  # wall-clock（對齊 DCS/historian）；無時間戳退回樣本索引
    his = [p["health_index"] for p in pts]
    colors = [_REGION_COLOR[p["region"]] for p in pts]
    # customdata 末位帶窗 start（時間軸改 wall-clock 後，_detail 不能再用 x 反推索引）
    custom = [[p["spe_mean"], p["gsi_mean"], _REGION_ZH[p["region"]], p["start"]] for p in pts]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=xs, y=his, mode="lines+markers", marker={"color": colors, "size": 9},
                  line={"color": "#999"}, name="健康指標", customdata=custom,
                  hovertemplate="時間 %{x}<br>健康度 %{y:.3f}<br>SPE %{customdata[0]}　GSI %{customdata[1]}<br>%{customdata[2]}<extra></extra>"))
    fig.add_trace(go.Scatter(x=xs, y=[p["confidence"] for p in pts], mode="lines",
                  line={"color": _CONF, "dash": "dot"}, name="可信度",
                  hovertemplate="時間 %{x}<br>可信度 %{y:.3f}<extra></extra>"))
    al = [(p.get("ts") or p["start"], p["health_index"], p["start"]) for p in pts if p["persisted_alarm"]]
    if al:
        fig.add_trace(go.Scatter(x=[a[0] for a in al], y=[a[1] for a in al], mode="markers",
                      marker={"symbol": "x", "color": _BAD, "size": 14}, name="告警",
                      customdata=[[a[2]] for a in al]))
    fig.add_hline(y=0.6, line_dash="dash", line_color="#888", annotation_text="告警門檻 0.6")
    fig.update_layout(yaxis={"title": "健康指標 (1=健康)", "range": [0, 1.05]},
                      xaxis={"title": "時間"}, height=420, legend={"orientation": "h"})
    ymap = go.Figure()
    if tl.get("has_y_mapping"):
        yhat = [p.get("yhat_mean") for p in pts]
        band = [p.get("yhat_band") or 0 for p in pts]
        up = [h + b for h, b in zip(yhat, band)]
        lo = [h - b for h, b in zip(yhat, band)]
        ymap.add_trace(go.Scatter(x=xs + xs[::-1], y=up + lo[::-1], fill="toself",
                       fillcolor="rgba(21,101,192,0.12)", line={"color": "rgba(0,0,0,0)"},
                       name="conformal 帶", hoverinfo="skip"))
        ymap.add_trace(go.Scatter(x=xs, y=yhat, mode="lines", line={"color": _CONF}, name="Ŷ 軟測量預測"))
        ya = [(p.get("ts") or p["start"], p["y_actual_mean"]) for p in pts if p.get("y_actual_mean") is not None]
        if ya:
            ymap.add_trace(go.Scatter(x=[a[0] for a in ya], y=[a[1] for a in ya], mode="markers",
                           marker={"color": _BAD, "size": 6}, name="實際 Y（量測到達）"))
        ymap.update_layout(title="L3 軟測量：Ŷ 預測 vs 實際 Y（帶外＝X→Y 關係偏移）",
                           xaxis={"title": "時間"}, yaxis={"title": "Y（軟量測標的）"},
                           height=300, legend={"orientation": "h"})
    else:
        ymap.update_layout(height=80, annotations=[{"text": "此模型無 Y 軟量測標的（不顯示映射子圖）",
                           "showarrow": False, "font": {"color": "#999"}}],
                           xaxis={"visible": False}, yaxis={"visible": False})
    n_alarm = tl["n_alarms"]
    msg = "⚠ 偵測到 " + str(n_alarm) + " 個告警窗（製程關係偏移）" if n_alarm else "✅ 全程健康"
    note = (f"　·　高維/長資料集已降採樣為 {tl['n_windows']} 窗顯示" if tl.get("subsampled") else "")
    status = html.Span([html.Span(msg, style={"color": _BAD if n_alarm else _OK}),
                        html.Span(note, style={"color": "#888", "fontSize": "13px", "fontWeight": 400})])
    return status, fig, ymap


@app.callback(Output("window-detail", "children"), Input("timeline", "clickData"),
              State("bundle-store", "data"), State("dataset", "value"), State("window", "value"),
              prevent_initial_call=True)
def _detail(click, bundle, name, window):
    if not bundle or not click:
        return ""
    name = bundle.get("product") or name  # 與 _run 一致：資料源＝模型 product
    pt = click["points"][0]
    w = int(window or 60)
    cd = pt.get("customdata")  # 末位為窗 start（x 軸已改 wall-clock，不能用 x 反推）
    if cd:
        start = int(cd[-1])
    else:  # 退路：非重疊窗 → pointIndex × 窗長
        start = int(pt.get("pointNumber", pt.get("pointIndex", 0))) * w
    end = start + w
    try:
        d = demo.window_detail(bundle["bundle_path"], name, start, end, compute_fwer=True)
    except Exception as e:
        return html.Span(f"❌ 詳細指標載入失敗：{e}", style={"color": _BAD})
    mspc, pv = d["mspc"], (d["fwer_pvalues"] or {})
    rows = [html.Tr([html.Td(d["layers"][k]["name"]), html.Td(k),
                     html.Td("⚠" if d["layers"][k]["unhealthy"] else "✅"), html.Td(str(pv.get(k, "—"))),
                     html.Td(d["layers"][k]["action"], style={"color": "#51607a", "fontSize": "12px"})])
            for k in ("L1", "L2", "L4")]
    rbc_top = "、".join(f"{v}({s})" for v, s in d["rbc_ranking"][:5])
    ss = d.get("soft_sensor", {})
    if not ss.get("available"):
        ss_line = "軟測量（Ŷ / 可信度）：此模型無 Y 標的（未提供軟量測）。"
    elif ss.get("n_y_obs", 0) > 0:
        mh = ss.get("map_health")
        ss_line = (f"軟測量：Ŷ {ss['yhat_mean']}　實際 Y {ss['y_actual_mean']}　±帶 {ss['band_half_mean']}"
                   f"（{'conformal' if ss['cp_available'] else 'std 近似'}，{ss['n_y_obs']} 筆 Y）"
                   f"　X→Y 可信度：{mh if mh is not None else '觀測不足'}")
    else:
        ss_line = "軟測量：本窗尚無 Y 到達（延遲量測）——待 Y 落地後給 Ŷ 與 X→Y 可信度。"
    v = d.get("verdict", {})
    vcol = {"ok": _OK, "warn": "#b26a00", "bad": _BAD}.get(v.get("tone"), "#51607a")
    top_var = d["rbc_ranking"][0][0] if d.get("rbc_ranking") else "(待查)"
    sop = (f"建議動作：現場確認「{top_var}」相關設備，必要時依 SOP 通報工程師（分機填於 SOP）。"
           if d["alarm"] else "建議動作：維持監看，無需處置。")  # 一行白話 SOP（作業員）
    return _card([
        html.H5(f"窗 [{start}:{end}] 詳細指標　{'⚠ 告警' if d['alarm'] else '✅ 正常'}", style={"margin": "0 0 8px"}),
        html.Div([html.Span(v.get("label", ""), style={"fontWeight": 500}), html.Span("　" + v.get("reason", "")),
                  html.Div(sop, style={"marginTop": "4px"})],
                 style={"background": "#f6f7f9", "borderLeft": f"4px solid {vcol}", "padding": "8px 12px",
                        "color": vcol, "marginBottom": "8px"}),
        html.Div(f"健康度 {d['subscores']}　|　可信度 {d['confidence']}"
                 "（操作域 T²；低＝外推應保留。低健康＋高可信＝可信的告警）",
                 style={"marginBottom": "6px", "fontWeight": 500}),
        html.Div(f"GSI {mspc['GSI_mean']}　|　T² {mspc['T2_mean']} / 限 {mspc['T2_limit']}（越限 {mspc['T2_exceed_frac']:.0%}）"
                 f"　|　SPE {mspc['SPE_mean']} / 限 {mspc['SPE_limit']}（越限 {mspc['SPE_exceed_frac']:.0%}）",
                 style={"marginBottom": "8px"}),
        html.Table([html.Thead(html.Tr([html.Th(h) for h in ("層", "代號", "狀態", "p-value", "建議檢查")]))]
                   + [html.Tbody(rows)], style={"width": "100%", "fontSize": "13px", "borderCollapse": "collapse"}),
        html.Div(f"RBC 肇因排行 (top5)：{rbc_top}", style={"marginTop": "8px"}),
        html.Div(ss_line, style={"marginTop": "6px", "color": _CONF}),
        html.Div(f"模型版本：{d['model_version']}", style={"color": "#888", "fontSize": "12px", "marginTop": "4px"}),
    ])


_SEV_COL = {"critical": _BAD, "warning": "#b26a00", "info": "#51607a"}


@app.callback(Output("events-body", "children"), Input("screen", "data"), Input("events-refresh", "data"),
              Input("tick", "n_intervals"))
def _events_body(screen, _r, _t):
    if screen != "events":
        return no_update
    ov = demo.event_overview(_INCIDENTS)
    st, roi, incs = ov["stats"], ov["roi"], ov["incidents"]
    mttr = st["mean_mttr_hr"]
    tiles = html.Div(style={"display": "grid", "gridTemplateColumns": "repeat(4,1fr)", "gap": "12px", "margin": "12px 0"},
                     children=[_tile("未結 open", str(st["open"])), _tile("處理中 ack", str(st["ack"])),
                               _tile("已關閉", str(st["closed"])), _tile("平均 MTTR(小時)", "—" if mttr is None else str(mttr))])
    roi_card = _card([
        html.Div("導入效益估算（情境假設，非實測損益）", style={"fontWeight": 500}),
        html.Div(f"critical {roi['n_critical_events']} 件 → 假設避免 {roi['assumed_prevented_stops']} 次非計畫停車 → 估省 ${roi['est_savings']:,.0f}",
                 style={"color": _OK, "margin": "4px 0"}),
        html.Div(f"假設：每次停車損失 ${roi['assumptions']['avg_loss_per_unplanned_stop']:,.0f}、避免比例 "
                 f"{roi['assumptions']['prevented_fraction']}。{roi['assumptions']['note']}",
                 style={"fontSize": "12px", "color": "#888"}),
    ], style={"margin": "10px 0"})
    if not incs:
        body = html.Div("尚無事件。在『查看健康指標』偵測到持續告警時自動開案。",
                        style={"color": "#51607a", "background": "#f6f7f9", "padding": "14px", "borderRadius": "10px"})
    else:
        cards = []
        for it in incs:
            sev = _SEV_COL.get(it["severity"], "#51607a")
            acts = []
            if it["status"] == "open":
                acts.append(_btn("認領 ACK", {"type": "ack-inc", "id": it["id"]}, style={"marginRight": "8px", "padding": "5px 12px"}))
            if it["status"] in ("open", "ack"):
                acts.append(dcc.Input(id={"type": "note-inc", "id": it["id"]}, type="text", placeholder="本案處置記錄",
                                      style={"width": "240px", "marginRight": "8px"}))
                acts.append(_btn("關閉", {"type": "close-inc", "id": it["id"]}, primary=True, style={"padding": "5px 12px"}))
            mttr_line = f"MTTR {it['mttr_sec'] / 3600:.2f} 小時｜處置：{it.get('close_note')}" if it.get("mttr_sec") else ""
            cards.append(_card([
                html.Div([html.Span(it["id"] + "　", style={"fontWeight": 500}),
                          html.Span(it["severity"], style={"color": sev, "fontWeight": 500}),
                          html.Span("　" + it["status"], style={"color": "#51607a"})]),
                html.Div(f"{it['product']}｜肇因 {it['top_cause']}｜健康 {it['health']}｜可信 {it['confidence']}｜{it['detected_at']}",
                         style={"fontSize": "13px", "color": "#51607a", "margin": "4px 0"}),
                html.Div(mttr_line, style={"fontSize": "12px", "color": "#888"}),
                html.Div(acts, style={"marginTop": "6px"}),
            ], style={"margin": "8px 0"}))
        body = html.Div(cards)
    return html.Div([tiles, roi_card, body])


@app.callback(Output("events-refresh", "data"),
              Input({"type": "ack-inc", "id": ALL}, "n_clicks"), Input({"type": "close-inc", "id": ALL}, "n_clicks"),
              State({"type": "note-inc", "id": ALL}, "value"), State("event-actor", "value"),
              State("events-refresh", "data"), prevent_initial_call=True)
def _event_action(_a, _c, _notes, actor, refresh):
    if not ctx.triggered or not ctx.triggered[0].get("value"):
        return no_update
    t = ctx.triggered_id
    if not isinstance(t, dict):
        return no_update
    actor = (actor or "").strip() or "未具名"  # 記入稽核軌跡（取代寫死「工程師」；真 auth 為 P2）
    store = IncidentStore(_INCIDENTS)
    try:
        if t["type"] == "ack-inc":
            store.ack(t["id"], by=actor)
        else:
            note = ""  # 取「本案卡片」的處置記錄（依 id 對應，不再共用單一框 → 不會貼錯案）
            for st in ctx.states_list[0]:
                if isinstance(st.get("id"), dict) and st["id"].get("id") == t["id"]:
                    note = st.get("value") or ""
                    break
            store.close(t["id"], note=note or "已處置", by=actor)
    except Exception:
        return no_update
    return (refresh or 0) + 1


@app.callback(Output("dl-incidents", "data"), Input("btn-export-incidents", "n_clicks"), prevent_initial_call=True)
def _dl_incidents(_n):
    incs = demo.event_overview(_INCIDENTS)["incidents"]
    return {"content": demo.incidents_to_csv(incs), "filename": "incidents.csv"}


@app.callback(Output("dl-timeline", "data"), Input("btn-export-timeline", "n_clicks"),
              State("bundle-store", "data"), prevent_initial_call=True)
def _dl_timeline(_n, bundle):
    if not bundle:
        return no_update
    name = bundle.get("product")
    tl = demo.score_timeline(bundle["bundle_path"], name)
    return {"content": demo.timeline_to_csv(tl["points"]), "filename": f"{name}_timeline.csv"}


if __name__ == "__main__":
    app.run(debug=False, port=8051)
