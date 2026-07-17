"""#4 多產線健康總覽（北極星）：一屏看全部產線健康 → 點某線就地展開三部分
（線上即時記錄／告警歷史紀錄／模型建立詳細資訊），告警歷史下鑽到偏移的 X 參數或 Y 量測。

方案 B（使用者定調）：一條產線＝一個既有監控點(process/dataset)，per-line 健康沿用
``demo.assets_overview`` 已算好的三態燈（零資料層改動）；「線上即時記錄」用
``demo.score_timeline`` 離線逐窗充當 demo 即時視圖。真逐 machine_id rollup 留作後續 backlog
（machine_id 計分語意待使用者拍板）。本檔為**呈現殼**——計分邏輯全在已單元測試的
``health_index.deploy.demo``／``deploy.events``；UI 不含演算法（NOT VERIFIED-visual）。
"""

from __future__ import annotations

import plotly.graph_objects as go
from dash import ALL, Input, Output, State, ctx, dcc, html, no_update

from health_index.deploy import demo

_OK, _BAD, _CONF, _ACCENT = "#16a34a", "#dc2626", "#1565c0", "#4338ca"
_STATUS = {"healthy": ("● 健康", _OK), "alarm": ("● 告警", _BAD), "placeholder": ("○ 待建模", "#b26a00"),
           "data_unavailable": ("○ 資料源不可得", "#888"), "unknown": ("○ 未知", "#888")}
_UNAVAIL = {"placeholder": "尚未建立監控模型", "data_unavailable": "資料源不可得，無法評分"}


# ---------- 純函數（資料層，已測；callback 只是薄殼）----------
def fleet_overview(registry_path: str, models_dir: str, incidents_path: str, *, window: int = 60) -> dict:
    """逐產線健康總覽（方案 B：沿用 assets_overview 的三態燈，零新計分）。"""
    return demo.assets_overview(registry_path, models_dir, incidents_path=incidents_path, window=window)


def line_detail_data(registry_path: str, models_dir: str, incidents_path: str, process_id: str, *,
                     window: int = 60, max_windows: int = 60, overview: dict | None = None) -> dict:
    """單一產線三部分資料（全部綁該 process_id）：realtime／alarms／model_info。

    realtime＝score_timeline 逐窗健康（無現役模型→誠實標 unavailable，不杜撰）；
    alarms＝該線告警歷史（含 top_cause 下鑽肇因）；model_info＝版本/驗收/稽核。
    """
    ov = overview or fleet_overview(registry_path, models_dir, incidents_path, window=window)
    asset = next((a for a in ov["assets"] if a["process_id"] == process_id), None)
    history = demo.model_history(registry_path, process_id, incidents_path=incidents_path)
    alarms = history["incidents"]
    if asset is not None and asset["status"] in ("healthy", "alarm") and asset["bundle_path"]:
        tl = demo.score_timeline(asset["bundle_path"], asset["dataset"], window=window, max_windows=max_windows)
        realtime = {"points": tl["points"], "n_alarms": tl["n_alarms"], "window": tl["window"],
                    "has_y_mapping": tl["has_y_mapping"], "product": tl["product"],
                    "n_quality_alarms": tl.get("n_quality_alarms", 0),
                    "current_health": asset["health"], "current_status": asset["status"]}
    else:
        reason = "（找不到此產線）" if asset is None else _UNAVAIL.get(asset["status"], "（無現役模型）")
        realtime = {"unavailable": reason}
    return {"asset": asset, "realtime": realtime, "alarms": alarms, "model_info": history}


