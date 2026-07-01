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

from health_index.deploy import catalog, demo
from health_index.deploy.assets import AssetStore
from health_index.deploy.events import IncidentStore

_MODELS_DIR = os.path.join(tempfile.gettempdir(), "health_index_demo_models")
_INCIDENTS = os.path.join(_MODELS_DIR, "incidents.json")  # 事件閉環持久化
_REGISTRY = os.path.join(_MODELS_DIR, "registry.json")  # 增量7 製程/模型 registry
_ACCENT = "#4338ca"  # 單一品牌 accent（taste-skill：靛藍）
_OK, _BAD, _CONF = "#16a34a", "#dc2626", "#1565c0"  # 語義狀態色：綠健康/紅告警/藍可信度
_REGION_COLOR = {"golden": _OK, "clean_reentry": "#66bb6a", "drift": _BAD, "other": "#ef6c00"}
_REGION_ZH = {"golden": "黃金基準", "clean_reentry": "乾淨回歸", "drift": "殘留飄移", "other": "換產品/其他"}

app = Dash(__name__, title="ProcessGuard 製程健康監控")
app.index_string = """<!DOCTYPE html>
<html><head>{%metas%}<meta name="viewport" content="width=device-width, initial-scale=1">{%favicon%}{%css%}
<style>@media (max-width:640px){.pg-grid{grid-template-columns:1fr !important}}
@keyframes pgflash{0%,100%{background:#fef2f2}50%{background:#fde0e0}}
.pg-flash{animation:pgflash 1.2s ease-in-out infinite}</style>
<title>{%title%}</title></head>
<body>{%app_entry%}<footer>{%config%}{%scripts%}{%renderer%}</footer></body></html>"""


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
        dcc.Store(id="registry-refresh", data=0),  # 建製程/建模/刪除後刷新總覽
        dcc.Store(id="wiz-proc"),                   # 精靈綁定：{process_id?, dataset?, display_name?, mode:new|swap}
        dcc.Store(id="hist-proc"),                  # 歷史頁要顯示哪個製程
        dcc.Store(id="preview-store"),              # golden 選擇預覽資料（dataset_preview）
        dcc.Store(id="golden-spec"),                # 目前 golden 規格（連續/勾選/自動）供建模
        dcc.Store(id="auto-runs"),                  # 自動挑選的 golden 區間（疊圖用）
        dcc.Store(id="tl-store"),  # 時間線 points（供門檻 slider 重繪，不重新評分）
        dcc.Interval(id="tick", interval=60000, n_intervals=0),  # 自動刷新（60s）——盤面不需手動戳
        html.Div(style={"display": "flex", "alignItems": "center", "justifyContent": "space-between",
                        "borderBottom": "1px solid #e3e8ef", "paddingBottom": "12px", "marginBottom": "16px"},
                 children=[
                     html.Div([html.Span("P", style={"background": _ACCENT, "color": "#fff", "borderRadius": "7px",
                               "padding": "2px 8px", "marginRight": "8px", "fontWeight": 500}), "ProcessGuard ",
                               html.Span("製程健康監控", style={"color": "#51607a", "fontSize": "14px"})],
                              style={"fontWeight": 500, "fontSize": "17px"}),
                     html.Div([
                         dcc.RadioItems(id="role-sel", value="engineer", inline=True,
                                        options=[{"label": " 作業員", "value": "operator"},
                                                 {"label": " 工程師", "value": "engineer"}],
                                        style={"display": "inline-block", "marginRight": "12px", "fontSize": "13px"}),
                         _btn("段分析", "nav-segview", style={"marginRight": "8px"}),
                         _btn("事件", "nav-events", style={"marginRight": "8px"}), _btn("總覽", "nav-home")]),
                 ]),
        html.Div(id="scr-home"),
        html.Div(id="scr-wizard", style={"display": "none"}),
        html.Div(id="scr-results", style={"display": "none"}),
        html.Div(id="scr-events", style={"display": "none"}),
        html.Div(id="scr-history", style={"display": "none"}),
        html.Div(id="scr-segview", style={"display": "none"}),
        dcc.Download(id="dl-incidents"),
        dcc.Download(id="dl-timeline"),
    ],
)


# ---------- Home（監控總覽）----------
def _home_view():
    return [
        html.Div(style={"display": "flex", "justifyContent": "space-between", "alignItems": "flex-start"}, children=[
            html.Div([html.H2("監控總覽", style={"margin": "0 0 4px", "fontWeight": 500}),
                      html.Div("各製程（監控點）的現役模型與健康狀態", style={"color": "#51607a", "fontSize": "14px"})]),
            html.Div([_btn("＋ 新建製程", "btn-newproc", style={"marginRight": "8px"}),
                      _btn("＋ 新建監控模型", "btn-new", primary=True)]),
        ]),
        html.Div(id="newproc-form", style={"display": "none", "margin": "12px 0"}, children=[_card([
            html.Div("新建製程（先佔名，可稍後熱插拔監控模型）", style={"fontWeight": 500, "marginBottom": "8px"}),
            html.Div(style={"display": "flex", "gap": "8px", "flexWrap": "wrap", "alignItems": "center"}, children=[
                dcc.Input(id="np-name", type="text", placeholder="製程名稱（如 1號常壓蒸餾塔）", style={"width": "240px"}),
                dcc.Dropdown(id="np-dataset", clearable=False, value="synthetic",
                             options=[{"label": catalog.describe(d)["title"], "value": d} for d in demo.available_datasets()],
                             style={"width": "260px"}),
                dcc.Input(id="np-area", type="text", placeholder="區域（選填，如 常壓蒸餾）", style={"width": "180px"}),
                _btn("建立", "btn-np-create", primary=True, style={"padding": "6px 14px"}),
            ]),
            html.Div(id="np-status", style={"fontSize": "13px", "marginTop": "6px"}),
        ])]),
        html.Div(id="home-metrics", style={"margin": "16px 0"}),
        _LEGEND,
    ]


_STATUS = {"healthy": ("● 健康", _OK), "alarm": ("● 告警", _BAD), "placeholder": ("○ 待建模", "#b26a00"),
           "data_unavailable": ("○ 資料源不可得", "#888"), "unknown": ("○ 未知", "#888")}


def _mini_btn(label, idobj, *, primary=False):
    st = {"padding": "4px 10px", "fontSize": "12px", "borderRadius": "7px", "marginRight": "6px", "marginTop": "6px",
          "border": f"1px solid {_ACCENT}", "cursor": "pointer", "background": _ACCENT if primary else "#fff",
          "color": "#fff" if primary else _ACCENT}
    return html.Button(label, id=idobj, n_clicks=0, style=st)


def _asset_card(r):
    """單一製程卡（三態：綠健康／紅告警／黃待建模／灰不可得）+ 明確動作按鈕（避免整卡點擊與按鈕衝突）。"""
    txt, col = _STATUS.get(r["status"], _STATUS["unknown"])
    pid = r["process_id"]
    hp = (f"健康度 {r['health']}　v{r['version']}" if r["health"] is not None
          else ("尚未建立監控模型" if r["status"] == "placeholder" else "（資料源不可得，無法評分）"))
    ai = r.get("active_incidents", 0)
    acts = []
    if r["status"] in ("healthy", "alarm"):
        acts.append(_mini_btn("查看結果 →", {"type": "open-model", "pid": pid}, primary=True))
        acts.append(_mini_btn("更換模型", {"type": "build-cta", "pid": pid}))
    elif r["status"] == "placeholder":
        acts.append(_mini_btn("建立模型 →", {"type": "build-cta", "pid": pid}, primary=True))
    else:  # data_unavailable
        acts.append(_mini_btn("重建模型", {"type": "build-cta", "pid": pid}))
    acts.append(_mini_btn("歷史", {"type": "hist-cta", "pid": pid}))
    acts.append(_mini_btn("刪除", {"type": "del-proc", "pid": pid}))
    style = {"display": "inline-block", "width": "230px", "marginRight": "10px", "verticalAlign": "top",
             "border": f"1px solid {col if r['status'] == 'alarm' else '#e3e8ef'}",
             "borderRadius": "12px", "padding": "16px 18px", "background": "#fff"}
    return html.Div([
        html.Div(r["display_name"], style={"fontWeight": 500}),
        html.Div(f"資料源 {r['dataset']}", style={"color": "#94a3b8", "fontSize": "11px"}),
        html.Div(txt, style={"color": col, "fontSize": "14px", "margin": "4px 0"}),
        html.Div(hp, style={"color": "#51607a", "fontSize": "12px"}),
        html.Div(f"未結事件 {ai}" if ai else "", style={"color": _BAD, "fontSize": "12px"}),
        html.Div(acts),
    ], style=style)


@app.callback(Output("home-metrics", "children"), Input("screen", "data"), Input("events-refresh", "data"),
              Input("registry-refresh", "data"), Input("tick", "n_intervals"))
