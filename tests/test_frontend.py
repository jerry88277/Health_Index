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
    build_contribution_figure,
    build_health_figure,
    build_softsensor_figure,
    build_spc_figure,
    build_subscore_figure,
    build_timeline_figure,
    build_yhealth_figure,
    create_app,
    fetch_analysis,
    fetch_contribution,
    fetch_series,
    fetch_softsensor,
    fetch_timeline,
    fetch_yhealth,
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
    assert {t.name for t in fig.data} == {"資料效度", "製程關係偏移", "整體漂移"}


def test_subscore_figure_discriminates_drift(analysis):
    # WHY（紅隊 B 🔴）：子分數圖須真接對「名稱↔值」——drift(4) 的「製程關係偏移」(L2) 子分數應低於 golden(0)。
    # 鎖住「子分數全接 0 / L2↔L4 互換」這類喪失鑑別資訊的假綠（Rule 9）。
    fig = build_subscore_figure(analysis)
    idx = {c["campaign_id"]: i for i, c in enumerate(analysis["campaigns"])}
    l2 = {t.name: t.y for t in fig.data}["製程關係偏移"]
    assert l2[idx[4]] < l2[idx[0]]


def test_fetch_handles_none_inputs():
    # WHY（修 bug）：輸入框清空時 dcc.Input 回傳 None → 原 int(None)/float(None) 拋
    # 「float() argument must be a real number, not 'NoneType'」。None 須套預設值、不報錯。
    a = fetch_analysis(None, dataset_id="synthetic", seed=None, drift_strength=None, client=client)
    assert a["n_campaigns"] == 5
    t = fetch_timeline(None, dataset_id=None, seed=None, drift_strength=None, client=client)
    assert len(t["spe"]) == 1500


def test_analyze_returns_monitored_variables():
    # WHY（監控參數區塊）：/analyze 回傳監控的製程參數名稱
    a = fetch_analysis(None, dataset_id="synthetic", seed=5, drift_strength=1.2, client=client)
    assert len(a["variables"]) == 10 and "x00" in a["variables"]


def test_fetch_analysis_raises_on_backend_error():
    # 後端錯誤（404）→ raise_for_status 拋例外（前端 callback 才能優雅降級）
    import httpx as _httpx

    with pytest.raises(_httpx.HTTPStatusError):
        fetch_analysis(None, dataset_id="nope", client=client)


def test_create_app_layout_has_controls_and_graphs():
    app = create_app()
    ids = _collect_ids(app.layout)
    assert {"run", "health-graph", "subscore-graph", "seed", "drift", "dataset"} <= ids


# --- B1：時間軸 + 肇因圖 ---
@pytest.fixture(scope="module")
def timeline():
    return fetch_timeline(None, dataset_id="synthetic", seed=5, drift_strength=1.2, client=client)


@pytest.fixture(scope="module")
def contribution():
    return fetch_contribution(None, dataset_id="synthetic", seed=5, drift_strength=1.2, client=client)


def test_timeline_figure_has_spe_t2_and_limit(timeline):
    fig = build_timeline_figure(timeline)
    assert {"異常程度(SPE)", "製程偏移(T²)"} <= {t.name for t in fig.data}
    # 正常上限線存在且值正確（接錯 limit 會被抓）
    assert any(getattr(s, "y0", None) == timeline["spe_limit"] for s in fig.layout.shapes)


def test_contribution_figure_ranks_and_marks_spc(contribution):
    # WHY：肇因圖呈選定 campaign 的 RBC 由高到低，且文字標單變數 SPC 越界率（低=SPC 盲的對照）
    fig = build_contribution_figure(contribution, 4)
    bar = fig.data[0]
    ys = list(bar.y)
    assert ys == sorted(ys, reverse=True)                      # RBC 降序
    # 每根柱標自己的可疑度數值（非 0%；避免 drift 段越界率~0 時每根都顯示 "0%" 的困惑）
    assert list(bar.text) == [f"{y:.2f}" for y in ys]


def test_contribution_figure_selects_campaign(contribution):
    # WHY（鎖「campaign 選擇真的生效」）：選不同 campaign → 不同肇因變數集，非寫死 drift
    f0 = build_contribution_figure(contribution, 0)
    f4 = build_contribution_figure(contribution, 4)
    assert list(f0.data[0].x) != list(f4.data[0].x) or list(f0.data[0].y) != list(f4.data[0].y)


def test_layout_has_timeline_and_contribution_graphs():
    ids = _collect_ids(create_app().layout)
    assert {"timeline-graph", "contribution-graph", "contrib-campaign"} <= ids


@pytest.fixture(scope="module")
def series():
    return fetch_series(None, dataset_id="synthetic", seed=5, drift_strength=1.2, client=client)


def test_spc_figure_single_var_has_3sigma_band(series):
    # WHY（SPC 視圖）：單變數圖須畫該變數值 + 上下 3σ 管制線（值取自 golden）
    fig = build_spc_figure(series, "x03")
    yvals = {getattr(s, "y0", None) for s in fig.layout.shapes}
    assert series["spc_upper"]["x03"] in yvals and series["spc_lower"]["x03"] in yvals
    assert fig.data[0].name == "x03"


def test_spc_figure_all_overlays_ten_vars(series):
    # WHY（#6 全參數時序）：「全部」模式疊 10 條標準化軌跡
    fig = build_spc_figure(series, "__all__")
    assert len({t.name for t in fig.data}) == 10


def test_layout_has_spc_graph():
    ids = _collect_ids(create_app().layout)
    assert {"spc-graph", "spc-variable"} <= ids


def test_health_figure_has_uncertainty_error_bars(analysis):
    # WHY（融合分數不確定度帶）：health 圖須帶 error_y（bootstrap 信賴帶）
    fig = build_health_figure(analysis)
    assert fig.data[0].error_y is not None and fig.data[0].error_y.array is not None


def test_softsensor_figure_has_yhat_y_and_band():
    # WHY（量測值偏移視圖）：⑥圖含預測 Ŷ 線、實際 Y 點、可信帶
    soft = fetch_softsensor(None, dataset_id="synthetic", seed=5, drift_strength=1.2, client=client)
    fig = build_softsensor_figure(soft)
    names = {t.name for t in fig.data if t.name}
    assert "預測 Ŷ" in names and "實際 Y" in names
    assert any("可信帶" in (t.name or "") for t in fig.data)
    # ③ X→Y 延遲對齊狀態須標示於圖上（synthetic 列對齊 → 顯示「估計 0 步」）
    assert any("延遲對齊" in (a.text or "") for a in fig.layout.annotations)


def test_layout_has_softsensor_graph():
    ids = _collect_ids(create_app().layout)
    assert "softsensor-graph" in ids


def test_yhealth_figure_unavailable_on_synthetic():
    # synthetic 純量品質 → ⑦圖顯示「不適用」（不誤導為有 Y 分布健康）
    yh = fetch_yhealth(None, dataset_id="synthetic", seed=5, drift_strength=1.2, client=client)
    fig = build_yhealth_figure(yh)
    assert "不適用" in fig.layout.title.text


def test_layout_has_yhealth_graph():
    ids = _collect_ids(create_app().layout)
    assert "yhealth-graph" in ids
