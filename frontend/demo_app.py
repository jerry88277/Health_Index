"""線上模擬 Demo UI（4 步 wizard）：選定資料範圍 → 建立模型 → 確認模擬資料 → 查看健康指標。

瓶子優先（docs/deployment_plan.md）：公開資料集線上模擬，PI 為 stub。本檔為**呈現殼**——所有邏輯在
已單元測試的 ``health_index.deploy.demo``；UI 不含演算法。舊 frontend/app.py 作廢，本檔為新 demo 入口。

啟動：``python -m frontend.demo_app``（或 PYTHONPATH=src python frontend/demo_app.py），開 http://127.0.0.1:8051
注意：UI 視覺未在本環境實際渲染驗證（NOT VERIFIED-visual）；orchestration 邏輯由 tests/test_demo.py 驗證。
"""

from __future__ import annotations

import datetime as _dt
import os
import tempfile

import plotly.graph_objects as go
from dash import Dash, Input, Output, State, dcc, html

from health_index.deploy import demo

_MODELS_DIR = os.path.join(tempfile.gettempdir(), "health_index_demo_models")
_REGION_COLOR = {"golden": "#2e7d32", "clean_reentry": "#66bb6a", "drift": "#c62828", "other": "#ef6c00"}
_REGION_ZH = {"golden": "黃金基準", "clean_reentry": "乾淨回歸", "drift": "殘留飄移", "other": "換產品/其他"}

app = Dash(__name__, title="Health Index 線上模擬 Demo")


def _card(children):
    return html.Div(children, style={"border": "1px solid #ddd", "borderRadius": "8px", "padding": "16px", "margin": "10px 0"})


app.layout = html.Div(
    style={"maxWidth": "1000px", "margin": "0 auto", "fontFamily": "system-ui, sans-serif", "padding": "20px"},
    children=[
        html.H2("製程健康度 — 線上模擬 Demo"),
        html.P("公開資料集模擬產線即時資料流；PI 介接為 stub，之後換真酒。", style={"color": "#666"}),
        dcc.Store(id="bundle-store"),
        # 步驟1：選定資料範圍
        _card([
            html.H4("① 選定資料範圍"),
            dcc.Dropdown(id="dataset", options=[{"label": d, "value": d} for d in demo.available_datasets()], value="synthetic", clearable=False, style={"width": "320px"}),
            html.Div(id="overview", style={"marginTop": "10px", "fontSize": "14px"}),
            html.Label("Golden 範圍（建模基準）：", style={"marginTop": "10px", "display": "block"}),
            dcc.RadioItems(id="golden-mode", options=[{"label": " 使用真值建議段", "value": "suggested"}, {"label": " 自動挑選最早乾淨平穩段 (auto)", "value": "auto"}], value="suggested"),
        ]),
        # 步驟2：建立模型
        _card([
            html.H4("② 建立模型"),
            html.Button("建立模型", id="btn-build", n_clicks=0, style={"padding": "8px 16px"}),
            html.Div(id="build-result", style={"marginTop": "10px", "fontSize": "14px"}),
        ]),
        # 步驟3：確認模擬資料
        _card([
            html.H4("③ 確認模擬資料"),
            html.Label("評分窗長："),
            dcc.Input(id="window", type="number", value=60, min=10, step=10, style={"width": "100px"}),
            html.Button("預覽將重放的資料", id="btn-preview", n_clicks=0, style={"padding": "8px 16px", "marginLeft": "10px"}),
            html.Div(id="preview-result", style={"marginTop": "10px", "fontSize": "14px"}),
        ]),
        # 步驟4：查看健康指標
        _card([
            html.H4("④ 查看健康指標"),
            html.Button("執行線上模擬", id="btn-run", n_clicks=0, style={"padding": "8px 16px", "fontWeight": "bold"}),
            dcc.Loading(html.Div(id="run-status", style={"marginTop": "10px", "fontSize": "18px", "fontWeight": "bold"})),
            dcc.Loading(dcc.Graph(id="timeline")),
        ]),
    ],
)