def _home_metrics(screen, _r, _rr, _t):
    pv = demo.assets_overview(_REGISTRY, _MODELS_DIR, incidents_path=_INCIDENTS)  # registry：含 placeholder，三態
    assets = pv["assets"]
    pcol = {"alarm": _BAD, "healthy": _OK, "empty": "#888"}[pv["plant_status"]]
    ptxt = {"alarm": "⚠ 有製程告警", "healthy": "✅ 全廠健康", "empty": "尚無監控中製程"}[pv["plant_status"]]
    banner = html.Div(f"全廠狀態：{ptxt}　·　{pv['n_monitored']} 監控中／{pv['n_alarm']} 告警／{pv['n_placeholder']} 待建模",
                      className="pg-flash" if pv["plant_status"] == "alarm" else "",  # 告警閃示（聲音替代，作業員）
                      style={"borderLeft": f"4px solid {pcol}", "background": "#f6f7f9", "padding": "10px 14px",
                             "color": pcol, "fontWeight": 500, "marginBottom": "12px"})
    tiles = html.Div(className="pg-grid", style={"display": "grid", "gridTemplateColumns": "repeat(3,1fr)", "gap": "12px"},
                     children=[_tile("監控中", str(pv["n_monitored"])), _tile("告警中", str(pv["n_alarm"])),
                               _tile("待建模", str(pv["n_placeholder"]))])
    if assets:
        blocks = []
        for area in pv["areas"]:  # 依區域分組（處長階層視圖）
            ac = _BAD if area["n_alarm"] else "#0f172a"
            blocks.append(html.Div([
                html.Div(f"區域：{area['area']}" + (f"（{area['n_alarm']} 告警）" if area["n_alarm"] else ""),
                         style={"fontWeight": 500, "margin": "10px 0 6px", "color": ac}),
                html.Div([_asset_card(r) for r in area["assets"]]),
            ]))
        note = html.Span() if pv["configured"] else html.Div(
            "（製程未設區域；新建製程時填「區域」欄即依 廠→區→製程 分組）",
            style={"color": "#888", "fontSize": "12px", "marginTop": "8px"})
        body = html.Div([html.Div("製程清單（待建模不計入綠紅健康燈）— 操作見各卡按鈕",
                                  style={"fontWeight": 500, "margin": "8px 0"}),
                         html.Div(blocks), note])
    else:
        body = html.Div("尚無製程。點右上「＋ 新建監控模型」走精靈直接建，或「＋ 新建製程」先佔名稍後熱插拔模型。",
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
                html.Div("① 選擇資料源並命名製程", style={"fontWeight": 500, "marginBottom": "8px"}),
                html.Div(id="wiz-bind-info", style={"fontSize": "13px", "marginBottom": "8px", "color": _ACCENT}),
                dcc.Input(id="wiz-name", type="text", placeholder="製程名稱（選填，預設用資料源標題）",
                          style={"width": "320px", "marginBottom": "8px", "display": "block"}),
                dcc.Dropdown(id="dataset", clearable=False, value="synthetic", style={"width": "380px"},
                             options=[{"label": catalog.describe(d)["title"], "value": d} for d in demo.available_datasets()]),
                html.Div(id="overview", style={"marginTop": "10px", "fontSize": "14px", "color": "#51607a"}),
                html.Div("監控的製程參數（預設全選；可只勾要監控的，例如 10 取 7；至少 2 個）：",
                         style={"fontWeight": 500, "marginTop": "12px", "marginBottom": "4px", "fontSize": "14px"}),
                dcc.Checklist(id="feature-sel", options=[], value=[], style={"fontSize": "13px"},
                              labelStyle={"display": "inline-block", "marginRight": "14px", "marginBottom": "2px"}),
                html.Div(id="feature-readout", style={"fontSize": "12px", "color": "#51607a", "marginTop": "4px"}),
            ]),
            html.Div(id="wp2", style={"display": "none"}, children=[
                html.Div("② 選擇訓練資料（黃金基準，代表 A 正常運轉）", style={"fontWeight": 500, "marginBottom": "8px"}),
                dcc.RadioItems(id="golden-mode", value="range", inline=True,
                               options=[{"label": " 連續區間", "value": "range"},
                                        {"label": " 勾選 campaign", "value": "segments"},
                                        {"label": " 自動挑乾淨段", "value": "auto"}],
                               style={"marginBottom": "8px", "fontSize": "13px"}),
                html.Div(id="gm-range", children=[
                    dcc.RangeSlider(id="golden-range", min=0, max=1500, value=[0, 600], allowCross=False,
                                    tooltip={"placement": "bottom", "always_visible": True}),
                ]),
                html.Div(id="gm-segments", style={"display": "none"}, children=[
                    html.Div("勾選代表「A 正常」的 campaign（可多選/非連續）：",
                             style={"fontSize": "13px", "color": "#51607a", "marginBottom": "4px"}),
                    dcc.Checklist(id="golden-segs", options=[], value=[],
                                  style={"fontSize": "13px"}, labelStyle={"display": "block", "margin": "2px 0"}),
                ]),
                html.Div(id="gm-auto", style={"display": "none"}, children=[
                    html.Div("系統用變點切段，自動挑最早的乾淨平穩段當基準（適合不確定該選哪段時）。",
                             style={"fontSize": "13px", "color": "#51607a"}),
                    _btn("套用自動挑選", "btn-auto-golden", style={"marginTop": "6px", "padding": "6px 14px"}),
                ]),
                html.Div(id="golden-readout", style={"fontSize": "13px", "color": _OK, "marginTop": "8px"}),
                html.Div("下圖：標準化偏離度（越高＝越偏離全域平均，用來看資料長相）；色帶＝campaign；綠框＝已選 golden。",
                         style={"fontSize": "12px", "color": "#94a3b8", "marginTop": "8px"}),
                dcc.Loading(dcc.Graph(id="golden-preview", config={"displayModeBar": False})),
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
        html.Div(style={"display": "flex", "alignItems": "center", "gap": "10px", "margin": "4px 0"}, children=[
            html.Span("告警門檻試算：", style={"fontSize": "13px", "color": "#51607a", "whiteSpace": "nowrap"}),
            html.Div(style={"flex": "1"}, children=[
                dcc.Slider(id="hi-thr", min=0.3, max=0.9, step=0.05, value=0.6,
                           marks={0.3: "0.3", 0.6: "0.6", 0.9: "0.9"}, tooltip={"placement": "bottom"},
                           updatemode="mouseup")]),
        ]),
        html.Div(id="thr-readout", style={"fontSize": "13px", "color": "#51607a", "marginBottom": "4px"}),
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
            html.Span("　處置記錄與原因填在各事件卡上再按「關閉」。", style={"fontSize": "12px", "color": "#888"}),
        ]),
        html.Div(style={"margin": "10px 0"}, children=[
            html.Label("每次非計畫停車損失（ROI 假設）：", style={"fontSize": "13px", "color": "#51607a"}),
            dcc.Input(id="roi-loss", type="number", value=1000000, step=100000, min=0,
                      style={"width": "160px", "marginLeft": "8px"}),
            html.Span("　元；ROI 為情境估算非實測。", style={"fontSize": "12px", "color": "#888"}),
        ]),
        html.Div(style={"margin": "10px 0"}, children=[
            html.Label("篩選狀態：", style={"fontSize": "13px", "color": "#51607a"}),
            dcc.Dropdown(id="evt-filter", value="all", clearable=False,
                         options=[{"label": "全部", "value": "all"}, {"label": "未結 open", "value": "open"},
                                  {"label": "處理中 ack", "value": "ack"}, {"label": "已關閉", "value": "closed"}],
                         style={"width": "160px", "display": "inline-block", "marginLeft": "8px", "verticalAlign": "middle"}),
        ]),
        dcc.Loading(html.Div(id="events-body")),
    ]


def _history_view():
    return [
        html.Div(style={"display": "flex", "justifyContent": "space-between", "alignItems": "center"}, children=[
            html.Div([html.H2("製程歷史 / 稽核", style={"margin": "0 0 4px", "fontWeight": 500}),
                      html.Div("模型版本、驗收快照、稽核 log、服役期事件（已軟刪除製程可在此還原）",
                               style={"color": "#51607a", "fontSize": "14px"})]),
            _btn("← 回總覽", "btn-hist-home"),
        ]),
        dcc.Loading(html.Div(id="history-body", style={"marginTop": "12px"})),
    ]


_SEG_STATS = ["mean", "std", "min", "max", "range", "median"]


