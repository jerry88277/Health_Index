"""Plotly Dash 前端：經 REST 取後端結果，視覺化判斷鏈。

啟動（地端）：``python frontend/app.py``（預設 :8050，後端 :8000）。
視覺化：
- Health Index per-campaign 長條（紅=告警, *=re-entry）+ 各層健康子分數。
- 逐樣本 SPE/T² 時間軸 + 控制限（B1，經 ``/timeline``）——看出隱性飄移在序列中何時越限。
- 選定 campaign 的 RBC 肇因變數排序 + 單變數 3σ 越界率對照（B1，經 ``/contribution``）——指出哪個參數。

範圍誠實標記（Rule 12）：Ŷ vs Y 仍待後端軟測量端點（M-later）。RBC 為「定位非因果」、多方向
漂移有殘留 smearing。圖表建構為純函式（``build_*_figure``），可不啟動伺服器/後端被 pytest 驗證。
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


def fetch_timeline(
    base_url: str | None,
    *,
    dataset_id: str = "synthetic",
    seed: int = 5,
    drift_strength: float = 1.2,
    client=None,
) -> dict:
    """取後端 /timeline（逐樣本 T²/SPE/GSI + 控制限 + campaign 邊界）。"""
    payload = {"dataset_id": dataset_id, "seed": int(seed), "drift_strength": float(drift_strength)}
    resp = client.post("/timeline", json=payload) if client is not None else httpx.post(
        f"{base_url}/timeline", json=payload, timeout=120
    )
    resp.raise_for_status()
    return resp.json()


def fetch_contribution(
    base_url: str | None,
    *,
    dataset_id: str = "synthetic",
    seed: int = 5,
    drift_strength: float = 1.2,
    client=None,
) -> dict:
    """取後端 /contribution（per-campaign RBC 肇因排序）。"""
    payload = {"dataset_id": dataset_id, "seed": int(seed), "drift_strength": float(drift_strength)}
    resp = client.post("/contribution", json=payload) if client is not None else httpx.post(
        f"{base_url}/contribution", json=payload, timeout=120
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


def build_timeline_figure(timeline: dict) -> go.Figure:
    """逐樣本 SPE / T² 時間軸 + SPE 控制限 + campaign 邊界（看出隱性飄移何時越限）。"""
    n = len(timeline["spe"])
    x = list(range(n))
    fig = go.Figure()
    fig.add_scatter(x=x, y=timeline["spe"], name="SPE", line=dict(color="steelblue"))
    fig.add_scatter(x=x, y=timeline["t2"], name="T²", line=dict(color="darkorange"), yaxis="y2")
    fig.add_hline(
        y=timeline["spe_limit"], line_dash="dash", line_color="steelblue",
        annotation_text=f"SPE 控制限 {timeline['spe_limit']}",
    )
    for s in timeline["campaigns"]:
        fig.add_vline(x=s["start"], line_dash="dot", line_color="gray")
        fig.add_annotation(
            x=(s["start"] + s["end"]) / 2, y=1.02, yref="paper", showarrow=False,
            text=f"C{s['campaign_id']}·{s['grade']}",
        )
    fig.update_layout(
        title="逐樣本 SPE / T² 時間軸（虛線=SPE 控制限；越限=隱性飄移）",
        xaxis_title="樣本（時間序）",
        yaxis=dict(title="SPE"),
        yaxis2=dict(title="T²", overlaying="y", side="right"),
    )
    return fig


def build_contribution_figure(contribution: dict, campaign_id: int) -> go.Figure:
    """選定 campaign 的 top 變數 RBC 肇因長條；文字標單變數 3σ 越界率（低＝SPC 盲）。"""
    camps = {c["campaign_id"]: c for c in contribution["campaigns"]}
    camp = camps.get(campaign_id) or (contribution["campaigns"][0] if contribution["campaigns"] else None)
    tv = camp["top_variables"] if camp else []
    fig = go.Figure(
        go.Bar(
            x=[v["variable"] for v in tv],
            y=[v["rbc"] for v in tv],
            marker_color="indianred",
            text=[f"SPC {v['spc_exceedance']:.2f}" for v in tv],
            textposition="outside",
        )
    )
    grade = camp["grade"] if camp else "?"
    cid = camp["campaign_id"] if camp else campaign_id
    fig.update_layout(
        title=f"C{cid}·{grade} 肇因變數（RBC；文字=單變數3σ越界率，低=SPC 盲）",
        xaxis_title="變數",
        yaxis_title="RBC 肇因強度",
    )
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
            html.Div(
                [
                    html.Span("肇因 campaign："),
                    dcc.Dropdown(
                        id="contrib-campaign",
                        options=[{"label": f"C{i}", "value": i} for i in range(5)],
                        value=4,  # 預設 drift re-entry A（最具代表的隱性飄移段）
                        style={"width": "120px"},
                    ),
                ],
                style={"display": "flex", "gap": "10px", "alignItems": "center"},
            ),
            html.Div(id="status"),
            dcc.Graph(id="health-graph"),
            dcc.Graph(id="subscore-graph"),
            dcc.Graph(id="timeline-graph"),
            dcc.Graph(id="contribution-graph"),
        ]
    )

    @app.callback(
        Output("health-graph", "figure"),
        Output("subscore-graph", "figure"),
        Output("timeline-graph", "figure"),
        Output("contribution-graph", "figure"),
        Output("status", "children"),
        Input("run", "n_clicks"),
        Input("contrib-campaign", "value"),
        State("dataset", "value"),
        State("seed", "value"),
        State("drift", "value"),
    )
    def _update(_n, contrib_cid, dataset, seed, drift):  # pragma: no cover - 互動回呼（純函式已測）
        try:
            analysis = fetch_analysis(base_url, dataset_id=dataset, seed=seed, drift_strength=drift)
            timeline = fetch_timeline(base_url, dataset_id=dataset, seed=seed, drift_strength=drift)
            contrib = fetch_contribution(base_url, dataset_id=dataset, seed=seed, drift_strength=drift)
        except Exception as exc:  # noqa: BLE001
            empty = go.Figure()
            return empty, empty, empty, empty, f"後端錯誤：{exc}"
        n_alarm = sum(c["is_alarm"] for c in analysis["campaigns"])
        status = f"{analysis['n_campaigns']} campaigns，{n_alarm} 告警，re-entry={analysis['reentry_campaigns']}"
        return (
            build_health_figure(analysis),
            build_subscore_figure(analysis),
            build_timeline_figure(timeline),
            build_contribution_figure(contrib, int(contrib_cid) if contrib_cid is not None else 4),
            status,
        )

    return app


app = create_app()


if __name__ == "__main__":  # pragma: no cover
    app.run(host="127.0.0.1", port=8050, debug=False)