def realtime_figure(rt: dict) -> go.Figure:
    """線上即時健康記錄圖：逐窗健康折線，marker 依 persisted_alarm 上色（紅告警/綠健康）。"""
    fig = go.Figure()
    pts = rt.get("points", [])
    xs = list(range(1, len(pts) + 1))
    ys = [p["health_index"] for p in pts]
    colors = [_BAD if p["persisted_alarm"] else _OK for p in pts]
    custom = [[p["region"], p.get("spe_mean"), p.get("ts") or ""] for p in pts]
    fig.add_trace(go.Scatter(
        x=xs, y=ys, mode="lines+markers", name="健康指標",
        line={"color": "#999"}, marker={"color": colors, "size": 8}, customdata=custom,
        hovertemplate="窗 %{x}<br>健康度 %{y:.3f}<br>區段 %{customdata[0]}　SPE %{customdata[1]}"
                      "<br>%{customdata[2]}<extra></extra>"))
    fig.update_layout(margin={"l": 40, "r": 12, "t": 28, "b": 30}, height=240,
                      yaxis={"title": "健康指標 (1=健康)", "range": [0, 1.05]},
                      xaxis={"title": "時間窗（近＝右）"}, showlegend=False,
                      title={"text": "線上即時健康記錄", "font": {"size": 14}})
    return fig


# ---------- 呈現（layout-builds 驗證，視覺 NOT VERIFIED）----------
def _line_card(a: dict, selected: bool) -> html.Div:
    txt, col = _STATUS.get(a["status"], _STATUS["unknown"])
    hp = (f"健康度 {a['health']}　v{a['version']}" if a["health"] is not None
          else ("尚未建立監控模型" if a["status"] == "placeholder" else "（資料源不可得）"))
    ai = a.get("active_incidents", 0)
    border = _ACCENT if selected else (_BAD if a["status"] == "alarm" else "#e3e8ef")
    return html.Div([
        html.Div(a["display_name"], style={"fontWeight": 500}),
        html.Div(f"區域 {a['area'] or '未分區'}　·　資料源 {a['dataset']}",
                 style={"color": "#94a3b8", "fontSize": "11px"}),
        html.Div(txt, style={"color": col, "fontSize": "14px", "margin": "4px 0"}),
        html.Div(hp, style={"color": "#51607a", "fontSize": "12px"}),
        html.Div(f"未結事件 {ai}" if ai else "", style={"color": _BAD, "fontSize": "12px"}),
        html.Button("查看此產線 →", id={"type": "fleet-open", "pid": a["process_id"]}, n_clicks=0,
                    style={"marginTop": "6px", "padding": "4px 10px", "fontSize": "12px", "borderRadius": "7px",
                           "border": f"1px solid {_ACCENT}", "cursor": "pointer",
                           "background": _ACCENT if selected else "#fff", "color": "#fff" if selected else _ACCENT}),
    ], style={"display": "inline-block", "width": "230px", "marginRight": "10px", "marginBottom": "10px",
              "verticalAlign": "top", "border": f"1px solid {border}", "borderWidth": "2px" if selected else "1px",
              "borderRadius": "12px", "padding": "14px 16px", "background": "#fff"})


def line_cards(overview: dict, selected_pid: str | None = None) -> list:
    """逐產線卡片（總覽格）+ 全廠健康 banner。無產線→引導文案。"""
    assets = overview["assets"]
    pcol = {"alarm": _BAD, "healthy": _OK, "empty": "#888"}[overview["plant_status"]]
    ptxt = {"alarm": "⚠ 有產線告警", "healthy": "✅ 全部產線健康", "empty": "尚無監控中產線"}[overview["plant_status"]]
    banner = html.Div(f"全廠：{ptxt}　·　{overview['n_monitored']} 監控中／{overview['n_alarm']} 告警／"
                      f"{overview['n_placeholder']} 待建模",
                      className="pg-flash" if overview["plant_status"] == "alarm" else "",
                      style={"borderLeft": f"4px solid {pcol}", "background": "#f6f7f9", "padding": "10px 14px",
                             "color": pcol, "fontWeight": 500, "marginBottom": "12px"})
    if not assets:
        return [banner, html.Div("尚無產線。到「總覽」新建製程/監控模型後即出現在此。",
                                 style={"color": "#51607a", "background": "#f6f7f9", "padding": "14px",
                                        "borderRadius": "10px"})]
    return [banner, html.Div([_line_card(a, a["process_id"] == selected_pid) for a in assets])]