def _segview_view():
    """段分析（可解釋視圖）：兩 step——① 段定義（method）② [參數×統計] 偏離視覺化。非告警（is_advisory）。"""
    return [
        html.Div(style={"display": "flex", "justifyContent": "space-between", "alignItems": "center"}, children=[
            html.Div([html.H2("段分析（可解釋視圖）", style={"margin": "0 0 4px", "fontWeight": 500}),
                      html.Div("穩態段定義 + [參數×統計] 偏離——可解釋／品質溝通，非告警",
                               style={"color": "#51607a", "fontSize": "14px"})]),
            _btn("← 回總覽", "btn-segview-home"),
        ]),
        html.Div("⚠ 此頁為可解釋視圖、非告警。逐參數段統計對「保邊際、破相關」型隱性飄移天生鈍——主訊號仍看健康指標(L2 "
                 "SPE)。偏離排序已做 Holm 多重比較校正；落在雜訊帶內＝統計上與 golden 無異，勿當告警依據。",
                 style={"background": "#fff7ed", "color": "#9a3412", "border": "1px solid #fed7aa",
                        "borderRadius": "10px", "padding": "10px 14px", "fontSize": "13px", "margin": "12px 0"}),
        _card([
            html.Div("① 段定義", style={"fontWeight": 500, "marginBottom": "8px"}),
            html.Div(style={"display": "flex", "gap": "20px", "flexWrap": "wrap", "alignItems": "center"}, children=[
                html.Div([html.Label("資料源：", style={"fontSize": "13px", "marginRight": "6px"}),
                          dcc.Dropdown(id="seg-dataset", clearable=False, value="synthetic", style={"width": "240px",
                                       "display": "inline-block", "verticalAlign": "middle"},
                                       options=[{"label": catalog.describe(d)["title"], "value": d}
                                                for d in demo.available_datasets()])]),
                html.Div([html.Label("分段法：", style={"fontSize": "13px", "marginRight": "6px"}),
                          dcc.RadioItems(id="seg-method", value="trim", inline=True,
                                         options=[{"label": " 去頭尾取中間 (trim)", "value": "trim"},
                                                  {"label": " 穩態偵測 (ssd)", "value": "ssd"},
                                                  {"label": " 小波高頻 (wavelet)", "value": "wavelet"}],
                                         style={"display": "inline-block", "fontSize": "13px"})]),
            ]),
            html.Div("② 選 [參數 × 統計]（比較 golden vs 比較區／drift 段）",
                     style={"fontWeight": 500, "margin": "14px 0 8px"}),
            html.Div("監控參數（預設全選）：", style={"fontSize": "13px", "color": "#51607a", "marginBottom": "4px"}),
            dcc.Checklist(id="seg-params", options=[], value=[], style={"fontSize": "13px"},
                          labelStyle={"display": "inline-block", "marginRight": "14px"}),
            html.Div("統計量（min/max/range 於段長接近 golden 時樣本不足→標 NaN，屬誠實邊界）：",
                     style={"fontSize": "13px", "color": "#51607a", "margin": "8px 0 4px"}),
            dcc.Checklist(id="seg-stats", value=_SEG_STATS,
                          options=[{"label": " " + s, "value": s} for s in _SEG_STATS],
                          style={"fontSize": "13px"}, labelStyle={"display": "inline-block", "marginRight": "14px"}),
            _btn("分析", "btn-segview-run", primary=True, style={"marginTop": "12px"}),
        ], style={"margin": "12px 0"}),
        dcc.Loading(html.Div(id="segview-status", style={"fontSize": "13px", "color": "#51607a", "margin": "8px 0"})),
        dcc.Loading(dcc.Graph(id="segview-fig", config={"displayModeBar": False})),
        dcc.Loading(html.Div(id="segview-table", style={"marginTop": "8px"})),
    ]


# 初始填入各屏內容（依 id 對應，避免索引脆弱）
_VIEWS = {"scr-home": _home_view, "scr-wizard": _wizard_view, "scr-results": _results_view,
          "scr-events": _events_view, "scr-history": _history_view, "scr-segview": _segview_view}
for _child in app.layout.children:
    if getattr(_child, "id", None) in _VIEWS:
        _child.children = _VIEWS[_child.id]()


# ---------- 路由與步進 ----------
@app.callback(Output("screen", "data"),
              Input("nav-home", "n_clicks"),
              Input("go-results", "n_clicks"), Input("btn-results-home", "n_clicks"),
              Input("nav-events", "n_clicks"), Input("btn-events-home", "n_clicks"),
              Input("btn-hist-home", "n_clicks"),
              Input("nav-segview", "n_clicks"), Input("btn-segview-home", "n_clicks"),
              prevent_initial_call=True)
def _route(*_):
    t = ctx.triggered_id
    return {"nav-home": "home", "btn-results-home": "home", "go-results": "results",
            "nav-events": "events", "btn-events-home": "home", "btn-hist-home": "home",
            "nav-segview": "segview", "btn-segview-home": "home"}.get(t, no_update)


@app.callback(Output("bundle-store", "data", allow_duplicate=True), Output("screen", "data", allow_duplicate=True),
              Input({"type": "open-model", "pid": ALL}, "n_clicks"), prevent_initial_call=True)
def _open_model(clicks):
    """點製程卡「查看結果」→ 載入該製程**現役模型** bundle（帶 dataset，供評分用正確資料源）+ 進結果頁。"""
    t = ctx.triggered_id
    if not t or not clicks or not any(c for c in clicks if c):
        return no_update, no_update
    store = AssetStore(_REGISTRY)
    cur = store.current_model(t["pid"])
    if cur is None:
        return no_update, no_update
    p = store.get_process(t["pid"])
    return ({"bundle_path": os.path.join(_MODELS_DIR, cur["path"]), "dataset": cur["dataset"],
             "process_id": t["pid"], "display_name": p["display_name"]}, "results")


@app.callback(Output("wiz-proc", "data"), Output("screen", "data", allow_duplicate=True),
              Output("wstep", "data", allow_duplicate=True),
              Input("btn-new", "n_clicks"), Input({"type": "build-cta", "pid": ALL}, "n_clicks"),
              prevent_initial_call=True)
def _enter_wizard(_new, _cta):
    """進精靈：btn-new＝全新製程（可命名/選源）；build-cta＝為既有製程建模/更換（資料源鎖定）。"""
    t = ctx.triggered_id
    if t == "btn-new":
        return {"mode": "new"}, "wizard", 1
    if not isinstance(t, dict) or not any(c for c in (_cta or []) if c):
        return no_update, no_update, no_update
    p = AssetStore(_REGISTRY).get_process(t["pid"])
    return ({"mode": "build", "process_id": t["pid"], "dataset": p["dataset"], "display_name": p["display_name"]},
            "wizard", 1)


@app.callback(Output("hist-proc", "data"), Output("screen", "data", allow_duplicate=True),
              Input({"type": "hist-cta", "pid": ALL}, "n_clicks"), prevent_initial_call=True)
def _enter_history(clicks):
    """點製程卡「歷史」→ 進歷史/稽核頁（含已軟刪除製程的還原入口）。"""
    t = ctx.triggered_id
    if not isinstance(t, dict) or not clicks or not any(c for c in clicks if c):
        return no_update, no_update
    return t["pid"], "history"


@app.callback(Output("wstep", "data"),
              Input("btn-next", "n_clicks"), Input("btn-back", "n_clicks"),
              State("wstep", "data"), prevent_initial_call=True)
def _wstep(_nx, _bk, cur):
    t = ctx.triggered_id
    if t == "btn-next":
        return min(len(_STEPS), (cur or 1) + 1)
    return max(1, (cur or 1) - 1)


@app.callback(Output("dataset", "value"), Output("dataset", "disabled"), Output("wiz-name", "style"),
              Output("wiz-bind-info", "children"), Input("wiz-proc", "data"), prevent_initial_call=True)
def _wiz_bind(wp):
    """精靈綁定：全新製程→可命名/自選源；為既有製程建模/更換→資料源鎖定、隱藏命名（重建基準語意）。"""
    name_show = {"width": "320px", "marginBottom": "8px", "display": "block"}
    if not wp or wp.get("mode") == "new":
        return no_update, False, name_show, "新製程：可命名並自選資料源（建立後即開始監控）。"
    return (wp["dataset"], True, {"display": "none"},
            f"為製程「{wp['display_name']}」建立／更換模型 · 資料源 {wp['dataset']}（鎖定）。"
            "更換＝以新黃金段重建基準，舊版自動轉為歷史版本。")


@app.callback(Output("scr-home", "style"), Output("scr-wizard", "style"), Output("scr-results", "style"),
              Output("scr-events", "style"), Output("scr-history", "style"), Output("scr-segview", "style"),
              Input("screen", "data"))
def _show_screen(screen):
    vis, hid = {"display": "block"}, {"display": "none"}
    return (vis if screen == "home" else hid, vis if screen == "wizard" else hid,
            vis if screen == "results" else hid, vis if screen == "events" else hid,
            vis if screen == "history" else hid, vis if screen == "segview" else hid)


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
              Output("golden-range", "marks"), Output("nrows", "data"), Output("window", "value"),
              Output("preview-store", "data"), Output("golden-segs", "options"), Output("golden-segs", "value"),
              Output("feature-sel", "options"), Output("feature-sel", "value"),
              Input("dataset", "value"))
