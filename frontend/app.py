"""Plotly Dash 前端：經 REST 取後端 /analyze 結果，視覺化 per-campaign Health Index。

啟動（地端）：``python frontend/app.py``（預設 :8050，後端 :8000）。
視覺化：Health Index per-campaign 長條（紅=告警, *=re-entry）+ 各層健康子分數。

範圍誠實標記（Rule 12）：per-sample 時間軸（T²/SPE/GSI）、Ŷ vs Y、RBC 肇因 需後端
``/analyze/{job}/health`` 與 ``/contribution`` 端點（M-later），本 MVP 先呈現 campaign 級彙總。
圖表建構為純函式（``build_*_figure``），可不啟動伺服器/後端被 pytest 驗證。
"""

from __future__ import annotations

import httpx
import plotly.graph_objects as go
from dash import Dash, Input, Output, State, dcc, html

from health_index.config import DEFAULT

DEFAULT_API = "http://127.0.0.1:8000"
ALARM = "crimson"
OK = "seagreen"


def fetch_analysis(
    base_url: str | None,
    *,
    dataset_id: str = "synthetic",
    seed: int = 5,
    drift_strength: float = 1.2,
    client=None,
) -> dict:
    """取後端 /analyze 結果。client（測試注入 TestClient）優先於 base_url。"""
    payload = {"dataset_id": dataset_id, "seed": int(seed), "drift_strength": float(drift_strength)}
    resp = client.post("/analyze", json=payload) if client is not None else httpx.post(
        f"{base_url}/analyze", json=payload, timeout=120
    )
    resp.raise_for_status()
    return resp.json()


def _label(c: dict) -> str:
    return f"C{c['campaign_id']}·{c['grade']}" + ("*" if c["is_reentry"] else "")


def build_health_figure(analysis: dict, *, threshold: float = DEFAULT.hi_alarm_threshold) -> go.Figure:
    """per-campaign Health Index 長條（紅=告警/綠=健康，標告警門檻）。"""
    camps = analysis["campaigns"]
    colors = [ALARM if c["is_alarm"] else OK for c in camps]
    fig = go.Figure(
        go.Bar(
            x=[_label(c) for c in camps],
            y=[c["health_index"] for c in camps],
            marker_color=colors,
            text=[f"{c['health_index']:.2f}" for c in camps],
            textposition="outside",
        )
    )
    fig.add_hline(y=threshold, line_dash="dash", annotation_text=f"告警門檻 {threshold}")
    fig.update_layout(
        title="Health Index per campaign（紅=告警, *=re-entry）",
        yaxis=dict(range=[0, 1.05], title="Health Index（1=健康）"),
    )
    return fig


def build_subscore_figure(analysis: dict) -> go.Figure:
    """各層（L1/L2/L4）健康子分數分組長條。"""
    camps = analysis["campaigns"]
    x = [_label(c) for c in camps]
    fig = go.Figure()
    for layer in ("L1", "L2", "L4"):
        fig.add_bar(name=layer, x=x, y=[c["subscores"][layer] for c in camps])
    fig.update_layout(barmode="group", title="各層健康子分數（1=健康）", yaxis=dict(range=[0, 1.05]))
    return fig


def create_app(base_url: str = DEFAULT_API) -> Dash:
    """建立 Dash app（控制列 + 兩張圖 + 狀態列）。"""
    app = Dash(__name__, title="Health_Index")
    app.layout = html.Div(
        [
            html.H2("Health_Index — 隱性飄移健康度"),
            html.Div(
                [
                    dcc.Dropdown(
                        id="dataset",
                        options=[{"label": "synthetic", "value": "synthetic"}],
                        value="synthetic",
                        style={"width": "200px"},
                    ),
                    dcc.Input(id="seed", type="number", value=5, min=0, step=1),
                    dcc.Input(id="drift", type="number", value=1.2, min=0.01, step=0.1),
                    html.Button("分析", id="run", n_clicks=0),
                ],
                style={"display": "flex", "gap": "10px"},
            ),
            html.Div(id="status"),
            dcc.Graph(id="health-graph"),
            dcc.Graph(id="subscore-graph"),
        ]
    )

    @app.callback(
        Output("health-graph", "figure"),
        Output("subscore-graph", "figure"),
        Output("status", "children"),
        Input("run", "n_clicks"),
        State("dataset", "value"),
        State("seed", "value"),
        State("drift", "value"),
    )
    def _update(_n, dataset, seed, drift):  # pragma: no cover - 互動回呼（純函式已測）
        try:
            analysis = fetch_analysis(base_url, dataset_id=dataset, seed=seed, drift_strength=drift)
        except Exception as exc:  # noqa: BLE001
            return go.Figure(), go.Figure(), f"後端錯誤：{exc}"
        n_alarm = sum(c["is_alarm"] for c in analysis["campaigns"])
        status = f"{analysis['n_campaigns']} campaigns，{n_alarm} 告警，re-entry={analysis['reentry_campaigns']}"
        return build_health_figure(analysis), build_subscore_figure(analysis), status

    return app


app = create_app()


if __name__ == "__main__":  # pragma: no cover
    app.run(host="127.0.0.1", port=8050, debug=False)