def _section(title: str, body) -> html.Div:
    return html.Div([html.Div(title, style={"fontWeight": 500, "margin": "12px 0 6px", "fontSize": "15px"}), body],
                    style={"borderTop": "1px solid #eef0f4", "paddingTop": "8px"})


def _realtime_view(rt: dict) -> html.Div:
    if "unavailable" in rt:
        return html.Div(f"（無即時記錄：{rt['unavailable']}）",
                        style={"color": "#51607a", "background": "#f6f7f9", "padding": "10px 14px", "borderRadius": "8px"})
    _t, col = _STATUS.get(rt["current_status"], _STATUS["unknown"])
    head = html.Div(f"目前 {_t}　健康度 {rt['current_health']}　·　近 {len(rt['points'])} 窗、"
                    f"{rt['n_alarms']} 告警窗" + (f"、{rt['n_quality_alarms']} 品質飄移窗" if rt["has_y_mapping"] else ""),
                    style={"color": col, "fontSize": "13px", "marginBottom": "4px"})
    return html.Div([head, dcc.Graph(figure=realtime_figure(rt), config={"displayModeBar": False})])


def _alarm_history_view(alarms: list) -> html.Div:
    if not alarms:
        return html.Div("此產線服役期間尚無告警。", style={"color": "#51607a", "fontSize": "13px"})
    rows = []
    for it in sorted(alarms, key=lambda x: x.get("detected_at", ""), reverse=True):
        kind = it.get("kind", "process")
        ktxt, kcol = ("品質飄移（Y 量測）", "#7c3aed") if kind == "quality" else ("製程異常（X 參數）", _ACCENT)
        cause = it.get("top_cause") or "—"
        rows.append(html.Div([
            html.Span(it["id"] + "　", style={"fontWeight": 500}),
            html.Span(ktxt, style={"background": kcol, "color": "#fff", "borderRadius": "6px",
                                   "padding": "1px 8px", "fontSize": "12px", "marginRight": "8px"}),
            html.Span(f"{it['status']}　", style={"color": "#51607a", "fontSize": "12px"}),
            # 下鑽肇因：偏移的 X 參數或 Y 量測（本畫面存在的理由）
            html.Span(f"偏移肇因 {cause}", style={"color": _BAD, "fontWeight": 500, "fontSize": "13px"}),
            html.Div(f"健康 {it['health']}｜可信 {it['confidence']}｜{it.get('detected_at', '')[:19]}",
                     style={"color": "#51607a", "fontSize": "12px", "marginTop": "2px"}),
        ], style={"borderBottom": "1px solid #f0f2f6", "padding": "6px 0"}))
    return html.Div(rows)


def _model_info_view(history: dict) -> html.Div:
    p = history["process"]
    cur = p.get("current_model_id")
    models = history.get("models", [])
    cm = next((m for m in models if m["id"] == cur), models[-1] if models else None)
    lines = [html.Div(f"資料源 {p['dataset']}　·　現役 {cur or '（無，待建模）'}　·　共 {len(models)} 個版本",
                      style={"fontSize": "13px", "color": "#51607a"})]
    if cm is not None:
        acc = cm.get("acceptance") or {}
        accs = (f"驗收 {'PASS' if acc.get('passed') else 'FAIL'}（FPR {acc.get('holdout_golden_fpr')}"
                f"，recall {acc.get('drift_recall')}）") if acc else "（無驗收快照）"
        lines.append(html.Div(f"現役 v{cm['version']}｜golden {cm.get('golden_range')}｜{accs}｜"
                              f"建於 {cm['created_at'][:19]}　{cm.get('created_by', '')}",
                              style={"fontSize": "13px", "marginTop": "4px"}))
    lines.append(html.Div(f"服役期事件 {len(history.get('incidents', []))} 件　·　稽核 log "
                          f"{len(history.get('audit', []))} 筆", style={"fontSize": "12px", "color": "#94a3b8",
                                                                        "marginTop": "4px"}))
    return html.Div(lines)