def _on_dataset(name):
    cat = catalog.describe(name)  # item3：人話說明 + 推薦窗長（讓使用者點下一關就看到對應結果）
    try:
        ov = demo.dataset_overview(name)
        pv = demo.dataset_preview(name)  # golden 選擇視覺化資料
    except Exception as e:
        return html.Span(f"無法載入資料集：{e}", style={"color": _BAD}), 1500, [0, 600], {}, 1500, 60, None, [], [], [], []
    n = ov["n_rows"]
    g = ov["golden_suggested"] or [0, int(0.4 * n)]
    marks = {0: "0", n: str(n), n // 2: str(n // 2)}
    desc = html.Div([
        html.Div(cat["title"], style={"fontWeight": 500, "color": "#0f172a"}),
        html.Div(cat["blurb"], style={"margin": "2px 0 6px"}),
        html.Div(f"列數 {n}，變數 {ov['n_features']} 維，建議基準段 {ov['golden_suggested']}"
                 + (f"　·　軟量測標的：{cat['y_label']}" if cat["y_label"] else "　·　無 Y 軟量測"),
                 style={"color": "#51607a"}),
        html.Div("分段：" + "、".join(f"{s['label']}[{s['start']}:{s['end']}]" for s in ov["segments"]),
                 style={"color": "#94a3b8", "fontSize": "12px"}),
    ], style={"background": "#f6f7f9", "borderRadius": "8px", "padding": "10px 12px"})
    seg_opts = [{"label": f"{s['label']} [{s['start']}:{s['end']}]", "value": s["id"]} for s in pv["segments"]]
    gs, ge = g[0], g[1]  # 預設勾選與建議 golden 重疊的 campaign
    seg_val = [s["id"] for s in pv["segments"] if s["start"] < ge and s["end"] > gs]
    feat_opts = [{"label": c, "value": c} for c in ov["x_columns"]]  # 精確 X 欄名（可勾選監控子集）
    feat_val = list(ov["x_columns"])  # 預設全選
    return desc, n, g, marks, n, cat["default_window"], pv, seg_opts, seg_val, feat_opts, feat_val


@app.callback(Output("feature-readout", "children"), Input("feature-sel", "value"), State("feature-sel", "options"))
def _feature_readout(val, opts):
    n, mtot = len(val or []), len(opts or [])
    warn = "" if n >= 2 else "　⚠ 至少需 2 個監控參數"
    return f"已選 {n}/{mtot} 個參數監控{warn}"


def _golden_fig(pv, runs):
    """golden 選擇預覽圖：偏離度時間線 + campaign 色帶 + 已選 golden 綠框。"""
    xs, vs = pv["series_x"], pv["series_v"]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=xs, y=vs, mode="lines", line={"color": "#64748b", "width": 1},
                  hovertemplate="列 %{x}<br>偏離度 %{y} σ<extra></extra>"))
    band = ["rgba(99,102,241,0.06)", "rgba(234,88,12,0.06)"]
    for i, s in enumerate(pv["segments"]):  # campaign 色帶
        fig.add_vrect(x0=s["start"], x1=s["end"], fillcolor=band[i % 2], line_width=0,
                      annotation_text=s["label"], annotation_position="top left", annotation_font_size=10)
    for r in (runs or []):  # 已選 golden（綠框）
        fig.add_vrect(x0=r[0], x1=r[1], fillcolor="rgba(22,163,74,0.18)", line_width=1, line_color=_OK)
    ymax = (max(vs) * 1.1) if vs else 1
    fig.update_layout(height=240, margin={"l": 44, "r": 10, "t": 16, "b": 32}, showlegend=False,
                      xaxis={"title": "資料列索引"}, yaxis={"title": "偏離度 (σ)", "range": [0, ymax]})
    return fig


@app.callback(Output("gm-range", "style"), Output("gm-segments", "style"), Output("gm-auto", "style"),
              Input("golden-mode", "value"))
def _show_golden_mode(mode):
    vis, hid = {"display": "block"}, {"display": "none"}
    return (vis if mode == "range" else hid, vis if mode == "segments" else hid, vis if mode == "auto" else hid)


@app.callback(Output("golden-preview", "figure"), Output("golden-readout", "children"), Output("golden-spec", "data"),
              Input("golden-mode", "value"), Input("golden-range", "value"), Input("golden-segs", "value"),
              Input("auto-runs", "data"), Input("preview-store", "data"), prevent_initial_call=True)
def _golden_preview(mode, rng, segs, auto_runs, pv):
    """依選法重繪預覽 + 算選取摘要 + 產生 build 用 golden 規格（連續/勾選/自動）。"""
    if not pv:
        return no_update, no_update, no_update
    seg_by = {s["id"]: s for s in pv["segments"]}
    if mode == "segments":
        runs = sorted([[seg_by[i]["start"], seg_by[i]["end"]] for i in (segs or []) if i in seg_by])
        spec = {"segments": list(segs or [])}
        n_sel = sum(e - s for s, e in runs)
        readout = f"已勾選 {len(runs)} 段 campaign，共 {n_sel} 筆作為 golden" if runs else "⚠ 尚未勾選 campaign"
    elif mode == "auto":
        runs = (auto_runs or {}).get("runs", [])
        spec, n_sel = "auto", (auto_runs or {}).get("n_selected", 0)
        readout = f"自動挑選：{len(runs)} 段、共 {n_sel} 筆" if runs else "點「套用自動挑選」執行"
    else:  # range
        s, e = (rng or [0, 0])
        runs, spec = [[s, e]], {"range": [s, e]}
        readout = f"已選連續區間 [{s}:{e}]　約 {e - s} 筆"
    return _golden_fig(pv, runs), readout, spec


@app.callback(Output("auto-runs", "data"), Output("golden-mode", "value"),
              Input("btn-auto-golden", "n_clicks"), State("dataset", "value"), prevent_initial_call=True)
def _auto_golden(_n, name):
    """一鍵自動挑乾淨段（接後端 'auto' 變點切段）→ 疊圖 + 切到自動模式。"""
    try:
        r = demo.resolve_golden_runs(name, "auto")
    except Exception:
        r = {"runs": [], "n_selected": 0}
    return r, "auto"


# ---------- 建模 ----------
@app.callback(Output("bundle-store", "data"), Output("build-result", "children"),
              Output("registry-refresh", "data", allow_duplicate=True),
              Input("btn-build", "n_clicks"), State("wiz-proc", "data"), State("wiz-name", "value"),
              State("dataset", "value"), State("golden-spec", "data"), State("golden-range", "value"),
              State("window", "value"), State("feature-sel", "value"), State("feature-sel", "options"),
              prevent_initial_call=True)
def _build(_n, wp, wiz_name, name, gspec, grange, window, feats, feat_opts):
    """建立/更換模型（registry）：全新製程先建 placeholder 再建模；既有製程直接登錄新版本。FAIL gate 物理擋存檔。"""
    wp = wp or {"mode": "new"}
    at = _dt.datetime.now().astimezone().isoformat(timespec="seconds")
    golden = gspec or {"range": list(grange or [0, 600])}  # 連續/勾選/自動 規格；無則退回 RangeSlider 連續
    feats = feats or []
    if feats and len(feats) < 2:  # 子集至少 2（PCA 需求）——前端先擋，給友善訊息
        return no_update, html.Span("❌ 監控參數至少需選 2 個", style={"color": _BAD}), no_update
    all_feats = [o["value"] for o in (feat_opts or [])]
    features = None if (not feats or set(feats) == set(all_feats)) else feats  # 全選→None（全用）；子集→傳清單
    try:
        if wp.get("mode") == "build" and wp.get("process_id"):
            pid, dataset = wp["process_id"], wp["dataset"]
        else:  # 全新製程：選資料源即隱式建製程（item3 快路，不強制先建 placeholder）
            dataset = name
            disp = (wiz_name or "").strip() or catalog.describe(dataset)["title"]
            pid = demo.create_process(_REGISTRY, display_name=disp, dataset=dataset, at=at)["id"]
        r = demo.build_model_for_process(_REGISTRY, _MODELS_DIR, pid, golden=golden,
                                         window=int(window or 60), at=at, features=features)
    except Exception as e:
        return no_update, html.Span(f"❌ 建模失敗：{e}", style={"color": _BAD}), no_update
    acc = r.get("acceptance", {})
    recall_txt = (f"、事故 recall {acc['drift_recall']}" if acc.get("drift_recall") is not None else "")
    y_txt = (f"、Y 側品質誤報率 {acc['y_holdout_fpr']}" if acc.get("y_holdout_fpr") is not None else "")
    if not r["saved"]:  # X 或 Y 側誤報率過高 → 物理擋存檔（誤報治理；recall 低改走警告不擋）
        blk = "Y 側品質誤報率過高" if r.get("block_reason") == "y_fpr" else "誤報率過高"
        return no_update, html.Div([
            html.Div(f"⛔ {blk}，未存檔：" + acc.get("verdict", ""), style={"color": _BAD, "fontWeight": 500}),
            html.Div(f"hold-out golden 誤報率 {acc.get('holdout_golden_fpr')}{y_txt}{recall_txt}",
                     style={"fontSize": "13px", "color": "#51607a"}),
            html.Div("請改選更平穩的黃金期、或檢查資料源/軟測量後重建（會誤報的模型不予上線）。",
                     style={"fontSize": "13px", "color": "#51607a"}),
        ]), no_update
    m, mod = r["build"], r["model"]
    disp_name = AssetStore(_REGISTRY).get_process(pid)["display_name"]
    bundle = {"bundle_path": os.path.join(_MODELS_DIR, mod["path"]), "dataset": dataset,
              "process_id": pid, "display_name": disp_name}
    if acc.get("available"):
        acc_line = html.Div([
            html.Div("✅ 驗收通過：" + acc["verdict"], style={"color": _OK, "fontWeight": 500}),
            html.Div(f"hold-out golden 誤報率 {acc['holdout_golden_fpr']}"
                     f"（{'≤ 目標' if acc['fpr_ok'] else '過高'}）{y_txt}{recall_txt}",
                     style={"fontSize": "13px", "color": "#51607a"}),
            html.Div("（FPR 為前半 golden 模型的 out-of-sample 保守估計；部署用全 golden、資料更多通常更穩）",
                     style={"fontSize": "12px", "color": "#888"}),
        ])
    else:
        acc_line = html.Div(f"（驗收未跑：{acc.get('error', '資料不足')}）", style={"fontSize": "13px", "color": "#888"})
    # recall 低警告（多半因監控子集丟掉帶訊號的參數）——FPR 合格仍上線，但顯著標示偵測力下降（知情取捨）
    recall_warn = html.Span()
    if acc.get("available") and acc.get("recall_ok") is False:
        recall_warn = html.Div(
            f"⚠ 事故 recall 偏低（{acc.get('drift_recall')}）：此監控組合對已知 drift 偵測力下降，"
            "多因排除了帶飄移訊號的參數。FPR 合格故允許上線，建議補回關鍵參數或全參數監控。",
            style={"background": "#fff7ed", "border": "1px solid #fdba74", "color": "#b26a00",
                   "padding": "8px 12px", "borderRadius": "8px", "fontSize": "13px", "margin": "6px 0"})
    msg = html.Div([
        html.Div(f"✅ 模型已建立並存檔：{disp_name}（v{mod['version']}）", style={"color": _OK, "fontWeight": 500}),
        html.Div(f"golden {m['golden_range']}，{m['n_golden']} 樣本，監控 {len(m.get('x_columns', []))} 參數"
                 f"（{'、'.join(m.get('x_columns', [])[:6])}{'…' if len(m.get('x_columns', [])) > 6 else ''}）"
                 f"，指紋健康度 {m['fingerprint_hi']:.3f}"
                 + ("，含軟測量 Ŷ" if m.get("has_y_health") else ""), style={"fontSize": "13px", "color": "#51607a"}),
        acc_line,
        recall_warn,
        html.Div("按「下一關」查看健康指標。", style={"fontSize": "13px", "color": "#51607a", "marginTop": "4px"}),
    ])
    return bundle, msg, _dt.datetime.now().timestamp()