@app.callback(Output("overview", "children"), Input("dataset", "value"))
def _show_overview(name):
    try:
        ov = demo.dataset_overview(name)
    except Exception as e:  # 資料缺/建構失敗 → 人話
        return html.Span(f"無法載入資料集：{e}", style={"color": "#c62828"})
    segs = "、".join(f"{s['label']}[{s['start']}:{s['end']}]" for s in ov["segments"])
    return html.Div([
        html.Div(f"列數 {ov['n_rows']}，變數 {ov['n_features']} 維，建議 golden 段 {ov['golden_suggested']}"),
        html.Div(f"分段：{segs}", style={"color": "#666"}),
    ])


@app.callback(
    Output("bundle-store", "data"), Output("build-result", "children"),
    Input("btn-build", "n_clicks"),
    State("dataset", "value"), State("golden-mode", "value"),
    prevent_initial_call=True,
)
def _build(_n, name, mode):
    try:
        golden = "auto" if mode == "auto" else None  # None→真值建議段
        m = demo.build_and_save_model(name, golden=golden, models_dir=_MODELS_DIR, created_at=_dt.datetime.now().isoformat())
        msg = html.Span(f"✅ 模型已建立並存檔：{m['product']}（golden {m['golden_range']}，{m['n_golden']} 樣本，指紋健康度 {m['fingerprint_hi']:.3f}）", style={"color": "#2e7d32"})
        return m, msg
    except Exception as e:
        return None, html.Span(f"❌ 建模失敗：{e}", style={"color": "#c62828"})


@app.callback(
    Output("preview-result", "children"),
    Input("btn-preview", "n_clicks"),
    State("dataset", "value"), State("window", "value"),
    prevent_initial_call=True,
)
def _preview(_n, name, window):
    try:
        pv = demo.replay_preview(name, window=int(window))
        return html.Span(f"將重放 {pv['n_rows']} 列為 ~{pv['n_windows_est']} 個窗（窗長 {pv['window']}）；含已知飄移真值：{'是' if pv['has_labeled_drift'] else '否'}。確認後按 ④ 執行。")
    except Exception as e:
        return html.Span(f"❌ 預覽失敗：{e}", style={"color": "#c62828"})


@app.callback(
    Output("run-status", "children"), Output("timeline", "figure"),
    Input("btn-run", "n_clicks"),
    State("bundle-store", "data"), State("dataset", "value"), State("window", "value"),
    prevent_initial_call=True,
)
def _run(_n, bundle, name, window):
    if not bundle:
        return html.Span("⚠ 請先在 ② 建立模型", style={"color": "#ef6c00"}), go.Figure()
    try:
        tl = demo.score_timeline(bundle["bundle_path"], name, window=int(window))
    except Exception as e:
        return html.Span(f"❌ 模擬失敗：{e}", style={"color": "#c62828"}), go.Figure()
    pts = tl["points"]
    xs = [p["start"] for p in pts]
    his = [p["health_index"] for p in pts]
    colors = [_REGION_COLOR[p["region"]] for p in pts]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=xs, y=his, mode="lines+markers", marker={"color": colors, "size": 9}, line={"color": "#999"}, name="健康指標"))
    # 告警標記
    al = [(p["start"], p["health_index"]) for p in pts if p["persisted_alarm"]]
    if al:
        fig.add_trace(go.Scatter(x=[a[0] for a in al], y=[a[1] for a in al], mode="markers", marker={"symbol": "x", "color": "#c62828", "size": 14}, name="告警"))
    fig.add_hline(y=0.6, line_dash="dash", line_color="#888", annotation_text="告警門檻 0.6")
    fig.update_layout(yaxis={"title": "健康指標 (1=健康)", "range": [0, 1.05]}, xaxis={"title": "時間（樣本索引）"}, height=420, legend={"orientation": "h"})
    n_alarm = tl["n_alarms"]
    status = html.Span(f"{'⚠ 偵測到 ' + str(n_alarm) + ' 個告警窗（製程關係偏移）' if n_alarm else '✅ 全程健康'}", style={"color": "#c62828" if n_alarm else "#2e7d32"})
    return status, fig


if __name__ == "__main__":
    app.run(debug=False, port=8051)