def detail_panel(detail: dict) -> html.Div:
    """單一產線就地展開的三部分面板（即時記錄／告警歷史／模型資訊）。"""
    name = detail["model_info"]["process"]["display_name"]
    return html.Div([
        html.Div(f"產線：{name}", style={"fontWeight": 500, "fontSize": "16px", "marginBottom": "4px"}),
        _section("① 線上即時記錄", _realtime_view(detail["realtime"])),
        _section("② 告警歷史紀錄（點肇因看偏移的參數／量測）", _alarm_history_view(detail["alarms"])),
        _section("③ 模型建立詳細資訊", _model_info_view(detail["model_info"])),
    ], style={"border": "1px solid #e3e8ef", "borderRadius": "12px", "padding": "16px 18px",
              "background": "#fff", "marginTop": "8px"})


def layout() -> list:
    """scr-fleet 內容殼（比照 batch_wizard：inline 掛入 demo_app，不走 _VIEWS）。"""
    return [
        dcc.Store(id="fleet-line"),  # 目前選取的產線 process_id
        html.Div(style={"display": "flex", "justifyContent": "space-between", "alignItems": "flex-start"}, children=[
            html.Div([html.H2("產線總覽", style={"margin": "0 0 4px", "fontWeight": 500}),
                      html.Div("各產線健康一屏綜覽　→　點產線就地展開即時記錄／告警歷史／模型資訊",
                               style={"color": "#51607a", "fontSize": "14px"})]),
            html.Button("← 回總覽", id="btn-fleet-home", n_clicks=0,
                        style={"padding": "9px 18px", "borderRadius": "9px", "border": f"1px solid {_ACCENT}",
                               "cursor": "pointer", "background": "#fff", "color": _ACCENT, "fontWeight": 500}),
        ]),
        html.Div(id="fleet-metrics", style={"margin": "14px 0"}),
        html.Div(id="fleet-detail"),
    ]


def register(app, *, registry_path: str, models_dir: str, incidents_path: str) -> None:
    """把產線總覽 callbacks 掛上 app（demo_app 呼叫，傳入單一真相的 registry 路徑）。"""

    @app.callback(Output("fleet-metrics", "children"),
                  Input("screen", "data"), Input("fleet-line", "data"),
                  Input("registry-refresh", "data"), Input("events-refresh", "data"), Input("tick", "n_intervals"))
    def _fleet_metrics(screen, selected, _r, _e, _t):
        if screen != "fleet":  # 僅在本屏計算，避免每 tick 重評全廠
            return no_update
        ov = fleet_overview(registry_path, models_dir, incidents_path)
        return line_cards(ov, selected)

    @app.callback(Output("fleet-line", "data"),
                  Input({"type": "fleet-open", "pid": ALL}, "n_clicks"), prevent_initial_call=True)
    def _fleet_select(clicks):
        t = ctx.triggered_id
        if not isinstance(t, dict) or not clicks or not any(c for c in clicks if c):
            return no_update
        return t["pid"]

    @app.callback(Output("fleet-detail", "children"),
                  Input("fleet-line", "data"), Input("events-refresh", "data"), Input("tick", "n_intervals"),
                  State("screen", "data"), prevent_initial_call=True)
    def _fleet_detail(pid, _e, _t, screen):
        if not pid:
            return html.Div("點上方任一產線 → 查看即時記錄／告警歷史／模型資訊。",
                            style={"color": "#51607a", "background": "#f6f7f9", "padding": "14px",
                                   "borderRadius": "10px", "marginTop": "8px"})
        if ctx.triggered_id in ("tick", "events-refresh") and screen != "fleet":
            return no_update  # 非本屏的定時刷新不重算
        try:
            d = line_detail_data(registry_path, models_dir, incidents_path, pid)
        except Exception as e:  # 誠實降級，不吞錯
            return html.Div(f"❌ 載入產線失敗：{e}", style={"color": _BAD})
        return detail_panel(d)