def _timeline_fig(pts, threshold):
    """健康時間線圖（共用：_run 初繪 + 門檻 slider 重繪）。threshold 控制門檻線位置（what-if）。"""
    xs = [p.get("ts") or p["start"] for p in pts]
    colors = [_REGION_COLOR[p["region"]] for p in pts]
    custom = [[p["spe_mean"], p["gsi_mean"], _REGION_ZH[p["region"]], p["start"], p["end"] - p["start"]]
              for p in pts]  # 末兩位 [start, win]：A20 下鑽用該點確切窗（=bundle.window 掃出）、非重算
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=xs, y=[p["health_index"] for p in pts], mode="lines+markers",
                  marker={"color": colors, "size": 9}, line={"color": "#999"}, name="健康指標", customdata=custom,
                  hovertemplate="時間 %{x}<br>健康度 %{y:.3f}<br>SPE %{customdata[0]}　GSI %{customdata[1]}<br>%{customdata[2]}<extra></extra>"))
    fig.add_trace(go.Scatter(x=xs, y=[p["confidence"] for p in pts], mode="lines",
                  line={"color": _CONF, "dash": "dot"}, name="可信度",
                  customdata=[[p["start"], p["end"] - p["start"]] for p in pts],  # A21+A20：帶 [start,win] 下鑽不錯位
                  hovertemplate="時間 %{x}<br>可信度 %{y:.3f}<extra></extra>"))
    al = [(p.get("ts") or p["start"], p["health_index"], p["start"], p["end"] - p["start"])
          for p in pts if p["persisted_alarm"]]
    if al:
        fig.add_trace(go.Scatter(x=[a[0] for a in al], y=[a[1] for a in al], mode="markers",
                      marker={"symbol": "x", "color": _BAD, "size": 14}, name="告警",
                      customdata=[[a[2], a[3]] for a in al]))  # 末兩位 [start, win]
    fig.add_hline(y=threshold, line_dash="dash", line_color="#888", annotation_text=f"門檻 {threshold}")
    fig.update_layout(yaxis={"title": "健康指標 (1=健康)", "range": [0, 1.05]},
                      xaxis={"title": "時間"}, height=420, legend={"orientation": "h"})
    return fig


# ---------- 結果（進入 results 屏時評分）----------
@app.callback(Output("run-status", "children"), Output("timeline", "figure"), Output("ymap", "figure"),
              Output("tl-store", "data"),
              Input("screen", "data"), State("bundle-store", "data"), State("dataset", "value"),
              State("window", "value"), prevent_initial_call=True)
