"""前端（Dash）WHY 測試（Rule 9）。

WHY：前端的價值是把判斷鏈結果**正確視覺化**。marquee＝Health Index 圖**忠實反映鑑別**——
drift campaign 呈「告警色」且分數低、golden 呈「健康色」且分數高。若圖表建構喪失此對應
（例如不依 is_alarm 上色、或 y 值接錯），測試必須失敗。圖表建構為純函式，餵真實鏈輸出驗證。
"""

import pytest

pytest.importorskip("dash")
pytest.importorskip("plotly")
pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from frontend.app import (  # noqa: E402
    ALARM,
    OK,
    build_health_figure,
    build_subscore_figure,
    create_app,
    fetch_analysis,
)
from health_index.api.server import app as api_app  # noqa: E402
from health_index.config import DEFAULT  # noqa: E402

client = TestClient(api_app)


@pytest.fixture(scope="module")
def analysis():
    # 經真實後端鏈（TestClient 注入）取結果，供圖表建構驗證端到端
    return fetch_analysis(None, dataset_id="synthetic", seed=5, drift_strength=1.2, client=client)


def _collect_ids(component) -> set:
    ids = set()
    cid = getattr(component, "id", None)
    if isinstance(cid, str):
        ids.add(cid)
    children = getattr(component, "children", None)
    if isinstance(children, (list, tuple)):
        for c in children:
            ids |= _collect_ids(c)
    elif children is not None and hasattr(children, "children"):
        ids |= _collect_ids(children)
    return ids


def test_fetch_analysis_via_client(analysis):
    assert analysis["n_campaigns"] == 5
    assert analysis["reentry_campaigns"] == [2, 4]


def test_health_figure_renders_alarm_discrimination(analysis):
    fig = build_health_figure(analysis)
    bar = fig.data[0]
    camps = analysis["campaigns"]
    colors = {c["campaign_id"]: bar.marker.color[i] for i, c in enumerate(camps)}
    yvals = {c["campaign_id"]: bar.y[i] for i, c in enumerate(camps)}
    # drift(4) 告警呈紅且分數低；golden(0) 健康呈綠且分數高
    assert colors[4] == ALARM and colors[0] == OK
    assert yvals[4] < yvals[0]
    # 告警門檻線存在且值正確（接錯 threshold 會被抓）
    assert any(getattr(s, "y0", None) == DEFAULT.hi_alarm_threshold for s in fig.layout.shapes)


def test_subscore_figure_has_three_layers(analysis):
    fig = build_subscore_figure(analysis)
    assert {t.name for t in fig.data} == {"L1", "L2", "L4"}


def test_subscore_figure_discriminates_drift(analysis):
    # WHY（紅隊 B 🔴）：子分數圖須真接對「名稱↔值」——drift(4) 的 L2 子分數應低於 golden(0)。
    # 鎖住「子分數全接 0 / L2↔L4 互換」這類喪失鑑別資訊的假綠（Rule 9）。
    fig = build_subscore_figure(analysis)
    idx = {c["campaign_id"]: i for i, c in enumerate(analysis["campaigns"])}
    l2 = {t.name: t.y for t in fig.data}["L2"]
    assert l2[idx[4]] < l2[idx[0]]


def test_fetch_analysis_raises_on_backend_error():
    # 後端錯誤（404）→ raise_for_status 拋例外（前端 callback 才能優雅降級）
    import httpx as _httpx

    with pytest.raises(_httpx.HTTPStatusError):
        fetch_analysis(None, dataset_id="nope", client=client)


def test_create_app_layout_has_controls_and_graphs():
    app = create_app()
    ids = _collect_ids(app.layout)
    assert {"run", "health-graph", "subscore-graph", "seed", "drift", "dataset"} <= ids