def _run(screen, bundle, name, window):
    if screen != "results":
        return no_update, no_update, no_update, no_update
    if not bundle:
        return html.Span("⚠ 請先建立模型", style={"color": "#ef6c00"}), go.Figure(), go.Figure(), no_update
    name = bundle.get("dataset") or name      # 製程綁定的資料源（解耦後評分用 dataset，非 process_id）
    pid = bundle.get("process_id") or name    # incident 綁 process_id（解孤兒事件對齊）
    try:
        tl = demo.score_timeline(bundle["bundle_path"], name, window=None)  # A20：用 bundle.window 單一真相（非精靈輸入）
    except Exception as e:
        return html.Span(f"❌ 模擬失敗：{e}", style={"color": _BAD}), go.Figure(), go.Figure(), no_update
    pts = tl["points"]
    # 增量5：持續告警 → 開事件（同裝置防重複；reuse 已算 pts，不重複評分）。最嚴重窗取 RBC 首位當肇因。
    worst_top = None
    alarmed = [p for p in pts if p["persisted_alarm"]]
    if alarmed:
        worst = min(alarmed, key=lambda p: p["health_index"])
        n_bad = 0
        try:
            dd = demo.window_detail(bundle["bundle_path"], name, worst["start"], worst["end"], compute_fwer=False,
                                    tag_map=demo.tag_map_for(_MODELS_DIR, name))  # 事件肇因也顯 DCS 位號（紅隊現場工程師）
            worst_top = dd["rbc_ranking"][0][0] if dd.get("rbc_ranking") else "(見窗下鑽)"
            n_bad = sum(1 for k in ("L1", "L2", "L4") if dd.get("layers", {}).get(k, {}).get("unhealthy"))  # A19 層一致數
        except Exception:
            worst_top = "(見窗下鑽)"
        IncidentStore(_INCIDENTS).open_incident(product=pid, window=[worst["start"], worst["end"]],
            health=worst["health_index"], confidence=worst["confidence"], top_cause=worst_top,
            detected_at=worst.get("ts"), n_layers_consistent=n_bad)
    # 增量8：Y 側品質飄移持續告警 → 開「品質」事件（kind=quality，與製程事件分流不互壓；防重複）
    q_alarmed = [p for p in pts if p.get("y_quality_persisted")]
    if q_alarmed:
        qw = min(q_alarmed, key=lambda p: p["y_map_health"] if p.get("y_map_health") is not None else 1.0)
        mh = qw.get("y_map_health")
        qcause = ("品質飄移：X→Y 殘差超界（X 正常、實際 Y 偏，隱性）" if mh is not None
                  else "品質飄移：預測品質 Ŷ 水準偏移（純預測外推、窗內無實際 Y）")
        qd = demo.quality_incident_decision(qw)  # A14/A15：後端決策（純 Ŷ 不升 critical、不借 X confidence、去 magic 9）
        IncidentStore(_INCIDENTS).open_incident(product=pid, window=[qw["start"], qw["end"]], health=qd["health"],
            confidence=qd["confidence"], top_cause=qcause, detected_at=qw.get("ts"), kind="quality",
            severity=qd["severity"])
    xs = [p.get("ts") or p["start"] for p in pts]  # wall-clock（對齊 DCS/historian）；ymap 也用
    fig = _timeline_fig(pts, 0.6)
    ymap = go.Figure()
    if tl.get("has_y_mapping"):
        yhat = [p.get("yhat_mean") for p in pts]
        band = [p.get("yhat_band") or 0 for p in pts]
        up = [h + b for h, b in zip(yhat, band)]
        lo = [h - b for h, b in zip(yhat, band)]
        ymap.add_trace(go.Scatter(x=xs + xs[::-1], y=up + lo[::-1], fill="toself",
                       fillcolor="rgba(21,101,192,0.12)", line={"color": "rgba(0,0,0,0)"},
                       name="conformal 帶（近似覆蓋）", hoverinfo="skip"))
        ymap.add_trace(go.Scatter(x=xs, y=yhat, mode="lines", line={"color": _CONF}, name="Ŷ 軟測量預測"))
        ya = [(p.get("ts") or p["start"], p["y_actual_mean"]) for p in pts if p.get("y_actual_mean") is not None]
        if ya:
            ymap.add_trace(go.Scatter(x=[a[0] for a in ya], y=[a[1] for a in ya], mode="markers",
                           marker={"color": _BAD, "size": 6}, name="實際 Y（量測到達）"))
        gy = tl.get("golden_yhat_mean")  # 增量8：golden 期預測品質基準線（Ŷ 水準漂移的參考）
        if gy is not None:
            ymap.add_hline(y=gy, line_dash="dot", line_color=_OK, annotation_text="golden Ŷ 基準")
        qx = [(p.get("ts") or p["start"], p.get("yhat_mean")) for p in pts if p.get("y_quality_persisted")]
        if qx:  # 品質飄移告警窗標記（多一個維度監控）
            ymap.add_trace(go.Scatter(x=[a[0] for a in qx], y=[a[1] for a in qx], mode="markers",
                           marker={"symbol": "x", "color": _BAD, "size": 13}, name="品質飄移告警"))
        ymap.update_layout(title="L3 軟測量：Ŷ 預測 vs 實際 Y（帶外／✕＝品質飄移：X→Y 關係偏移或 Ŷ 水準漂移）",
                           xaxis={"title": "時間"}, yaxis={"title": "Y（軟量測標的）"},
                           height=300, legend={"orientation": "h"})
    else:
        ymap.update_layout(height=80, annotations=[{"text": "此模型無 Y 軟量測標的（不顯示映射子圖）",
                           "showarrow": False, "font": {"color": "#999"}}],
                           xaxis={"visible": False}, yaxis={"visible": False})
    n_alarm = tl["n_alarms"]
    title = bundle.get("display_name") or name
    msg = f"⚠ {title}：偵測到 {n_alarm} 個告警窗（製程關係偏移）" if n_alarm else f"✅ {title}：全程健康"
    note = (f"　·　⚠ 高維/長資料集已降採樣：僅 {tl['n_windows']} 窗、約 {tl.get('coverage_frac', 1) * 100:.0f}% 資料被評分，"
            "窗間空隙未評分（該段飄移可能漏抓）；要全覆蓋請縮小窗長或指定 max_windows"
            "　·　另：『連續 N 窗』為被抽樣窗、非物理相鄰，持續告警濾毛刺語義已改變、n_alarms 不可跨不同降採樣設定比較（A6）"
            if tl.get("subsampled") else "")
    # 粗→細中層：最嚴重窗摘要（① 健康指標總覽 → ② 為什麼超標 → ③ 點窗看製程參數）
    worst_line = html.Span()
    if alarmed:
        w = min(alarmed, key=lambda p: p["health_index"])
        worst_line = html.Div(f"② 最嚴重：窗 [{w['start']}:{w['end']}]　主因 {worst_top}　健康 {w['health_index']}"
                              f"　可信 {w['confidence']}（點下方時間線該紅點看完整肇因與製程參數）",
                              style={"color": _BAD, "fontSize": "13px", "fontWeight": 400, "marginTop": "4px"})
    # 增量8 ③ 品質維度（Y 側）：預測品質 Ŷ 偏移 / X→Y 殘差超界 → 防量產次級品
    q_line = html.Span()
    if tl.get("has_y_mapping"):
        n_quality = tl.get("n_quality_alarms", 0)
        n_unreliable = tl.get("n_quality_unreliable", 0)  # A13：Ŷ 外推、無實際 Y 可驗證的窗
        n_obs = sum(1 for p in pts if p.get("y_observed"))
        sparse = n_obs < max(1, len(pts)) * 0.5  # Y 量測稀疏 → 誠實標隱性飄移只在有 Y 樣本的窗可判
        if n_quality:
            qtxt = f"③ 品質維度：⚠ {n_quality} 個品質飄移窗（預測品質 Ŷ 偏移／X→Y 殘差超界）——恐量產次級品，建議查品質標的"
            qcol = _BAD
        else:
            qtxt = "③ 品質維度：✅ 預測品質穩定" + ("（Y 量測稀疏：隱性品質飄移僅在 Y 樣本到達的窗可判）" if sparse else "")
            qcol = _OK if not sparse else "#b26a00"
        if n_unreliable:  # A13：外推窗 Ŷ→prior mean 使 z 縮小 → 不可當「品質穩定」憑據，誠實標「不可信、改看 X 側」
            qtxt += (f"　⚠ 另有 {n_unreliable} 窗 Ŷ 外推（X 離建模域），Ŷ-drift 判讀不可信、"
                     "非真穩定，品質改看 X 側告警（A13）")
            qcol = "#b26a00" if qcol == _OK else qcol
        q_line = html.Div(qtxt, style={"color": qcol, "fontSize": "13px", "marginTop": "6px"})
    status = html.Div([
        html.Div("① 健康指標", style={"color": "#94a3b8", "fontSize": "12px"}),
        html.Span([html.Span(msg, style={"color": _BAD if n_alarm else _OK}),
                   html.Span(note, style={"color": "#888", "fontSize": "13px", "fontWeight": 400})]),
        worst_line,
        q_line,
    ])
    return status, fig, ymap, pts


@app.callback(Output("timeline", "figure", allow_duplicate=True), Output("thr-readout", "children"),
              Input("hi-thr", "value"), State("tl-store", "data"), prevent_initial_call=True)
def _recolor(thr, pts):
    """門檻 what-if：移動門檻線 + 算「此門檻下幾窗低於門檻」，不重新評分、不改模型實際告警（製程工程師調靈敏度）。"""
    if not pts:
        return no_update, ""
    n = sum(1 for p in pts if p["health_index"] < thr)
    return _timeline_fig(pts, thr), f"門檻 {thr} 試算：{n}/{len(pts)} 窗低於門檻（what-if，不改模型實際告警）"


@app.callback(Output("window-detail", "children"), Input("timeline", "clickData"), Input("role-sel", "value"),
              State("bundle-store", "data"), State("dataset", "value"), State("window", "value"),
              prevent_initial_call=True)
def _detail(click, role, bundle, name, window):
    if not bundle or not click:
        return ""
    name = bundle.get("dataset") or name  # 與 _run 一致：評分用製程綁定的資料源
    pt = click["points"][0]
    cd = pt.get("customdata")  # 末兩位 = [窗 start, 窗長 win]（x 軸已改 wall-clock，不能用 x 反推）
    # A21+A20：所有可點 trace（健康/可信/告警）均帶 [start,win]；缺失＝點到不可下鑽元素（如門檻線）→ 明確拒絕，
    # 不用脆弱退路 pointNumber×window（降採樣 step≠window 系統性錯位）。win 取自該點（=bundle.window 掃出的確切窗，
    # A20 單一真相），非重算 start+精靈窗長 → 下鑽窗與時間線窗一致。
    if not cd or len(cd) < 2:
        return html.Span("此處不可下鑽，請點「健康指標」曲線上的點或「告警」✕ 標記。",
                         style={"color": "#ef6c00", "fontSize": "13px"})
    start, win = int(cd[-2]), int(cd[-1])
    end = start + win
    try:
        d = demo.window_detail(bundle["bundle_path"], name, start, end, compute_fwer=True,
                               tag_map=demo.tag_map_for(_MODELS_DIR, name))
    except Exception as e:
        return html.Span(f"❌ 詳細指標載入失敗：{e}", style={"color": _BAD})
    mspc, pv = d["mspc"], (d["fwer_pvalues"] or {})
    rows = [html.Tr([html.Td(d["layers"][k]["name"]), html.Td(k),
                     html.Td("⚠" if d["layers"][k]["unhealthy"] else "✅"), html.Td(str(pv.get(k, "—"))),
                     html.Td(d["layers"][k]["action"], style={"color": "#51607a", "fontSize": "12px"})])
            for k in ("L1", "L2", "L4")]
    rbc_top = "、".join(f"{v}({s})" for v, s in d["rbc_ranking"][:5])
    rbc_note = "" if d.get("tag_mapped") else "（顯資料集欄名；現場 DCS 位號對照放 tags/{產品}.json 即自動套用）"
    ss = d.get("soft_sensor", {})
    if not ss.get("available"):
        ss_line = "軟測量（Ŷ / 可信度）：此模型無 Y 標的（未提供軟量測）。"
    elif ss.get("n_y_obs", 0) > 0:
        mh = ss.get("map_health")
        qflag = "　⚠ 品質飄移旗標：殘差超界（X 正常但實際 Y 偏，X→Y 關係斷）" if ss.get("y_flagged") else ""
        ss_line = (f"軟測量：Ŷ {ss['yhat_mean']}　實際 Y {ss['y_actual_mean']}　±帶 {ss['band_half_mean']}"
                   f"（{'conformal' if ss['cp_available'] else 'std 近似'}，{ss['n_y_obs']} 筆 Y）"
                   f"　X→Y 可信度：{mh if mh is not None else '觀測不足'}{qflag}")
    else:
        ss_line = "軟測量：本窗尚無 Y 到達（延遲量測）——待 Y 落地後給 Ŷ 與 X→Y 可信度。"
    v = d.get("verdict", {})
    vcol = {"ok": _OK, "warn": "#b26a00", "bad": _BAD}.get(v.get("tone"), "#51607a")
    top_var = d["rbc_ranking"][0][0] if d.get("rbc_ranking") else "(待查)"
    sop = (f"建議動作：現場確認「{top_var}」相關設備，必要時依 SOP 通報工程師（分機填於 SOP）。"
           if d["alarm"] else "建議動作：維持監看，無需處置。")  # 一行白話 SOP（作業員）
    if role == "operator":  # 作業員視圖：只給紅綠/可信/源頭/動作，藏 GSI/T²/SPE/p-value/Ŷ 等術語（漸進揭露）
        op_reason = {"bad": "警報可信，請依下方動作處理。",
                     "warn": "警報可信度偏低，先觀察、別急著動手，必要時通報工程師。",
                     "ok": "目前正常，維持監看。"}.get(v.get("tone"), "")  # 白話，不複用工程師術語 reason
        return _card([
            html.H5(f"窗 [{start}:{end}]　{'⚠ 異常' if d['alarm'] else '✅ 正常'}", style={"margin": "0 0 8px"}),
            html.Div([html.Span(v.get("label", ""), style={"fontWeight": 500, "fontSize": "16px"}),
                      html.Div("　" + op_reason, style={"marginTop": "2px"}),
                      html.Div(sop, style={"marginTop": "6px", "fontWeight": 500})],
                     style={"background": "#f6f7f9", "borderLeft": f"5px solid {vcol}", "padding": "10px 14px",
                            "color": vcol, "marginBottom": "8px"}),
            html.Div(f"可信度 {d['confidence']}（高＝此警報可信，低＝先觀察）", style={"marginBottom": "4px"}),
            html.Div(f"最可能源頭：{top_var}", style={"fontWeight": 500}),
            html.Div("（切換右上「工程師」可看完整統計指標與肇因排行）",
                     style={"color": "#888", "fontSize": "12px", "marginTop": "6px"}),
        ])
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
        html.Div([html.Span(f"RBC 肇因排行 (top5)：{rbc_top}"),
                  html.Span(rbc_note, style={"color": "#888", "fontSize": "12px"})], style={"marginTop": "8px"}),
        html.Div(ss_line, style={"marginTop": "6px", "color": _CONF}),
        html.Div(f"品質維度涵蓋：{ss.get('coverage')}" if ss.get("available") else "",
                 style={"color": "#888", "fontSize": "12px", "marginTop": "2px"}),  # 誠實揭露 map-only/含 dist
        html.Div(f"模型版本：{d['model_version']}", style={"color": "#888", "fontSize": "12px", "marginTop": "4px"}),
    ])


_SEV_COL = {"critical": _BAD, "warning": "#b26a00", "info": "#51607a"}


@app.callback(Output("events-body", "children"), Input("screen", "data"), Input("events-refresh", "data"),
              Input("tick", "n_intervals"), Input("roi-loss", "value"), Input("evt-filter", "value"))
def _events_body(screen, _r, _t, roi_loss, flt):
    if screen != "events":
        return no_update
    ov = demo.event_overview(_INCIDENTS, avg_loss_per_unplanned_stop=float(roi_loss or 1_000_000))
    st, roi, incs = ov["stats"], ov["roi"], ov["incidents"]
    mttr = st["mean_mttr_hr"]
    handover = html.Div(f"交接班摘要：未結 {st['open']}、處理中 {st['ack']}、已關閉 {st['closed']}、誤報 "
                        f"{st.get('false_alarm', 0)}｜平均 MTTR {('—' if mttr is None else str(mttr) + ' 小時')}",
                        style={"background": "#eef2ff", "color": _ACCENT, "padding": "8px 12px",
                               "borderRadius": "8px", "margin": "8px 0", "fontWeight": 500})
    if flt and flt != "all":  # 狀態篩選（現場工程師）——清單篩，KPI/ROI 仍全量
        incs = [it for it in incs if it["status"] == flt]
    tiles = html.Div(className="pg-grid", style={"display": "grid", "gridTemplateColumns": "repeat(5,1fr)",
                     "gap": "12px", "margin": "12px 0"},
                     children=[_tile("未結 open", str(st["open"])), _tile("處理中 ack", str(st["ack"])),
                               _tile("已關閉", str(st["closed"])), _tile("誤報", str(st.get("false_alarm", 0))),
                               _tile("平均 MTTR(小時)", "—" if mttr is None else str(mttr))])
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
                                      style={"width": "220px", "marginRight": "8px"}))
                acts.append(dcc.Dropdown(id={"type": "reason-inc", "id": it["id"]}, clearable=False, value="real",
                            options=[{"label": "真實處置", "value": "real"}, {"label": "誤報", "value": "false_alarm"},
                                     {"label": "已知忽略", "value": "ignore"}],
                            style={"width": "130px", "display": "inline-block", "marginRight": "8px", "verticalAlign": "middle"}))
                acts.append(_btn("關閉", {"type": "close-inc", "id": it["id"]}, primary=True, style={"padding": "5px 12px"}))
            mttr_line = f"MTTR {it['mttr_sec'] / 3600:.2f} 小時｜處置：{it.get('close_note')}" if it.get("mttr_sec") else ""
            kind = it.get("kind", "process")  # 增量8：品質 vs 製程 事件分流標籤
            ktxt, kcol = ("品質飄移", "#7c3aed") if kind == "quality" else ("製程異常", _ACCENT)
            nlc = it.get("n_layers_consistent", 0)  # A19：層一致數（多層一致＝可信告警，依此自動定級）
            layer_txt = f"｜{nlc} 層一致（依此自動定級）" if (kind == "process" and nlc) else ""
            cards.append(_card([
                html.Div([html.Span(it["id"] + "　", style={"fontWeight": 500}),
                          html.Span(ktxt, style={"background": kcol, "color": "#fff", "borderRadius": "6px",
                                    "padding": "1px 8px", "fontSize": "12px", "marginRight": "8px"}),
                          html.Span(it["severity"], style={"color": sev, "fontWeight": 500}),
                          html.Span("　" + it["status"], style={"color": "#51607a"})]),
                html.Div(f"{it['product']}｜肇因 {it['top_cause']}｜健康 {it['health']}｜可信 {it['confidence']}{layer_txt}｜{it['detected_at']}",
                         style={"fontSize": "13px", "color": "#51607a", "margin": "4px 0"}),
                html.Div(mttr_line, style={"fontSize": "12px", "color": "#888"}),
                html.Div(acts, style={"marginTop": "6px"}),
            ], style={"margin": "8px 0"}))
        body = html.Div(cards)
    return html.Div([handover, tiles, roi_card, body])


@app.callback(Output("events-refresh", "data"),
              Input({"type": "ack-inc", "id": ALL}, "n_clicks"), Input({"type": "close-inc", "id": ALL}, "n_clicks"),
              State({"type": "note-inc", "id": ALL}, "value"), State({"type": "reason-inc", "id": ALL}, "value"),
              State("event-actor", "value"), State("events-refresh", "data"), prevent_initial_call=True)
def _event_action(_a, _c, _notes, _reasons, actor, refresh):
    if not ctx.triggered or not ctx.triggered[0].get("value"):
        return no_update
    t = ctx.triggered_id
    if not isinstance(t, dict):
        return no_update
    actor = (actor or "").strip() or "未具名"  # 記入稽核軌跡（取代寫死「工程師」；真 auth 為 P2）
    store = IncidentStore(_INCIDENTS)

    def _by_id(group_idx, default=""):  # 依事件 id 取本案卡片的值（note/reason group）
        for st in ctx.states_list[group_idx]:
            if isinstance(st.get("id"), dict) and st["id"].get("id") == t["id"]:
                return st.get("value") or default
        return default

    try:
        if t["type"] == "ack-inc":
            store.ack(t["id"], by=actor)
        else:
            store.close(t["id"], note=_by_id(0) or "已處置", by=actor, reason=_by_id(1, "real"))
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
    name = bundle.get("dataset")
    fname = bundle.get("process_id") or name
    tl = demo.score_timeline(bundle["bundle_path"], name)
    return {"content": demo.timeline_to_csv(tl["points"]), "filename": f"{fname}_timeline.csv"}


# ---------- 新建製程 / 製程刪除 / 歷史頁（增量7）----------
@app.callback(Output("newproc-form", "style"), Input("btn-newproc", "n_clicks"),
              State("newproc-form", "style"), prevent_initial_call=True)
def _toggle_newproc(_n, st):
    """切換新建製程表單顯隱。"""
    shown = (st or {}).get("display") != "none"
    return {"display": "none" if shown else "block", "margin": "12px 0"}


@app.callback(Output("np-status", "children"), Output("registry-refresh", "data", allow_duplicate=True),
              Output("newproc-form", "style", allow_duplicate=True),
              Input("btn-np-create", "n_clicks"), State("np-name", "value"), State("np-dataset", "value"),
              State("np-area", "value"), prevent_initial_call=True)
def _np_create(_n, name, dataset, area):
    """建立 placeholder 製程（先佔名，稍後熱插拔模型）。"""
    nm = (name or "").strip()
    if not nm:
        return html.Span("請填製程名稱", style={"color": _BAD}), no_update, no_update
    at = _dt.datetime.now().astimezone().isoformat(timespec="seconds")
    try:
        p = demo.create_process(_REGISTRY, display_name=nm, dataset=dataset, at=at, area=(area or "").strip() or None)
    except Exception as e:
        return html.Span(f"建立失敗：{e}", style={"color": _BAD}), no_update, no_update
    return (html.Span(f"✅ 已建立製程「{p['display_name']}」（待建模）", style={"color": _OK}),
            _dt.datetime.now().timestamp(), {"display": "none", "margin": "12px 0"})


@app.callback(Output("registry-refresh", "data", allow_duplicate=True),
              Input({"type": "del-proc", "pid": ALL}, "n_clicks"), State("event-actor", "value"),
              prevent_initial_call=True)
def _del_proc(clicks, actor):
    """軟刪除製程（完全隱藏，只在歷史可見）+ 關閉孤兒事件。"""
    t = ctx.triggered_id
    if not isinstance(t, dict) or not clicks or not any(c for c in clicks if c):
        return no_update
    at = _dt.datetime.now().astimezone().isoformat(timespec="seconds")
    demo.delete_process(_REGISTRY, t["pid"], reason="使用者刪除", by=(actor or "").strip() or "未具名",
                        at=at, incidents_path=_INCIDENTS)
    return _dt.datetime.now().timestamp()


@app.callback(Output("history-body", "children"), Input("hist-proc", "data"), Input("registry-refresh", "data"),
              prevent_initial_call=True)
def _history_body(pid, _r):
    """製程歷史/稽核：版本清單（含 acceptance 快照）+ 稽核 log + 服役期事件；已刪製程給還原入口。"""
    if not pid:
        return ""
    try:
        h = demo.model_history(_REGISTRY, pid, incidents_path=_INCIDENTS)
    except Exception as e:
        return html.Span(f"❌ 載入歷史失敗：{e}", style={"color": _BAD})
    p = h["process"]
    cur = p.get("current_model_id")
    head = [html.H3(f"製程歷史：{p['display_name']}", style={"margin": "0 0 4px"}),
            html.Div(f"資料源 {p['dataset']}　·　狀態 {'已刪除' if p['deleted'] else '使用中'}"
                     f"　·　現役 {cur or '（無，待建模）'}", style={"color": "#51607a", "fontSize": "13px"})]
    if p["deleted"]:
        head.append(_btn("還原此製程", {"type": "restore-proc", "pid": pid}, primary=True, style={"marginTop": "8px"}))
    # 版本清單（含 acceptance 快照 + 是否現役 + 服役期事件數）
    inc_by = {}
    for it in h["incidents"]:
        inc_by[tuple(it.get("window", []))] = inc_by.get(tuple(it.get("window", [])), 0) + 1
    vrows = []
    for m in h["models"]:
        acc = m.get("acceptance") or {}
        accs = (f"驗收 {'PASS' if acc.get('passed') else 'FAIL'}（FPR {acc.get('holdout_golden_fpr')}"
                f"，recall {acc.get('drift_recall')}）") if acc else "（無驗收快照）"
        tag = "　← 現役" if m["id"] == cur else ("　（已刪）" if m["deleted"] else "")
        vrows.append(html.Tr([html.Td(f"v{m['version']}{tag}"), html.Td(str(m.get("golden_range"))),
                              html.Td(accs), html.Td(m["created_at"][:19]), html.Td(m.get("created_by", ""))]))
    vtable = html.Table([html.Thead(html.Tr([html.Th(x) for x in ("版本", "golden", "驗收快照", "建立時間", "建立者")])),
                        html.Tbody(vrows)], style={"width": "100%", "fontSize": "13px", "borderCollapse": "collapse",
                                                   "marginTop": "10px"})
    # 稽核 log（log存取）
    arows = [html.Tr([html.Td(a["at"][:19]), html.Td(a["actor"]), html.Td(a["action"]),
                      html.Td(a.get("detail", ""), style={"color": "#51607a"})]) for a in reversed(h["audit"])]
    atable = html.Table([html.Thead(html.Tr([html.Th(x) for x in ("時間", "操作者", "動作", "細節")])),
                        html.Tbody(arows)], style={"width": "100%", "fontSize": "12px", "borderCollapse": "collapse",
                                                   "marginTop": "10px"})
    return html.Div(head + [
        html.Div("模型版本（含驗收快照——判斷是否該回退）", style={"fontWeight": 500, "marginTop": "12px"}), vtable,
        html.Div(f"服役期事件：{len(h['incidents'])} 件", style={"fontSize": "13px", "color": "#51607a", "marginTop": "10px"}),
        html.Div("稽核 log（log 存取）", style={"fontWeight": 500, "marginTop": "12px"}), atable,
    ])


@app.callback(Output("registry-refresh", "data", allow_duplicate=True),
              Input({"type": "restore-proc", "pid": ALL}, "n_clicks"), State("event-actor", "value"),
              prevent_initial_call=True)
def _restore_proc(clicks, actor):
    """還原被軟刪除的製程（歷史頁入口）。"""
    t = ctx.triggered_id
    if not isinstance(t, dict) or not clicks or not any(c for c in clicks if c):
        return no_update
    at = _dt.datetime.now().astimezone().isoformat(timespec="seconds")
    demo.restore_process(_REGISTRY, t["pid"], by=(actor or "").strip() or "未具名", at=at)
    return _dt.datetime.now().timestamp()


# ---------- 段分析（可解釋視圖）----------
@app.callback(Output("seg-params", "options"), Output("seg-params", "value"), Input("seg-dataset", "value"))
def _segview_params(name):
    """依資料源填監控參數選項（預設全選）。"""
    try:
        cols = demo.dataset_overview(name)["x_columns"]
    except Exception:
        return [], []
    return [{"label": c, "value": c} for c in cols], cols


@app.callback(Output("segview-status", "children"), Output("segview-fig", "figure"), Output("segview-table", "children"),
              Input("btn-segview-run", "n_clicks"),
              State("seg-dataset", "value"), State("seg-method", "value"),
              State("seg-params", "value"), State("seg-stats", "value"), prevent_initial_call=True)
def _segview_run(_n, name, method, params, stats):
    """呼叫 demo.segment_view → trace 圖（golden/比較區段帶）+ [參數×統計] 偏離排序表（Holm，非告警）。"""
    if not params:
        return html.Span("⚠ 至少選 1 個監控參數", style={"color": "#ef6c00"}), go.Figure(), no_update
    import warnings as _w
    try:
        with _w.catch_warnings():
            _w.simplefilter("ignore")
            v = demo.segment_view(name, method=method, features=params, stats=stats or None)
    except Exception as e:
        return html.Span(f"❌ 分析失敗：{e}", style={"color": _BAD}), go.Figure(), no_update

    fig = go.Figure()
    shown = v["params"][:6]  # 限 6 條 trace 保可讀
    for p in shown:
        tr = v["traces"][p]
        fig.add_trace(go.Scatter(x=tr["x"], y=tr["v"], mode="lines", name=p, line={"width": 1}))
    for s, e in v["golden"]["runs"]:
        fig.add_vrect(x0=s, x1=e, fillcolor="rgba(16,185,129,0.10)", line_width=0)
    for s, e in v["query"]["segments"]:
        fig.add_vrect(x0=s, x1=e, fillcolor="rgba(99,102,241,0.12)", line_width=0)
    fig.update_layout(height=300, margin={"l": 44, "r": 10, "t": 30, "b": 28},
                      title=f"參數 trace（綠帶=golden、紫帶=比較區段；顯示前 {len(shown)}/{len(v['params'])} 參數）",
                      legend={"orientation": "h", "y": -0.22}, font={"size": 11})

    d = v["drift"]
    th = {"textAlign": "left", "padding": "4px 8px", "borderBottom": "2px solid #e3e8ef", "color": "#51607a"}
    td = {"padding": "4px 8px", "borderBottom": "1px solid #eef2ff"}
    head = html.Tr([html.Th(h, style=th) for h in ["參數", "統計", "段", "偏離 z", "Holm p", "判定"]])
    rows = []
    for c in d["cells"][:20]:
        if c["z"] is None:
            verdict, zt, pt = html.Span("樣本不足", style={"color": "#94a3b8"}), "—", "—"
        elif c["significant_holm"]:
            verdict = html.Span("偏離（Holm 顯著）", style={"color": _BAD, "fontWeight": 500})
            zt, pt = f"{c['z']:+.2f}", f"{c['p_raw']:.3f}"
        else:
            verdict = html.Span("雜訊內", style={"color": "#51607a"})
            zt, pt = f"{c['z']:+.2f}", f"{c['p_raw']:.3f}"
        seg = c["seg_global"]
        rows.append(html.Tr([html.Td(c["param"], style=td), html.Td(c["stat"], style=td),
                             html.Td(f"[{seg[0]},{seg[1]})" if seg else "—", style=td),
                             html.Td(zt, style=td), html.Td(pt, style=td), html.Td(verdict, style=td)]))
    table = html.Table([html.Thead(head), html.Tbody(rows)],
                       style={"width": "100%", "fontSize": "13px", "borderCollapse": "collapse"})
    status = html.Div([
        html.Div(v["note"], style={"marginBottom": "4px"}),
        html.Span(f"Holm 顯著 {d['n_significant']}/{d['n_comparisons']} 個 [參數×統計]；雜訊帶 z≈{d['chance_band_z']}；"
                  f"分段法 {v['method']}、{v['query']['n_segments']} 段（前 20 筆，依 |z| 排序）。",
                  style={"fontWeight": 500}),
    ])
    return status, fig, table


if __name__ == "__main__":
    app.run(debug=False, port=8051)
