"""Plotly Dash 前端：經 REST 取後端結果，視覺化製程健康度（現場工程師導向）。

啟動（地端）：``python frontend/app.py``（預設 :8050，後端 :8000）。
版面由上而下、顆粒度由大到小：前情提要 → 監控參數 → 設定說明 → ①總健康度 → ②三面向子分數
→ ③可疑參數排行 → ④異常程度時間軸 → 名詞解釋。術語以現場白話呈現（如 SPE→「異常程度」、
L2→「製程關係偏移」、RBC→「可疑參數排行」），底部附專業詞對照。

範圍誠實標記（Rule 12）：Ŷ vs Y 仍待後端軟測量端點（M-later）。RBC 為「定位非因果」、多方向
漂移有殘留 smearing。圖表建構為純函式（``build_*_figure``），可不啟動伺服器/後端被 pytest 驗證。
"""

from __future__ import annotations

import httpx
import numpy as np
import plotly.graph_objects as go
from dash import Dash, Input, Output, State, dcc, html

from health_index.config import DEFAULT

DEFAULT_API = "http://127.0.0.1:8000"
ALARM = "crimson"
OK = "seagreen"

# 內部偵測層 → 現場白話標籤
LAYER_LABELS = {"L1": "資料效度", "L2": "製程關係偏移", "L4": "整體漂移"}

_CARD = {"border": "1px solid #ddd", "borderRadius": "8px", "padding": "12px 16px", "margin": "10px 0", "background": "#fafafa"}


def _payload(dataset_id, seed, drift_strength) -> dict:
    """組請求；輸入框清空時 dcc.Input 回傳 None → 套預設值（修 float(None)/int(None) 錯誤）。"""
    return {
        "dataset_id": dataset_id or "synthetic",
        "seed": 5 if seed is None else int(seed),
        "drift_strength": 1.2 if drift_strength is None else float(drift_strength),
    }


def _post(path: str, payload: dict, base_url: str | None, client) -> dict:
    resp = client.post(path, json=payload) if client is not None else httpx.post(
        f"{base_url}{path}", json=payload, timeout=120
    )
    resp.raise_for_status()
    return resp.json()


def fetch_analysis(base_url, *, dataset_id="synthetic", seed=5, drift_strength=1.2, client=None) -> dict:
    """取後端 /analyze（per-campaign 健康度/告警/re-entry/監控參數）。"""
    return _post("/analyze", _payload(dataset_id, seed, drift_strength), base_url, client)


def fetch_timeline(base_url, *, dataset_id="synthetic", seed=5, drift_strength=1.2, client=None) -> dict:
    """取後端 /timeline（逐樣本 T²/SPE/GSI + 控制限 + campaign 邊界）。"""
    return _post("/timeline", _payload(dataset_id, seed, drift_strength), base_url, client)


def fetch_contribution(base_url, *, dataset_id="synthetic", seed=5, drift_strength=1.2, client=None) -> dict:
    """取後端 /contribution（per-campaign 可疑參數排行 RBC）。"""
    return _post("/contribution", _payload(dataset_id, seed, drift_strength), base_url, client)


def fetch_series(base_url, *, dataset_id="synthetic", seed=5, drift_strength=1.2, client=None) -> dict:
    """取後端 /series（逐樣本原始參數值 + golden 3σ 單變數管制線）。"""
    return _post("/series", _payload(dataset_id, seed, drift_strength), base_url, client)


def fetch_softsensor(base_url, *, dataset_id="synthetic", seed=5, drift_strength=1.2, client=None) -> dict:
    """取後端 /softsensor（逐樣本預測 Ŷ + 可信帶 + 實際 Y）。"""
    return _post("/softsensor", _payload(dataset_id, seed, drift_strength), base_url, client)


def fetch_yhealth(base_url, *, dataset_id="synthetic", seed=5, drift_strength=1.2, client=None) -> dict:
    """取後端 /yhealth（per-campaign Y 分布健康；Y-MSPC）。"""
    return _post("/yhealth", _payload(dataset_id, seed, drift_strength), base_url, client)


def fetch_fwer(base_url, *, dataset_id="synthetic", seed=5, drift_strength=1.2, client=None) -> dict:
    """取後端 /fwer（per-campaign AC-6 嚴格告警；保時序情境隱性飄移的主偵測路徑）。"""
    return _post("/fwer", _payload(dataset_id, seed, drift_strength), base_url, client)


def _label(c: dict) -> str:
    return f"C{c['campaign_id']}·{c['grade']}" + ("*" if c["is_reentry"] else "")


def build_health_figure(analysis: dict, *, threshold: float = DEFAULT.hi_alarm_threshold) -> go.Figure:
    """①總健康度：每段產品一個 0–1 分數（綠=健康/紅=告警，標告警門檻）。"""
    camps = analysis["campaigns"]
    colors = [ALARM if c["is_alarm"] else OK for c in camps]
    has_band = any(c.get("health_hi", 0) > c.get("health_lo", 0) for c in camps)
    error_y = None
    if has_band:
        error_y = dict(
            type="data", symmetric=False,
            array=[max(0.0, c.get("health_hi", 0) - c["health_index"]) for c in camps],
            arrayminus=[max(0.0, c["health_index"] - c.get("health_lo", 0)) for c in camps],
            color="#333", thickness=1.5,
        )
    fig = go.Figure(
        go.Bar(
            x=[_label(c) for c in camps],
            y=[c["health_index"] for c in camps],
            marker_color=colors,
            text=[f"{c['health_index']:.2f}" for c in camps],
            textposition="outside",
            error_y=error_y,
        )
    )
    fig.add_hline(y=threshold, line_dash="dash", annotation_text=f"告警門檻 {threshold}")
    fig.update_layout(
        title="① 總健康度（每段產品一個分數；綠=健康、紅=告警、* =換產品後回歸段；黑線=不確定度帶）",
        yaxis=dict(range=[0, 1.05], title="健康度（1=最健康）"),
    )
    return fig


def build_subscore_figure(analysis: dict) -> go.Figure:
    """②三面向健康子分數：資料效度(L1) / 製程關係偏移(L2) / 整體漂移(L4)，1=健康。"""
    camps = analysis["campaigns"]
    x = [_label(c) for c in camps]
    fig = go.Figure()
    for layer, name in LAYER_LABELS.items():
        fig.add_bar(name=name, x=x, y=[c["subscores"][layer] for c in camps])
    fig.update_layout(
        barmode="group",
        title="② 三面向健康子分數（1=健康；哪個面向掉下來＝哪種異常）",
        yaxis=dict(range=[0, 1.05], title="子分數（1=健康）"),
    )
    return fig


def build_contribution_figure(contribution: dict, campaign_id: int) -> go.Figure:
    """③可疑參數排行：選定段內各參數的可疑程度排序（文字＝該參數單獨看的越界率，低＝單一儀表看不出）。"""
    camps = {c["campaign_id"]: c for c in contribution["campaigns"]}
    camp = camps.get(campaign_id) or (contribution["campaigns"][0] if contribution["campaigns"] else None)
    tv = camp["top_variables"] if camp else []
    fig = go.Figure(
        go.Bar(
            x=[v["variable"] for v in tv],
            y=[v["rbc"] for v in tv],
            marker_color="indianred",
            text=[f"{v['rbc']:.2f}" for v in tv],
            textposition="outside",
        )
    )
    grade = camp["grade"] if camp else "?"
    cid = camp["campaign_id"] if camp else campaign_id
    fig.update_layout(
        title=f"③ 可疑參數排行 — C{cid}·{grade}（柱越高＝越可疑；數字＝可疑度）",
        xaxis_title="製程參數",
        yaxis_title="可疑程度",
    )
    return fig


def build_timeline_figure(timeline: dict) -> go.Figure:
    """④異常程度時間軸：逐樣本異常程度(SPE) / 製程偏移(T²) + 正常上限（越高越偏離正常）。"""
    n = len(timeline["spe"])
    x = list(range(n))
    fig = go.Figure()
    fig.add_scatter(x=x, y=timeline["spe"], name="異常程度(SPE)", line=dict(color="steelblue"))
    fig.add_scatter(x=x, y=timeline["t2"], name="製程偏移(T²)", line=dict(color="darkorange"), yaxis="y2")
    fig.add_hline(
        y=timeline["spe_limit"], line_dash="dash", line_color="crimson", line_width=3,
        annotation_text=f"異常程度(SPE) 正常上限 {timeline['spe_limit']}",
    )
    for s in timeline["campaigns"]:
        fig.add_vline(x=s["start"], line_dash="dot", line_color="gray")
        fig.add_annotation(
            x=(s["start"] + s["end"]) / 2, y=1.02, yref="paper", showarrow=False,
            text=f"C{s['campaign_id']}·{s['grade']}",
        )
    fig.update_layout(
        title="④ 異常程度時間軸（越高越偏離正常；超過虛線=該時刻異常）",
        xaxis_title="時間（樣本序）",
        yaxis=dict(title="異常程度(SPE)"),
        yaxis2=dict(title="製程偏移(T²)", overlaying="y", side="right"),
    )
    return fig


def build_spc_figure(series: dict, variable: str) -> go.Figure:
    """⑤單變數 SPC / 全參數時序：選一個參數看其值 + ±3σ 管制線（示範 SPC 隱形）；或「全部」標準化疊圖。"""
    spans = series["campaigns"]
    n = len(next(iter(series["series"].values())))
    x = list(range(n))
    if variable != "__all__" and variable not in series["series"]:
        variable = series["variables"][0]  # 跨資料集切換時舊選值失效 → 退回第一個參數
    fig = go.Figure()
    if variable == "__all__":
        for v in series["variables"]:
            arr = np.asarray(series["series"][v], dtype=float)
            z = (arr - arr.mean()) / (arr.std() + 1e-9)
            fig.add_scatter(x=x, y=z, name=v, mode="lines")
        title = "⑤ 全部參數時間軸（標準化；一次看 10 個參數的時序形狀）"
        ytitle = "標準化值"
    else:
        vals = series["series"][variable]
        up, lo = series["spc_upper"][variable], series["spc_lower"][variable]
        fig.add_scatter(x=x, y=vals, name=variable, line=dict(color="steelblue"))
        fig.add_hline(y=up, line_dash="dash", line_color="crimson", annotation_text="3σ 上限")
        fig.add_hline(y=lo, line_dash="dash", line_color="crimson", annotation_text="3σ 下限")
        title = f"⑤ 單變數 SPC：{variable}（紅線=±3σ 管制限；飄移段仍在線內＝單變數 SPC 看不到）"
        ytitle = "參數值"
    for s in spans:
        fig.add_vline(x=s["start"], line_dash="dot", line_color="gray")
        fig.add_annotation(
            x=(s["start"] + s["end"]) / 2, y=1.02, yref="paper", showarrow=False,
            text=f"C{s['campaign_id']}·{s['grade']}",
        )
    fig.update_layout(title=title, xaxis_title="時間（樣本序）", yaxis_title=ytitle)
    return fig


def build_softsensor_figure(soft: dict) -> go.Figure:
    """⑥量測值：預測 Ŷ（線）+ 可信帶（陰影）+ 實際 Y（紅點）。實際 Y 落出帶外＝量測層飄移/Ŷ 不可信。"""
    yhat, bh, ya = soft["yhat"], soft["band_half"], soft["y_actual"]
    n = len(yhat)
    x = list(range(n))
    upper = [yhat[i] + bh[i] for i in range(n)]
    lower = [yhat[i] - bh[i] for i in range(n)]
    fig = go.Figure()
    fig.add_scatter(x=x, y=upper, line=dict(width=0), showlegend=False, hoverinfo="skip")
    fig.add_scatter(
        x=x, y=lower, fill="tonexty", fillcolor="rgba(255,159,64,0.35)", line=dict(width=0),
        name=f"可信帶（{soft['band_kind']}）",
    )
    fig.add_scatter(x=x, y=yhat, name="預測 Ŷ", line=dict(color="steelblue"))
    ax = [i for i, v in enumerate(ya) if v is not None]
    fig.add_scatter(x=ax, y=[ya[i] for i in ax], mode="markers", name="實際 Y", marker=dict(color="crimson", size=6))
    for s in soft["campaigns"]:
        fig.add_vline(x=s["start"], line_dash="dot", line_color="gray")
        fig.add_annotation(
            x=(s["start"] + s["end"]) / 2, y=1.02, yref="paper", showarrow=False,
            text=f"C{s['campaign_id']}·{s['grade']}",
        )
    d = soft.get("y_delay_steps", 0)
    delay_txt = (
        # 誠實標：0 是「此資料集列對齊」的性質，非對真實產線輸送延遲的量測結果（Rule 12）
        "X→Y 延遲對齊：本資料估計 0 步（此資料集量測與製程列對齊；真實產線若有輸送延遲會估出 N 步並自動校正）"
        if d == 0
        else f"X→Y 延遲對齊：估計 {d} 步（已以 X(t−{d}) 訓練映射，避免錯位污染）"
    )
    fig.add_annotation(
        x=0.0, y=1.14, xref="paper", yref="paper", showarrow=False, align="left",
        text=delay_txt, font=dict(size=12, color="#555"),
    )
    fig.update_layout(
        title="⑥ 量測值：預測 Ŷ vs 實際 Y（含可信帶）", xaxis_title="時間（樣本序）", yaxis_title="量測值 Y",
        margin=dict(t=96),  # 留頂部空間給延遲對齊註記，避免與標題/campaign 標籤擠壓（紅隊 B#1）
    )
    return fig


_LAYER_NAME = {"L1": "資料效度", "L2": "製程關係偏移", "L4": "整體漂移"}


def build_fwer_figure(fw: dict) -> go.Figure:
    """⑧AC-6 嚴格告警：per-campaign Holm 單一決策點（紅=告警，標被判異常的層）。

    保時序情境下隱性飄移由此偵測——融合 Health Index 受權重稀釋可能不過閾（drift≈0.85>0.6），但
    AC-6（對 golden null Holm 校正，誤報率≤α）抓得到，且 ``rejected`` 標出是哪一層（多為 L2 製程關係偏移）。
    """
    camps = fw.get("campaigns", [])
    if not camps:
        fig = go.Figure()
        fig.add_annotation(text="（無 AC-6 資料）", showarrow=False, xref="paper", yref="paper", x=0.5, y=0.5)
        fig.update_layout(title="⑧ AC-6 嚴格告警")
        return fig

    def lab(c: dict) -> str:
        return f"C{c['campaign_id']}·{c['grade']}" + ("*" if c["is_reentry"] else "")

    susp = [round(1.0 - min((c.get("pvalues") or {"_": 1.0}).values()), 3) for c in camps]  # 可疑度＝1−最小 p
    colors = [ALARM if c["fwer_alarm"] else OK for c in camps]
    text = [
        ("告警：" + "+".join(_LAYER_NAME.get(k, k) for k in c["rejected"])) if c["fwer_alarm"] else "正常"
        for c in camps
    ]
    fig = go.Figure(go.Bar(x=[lab(c) for c in camps], y=susp, marker_color=colors, text=text, textposition="outside"))
    fig.update_layout(
        title="⑧ AC-6 嚴格告警（Holm 單一決策點；保時序隱性飄移由此抓，融合分數可能不過閾）",
        yaxis=dict(range=[0, 1.18], title="可疑度（1−最小 p；越高越異常）"),
    )
    return fig


def build_yhealth_figure(yh: dict) -> go.Figure:
    """⑦Y 分布健康：per-campaign 品質(G/H)分布 vs golden 的 Y-MSPC（紅=分布顯著偏離）。"""
    if not yh.get("available"):
        fig = go.Figure()
        fig.add_annotation(text=yh.get("note", "此資料集為純量品質，Y 分布健康需多維品質"),
                           showarrow=False, font=dict(size=14), xref="paper", yref="paper", x=0.5, y=0.5)
        fig.update_layout(title="⑦ Y 分布健康（此資料集不適用：需多維品質如 G/H）")
        return fig
    camps = yh["campaigns"]
    colors = [ALARM if c["y_flagged"] else OK for c in camps]
    fig = go.Figure(
        go.Bar(
            x=[f"C{c['campaign_id']}·{c['grade']}" + ("*" if c["is_reentry"] else "") for c in camps],
            y=[c["y_health"] for c in camps], marker_color=colors,
            text=[f"{c['y_health']:.2f}" for c in camps], textposition="outside",
        )
    )
    fig.update_layout(
        title="⑦ Y 分布健康（品質 G/H 分布 vs golden；紅=分布顯著偏離）",
        yaxis=dict(range=[0, 1.05], title="Y 分布健康（1=健康）"),
    )
    return fig


# ---- 圖表下方白話說明 ----

_CAP = {"color": "#555", "fontSize": "14px", "margin": "2px 0 14px 0"}

_CAP_HEALTH = (
    "編號說明：數字=第幾段製程、字母=產品種類(grade)、* =換產品後第一段回歸。產線依序生產 "
    "A→B→A→C→A。不同產品(B/C)操作點本就不同、健康度低是正常的，別跨產品比較；重點看同一支產品 A "
    "的不同段：C0(基準)與 C2(乾淨回歸)健康，C4 回歸卻掉下來＝殘留隱性飄移。"
)
_SUB_EXPLAIN = [
    ("資料效度 (L1)",
     "這段資料本身可不可信。用穩健統計(FastMCD)＋PCA 距離(DQI_x)判定每筆是否落在「正常資料範圍」內；"
     "子分數＝落在範圍內的樣本比例。低分＝資料有缺值/超界/離群，該先處理再談判斷。"),
    ("製程關係偏移 (L2)",
     "變數「之間的關係」有沒有變——隱性飄移的主訊號。用正常段(golden)學 PCA 模型，對每筆算 "
     "T²(正常子空間內的偏離)與 SPE(殘差空間的偏離)；子分數＝未越管制限的樣本比例。低分＝變數關係結構偏移。"),
    ("整體飄移 (L4)",
     "整段資料的「分佈」有沒有整體位移。把這段與正常基準在 PCA 分數空間相比，用 1D-Wasserstein 距離"
     "(對正常 null 標準化的 z 分數)量位移幅度，再 exp 衰減成 0–1；子分數低＝整段分佈偏離正常。"),
]
_SUB_NOTE = "三者皆 0–1（1=健康）、方向統一；加權（製程關係偏移權重×2，因它是隱性飄移主訊號）融合成 ① 總健康度。"
_CAP_CONTRIB = (
    "把「異常程度」拆解到各參數，指出哪個參數對這段偏移貢獻最多——去現場優先檢查它（柱越高越可疑）。"
    "注意：在隱性飄移段，這些可疑參數單獨看幾乎都沒越過各自的 3σ 管制線（接近 0%，見下方 ⑤ SPC 圖），"
    "所以單變數管制圖看不出來，必須靠多變量監控才抓得到。"
)
_CAP_TIMELINE = (
    "整段製程逐時刻的兩個指標：藍線＝異常程度(SPE，看左軸)、橘線＝製程偏移(T²，看右軸)。"
    "紅色粗虛線是『異常程度(SPE)』的正常上限——由健康基準（golden 段）的正常波動自動定出："
    "當藍線(SPE)超過這條紅線，代表該時刻已偏離正常的變數關係結構＝異常。可看出飄移在序列中何時開始、"
    "持續多久。（註：紅線只卡藍線 SPE，不卡橘線 T²；SPE 是隱性飄移的主訊號。）"
)
_CAP_SPC = (
    "這是現場熟悉的單變數管制圖：某參數的值 + 它的 ±3σ 管制線。關鍵：飄移段（最後一段 A）的值"
    "幾乎都還在 3σ 線內——單看這張圖『正常』，但①總健康度已告警。這就是隱性飄移：單變數 SPC 看不到、"
    "多變量才抓得到。切到「全部(標準化)」可一次看 10 個參數的時序。"
)
_CAP_SOFT = (
    "量測值(品質 Y)層的視角：藍線是用製程參數 X 算出的預測量測 Ŷ，陰影是它的可信帶，紅點是實際 Y。"
    "在 golden/乾淨段 Ŷ 貼著實際 Y；到飄移段，X→Y 的映射已偏移，Ŷ 會偏離實際 Y、實際 Y 落出可信帶"
    "＝量測值層也飄移、Ŷ 不可信。可信帶來源：標籤足量時用 Conformal Prediction（覆蓋保證）；本合成資料"
    "標籤稀疏（<200）故退回 GPR 後驗 std（圖例標 GPR_std）。"
)
_CAP_YHEALTH = (
    "品質(Y)的『分布』本身有沒有偏移：用 G/H 多變量管制(T²/SPE)比這段品質分布 vs golden。"
    "換產品(B/C)因 G/H 比例不同會被強烈旗標(正常——產品真的不一樣)；但注入飄移的回歸段(最後一段 A)"
    "其 Y 分布幾乎不變→這裡不旗標。對照 ⑥：飄移段正是『品質測量看似正常、但 X→Y 關係已斷』的隱蔽"
    "案例——⑦(Y 分布)看不到、⑥(軟測量映射)才抓得到。兩者互補：⑦看品質變沒變、⑥看關係斷沒斷。"
    "（synthetic 為純量品質，此圖不適用。）"
)

_CAP_FWER = (
    "嚴格告警(AC-6)：對『正常基準(golden)』做統計校正(Holm)，保證健康段誤報率 ≤5%。紅=告警並標出是哪一"
    "層出問題(多為『製程關係偏移』L2)，綠=正常。* =換產品後回歸段。重點看『TEP(保時序)』資料集：殘留"
    "飄移的回歸段(最後一段 A)在這裡會亮紅(L2 抓到)，但它的①總健康分數因多層平均稀釋可能沒掉到門檻下——"
    "所以隱性飄移要以本圖(嚴格告警)為準，而非只看①。乾淨回歸段(前一段 A*)維持綠＝不誤報。"
)


# ---- 靜態說明區塊 ----

_SCENARIO = (
    "情境：同一條產線、監控同一組參數。先生產產品 A 建立「健康基準」，接著換去生產 B、再回 A、"
    "換 C、再回 A。每次換產品時操作點本來就會改變（流量/溫度設定不同），這是正常的。"
    "但回到 A 時，若製程已悄悄老化或偏移（例如觸媒衰退、感測器漂移、結垢），每個參數單獨看仍在規格內、"
    "傳統 SPC 一切正常，實際上變數之間的關係已經變了——這就是要抓的隱性飄移。本工具的價值：在"
    "「回歸 A」這一段，分辨它是乾淨回歸（健康）還是殘留飄移（該預警）。"
)

_SETTINGS_HELP = [
    ("資料情境（dataset）", "要分析哪組資料。目前為合成連續製程示範（A→B→A→C→A，最後一段 A 注入隱性飄移）。"),
    ("亂數種子（seed）", "可重現的隨機種子；不同種子＝不同產線實例。清空會自動用預設 5。"),
    ("飄移強度（drift_strength）", "模擬隱性飄移有多嚴重，數值越大越明顯。清空會自動用預設 1.2。"),
    ("可疑參數要看哪一段", "下方「可疑參數排行」圖要呈現哪一段（campaign）的肇因；預設看最後一段回歸 A。"),
]

_GLOSSARY = [
    ("Health Index 健康度", "把多個偵測面向融合成 0–1 的單一分數，1=最健康；現場只要看紅綠燈與分數。"),
    ("隱性飄移 (hidden drift)", "每個變數單獨都在規格內，但變數間關係或 X→Y 映射已偏移；單變數 SPC 看不到。"),
    ("AVM / 軟測量", "用製程參數 X 推估難測/破壞性的品質量 Ŷ，並在預測不可信時預警（鄭芳田教授 AVM 精神）。"),
    ("PCA 主成分分析", "把眾多相關變數壓成少數獨立方向，方便量「整體關係」是否偏離正常。"),
    ("T² (Hotelling)", "在 PCA 保留的正常子空間內，當前點離正常中心多遠＝『製程偏移』。"),
    ("SPE / Q (異常程度)", "當前點落在 PCA『殘差空間』的大小＝偏離正常關係結構多少；隱性飄移的主訊號。"),
    ("RBC 可疑參數", "把 SPE 異常拆解到各變數，指出『哪個參數』貢獻最多偏移（定位用，非因果）。"),
    ("MMD / Wasserstein", "量整段資料的分佈漂移：換線後一段資料是否整體偏離正常分佈。"),
    ("資料效度 (DQI_x)", "判斷前先檢查輸入資料本身可不可信：有沒有缺值、超出物理範圍、訊號凍結不動。"
        "資料不可信就不硬做判斷，避免「垃圾進、垃圾出」。子分數低=這段資料品質本身有問題。"),
    ("單變數 SPC / 3σ 管制線", "現場最熟悉的管制圖：單一參數的值 + 平均±3 倍標準差的上下限。"
        "本工具要凸顯的正是：隱性飄移時這張圖看起來『正常』，多變量方法才抓得到。"),
    ("FWER / Holm", "多個偵測面向一起判時，控制『正常段被誤報』的整體機率不超過設定值。"),
    ("DTW 批次對齊", "批次製程每批長短不一，用動態時間規整對齊軌跡後比形狀（批次型專用）。"),
    ("re-entry 回歸段", "換產品/維修後第一段回到同一支產品；殘留飄移最常在此現形，重點監看。"),
]


def _intro_card() -> html.Div:
    return html.Div([html.H4("前情提要"), html.P(_SCENARIO)], style=_CARD)


def _settings_card() -> html.Div:
    return html.Div(
        [
            html.H4("設定說明"),
            html.Ul([html.Li([html.B(k + "："), v]) for k, v in _SETTINGS_HELP]),
            html.Div(
                [
                    dcc.Dropdown(
                        id="dataset",
                        options=[
                            {"label": "synthetic（合成示範）", "value": "synthetic"},
                            {"label": "TEP（真實連續製程＋注入隱性飄移）", "value": "tep"},
                            {"label": "TEP（保時序：AC-6/L2 偵測，②）", "value": "tep_tp"},
                            {"label": "高維合成（40 參數，軟測量走 PLS，桶2a）", "value": "synthetic_hd"},
                        ],
                        value="synthetic", style={"width": "280px"},
                    ),
                    html.Span("種子"),
                    dcc.Input(id="seed", type="number", value=5, min=0, step=1, style={"width": "80px"}),
                    html.Span("飄移強度"),
                    dcc.Input(id="drift", type="number", value=1.2, min=0.01, step=0.1, style={"width": "90px"}),
                    html.Span("可疑參數看哪段"),
                    dcc.Dropdown(id="contrib-campaign", options=[{"label": f"C{i}", "value": i} for i in range(5)],
                                 value=4, style={"width": "110px"}),
                    html.Button("分析", id="run", n_clicks=0),
                ],
                style={"display": "flex", "gap": "8px", "alignItems": "center", "flexWrap": "wrap", "marginTop": "8px"},
            ),
        ],
        style=_CARD,
    )


def _subscore_caption() -> html.Div:
    """②圖下方：逐項說明三面向子分數是什麼、怎麼算。"""
    items = [html.Li([html.B(k + "："), v]) for k, v in _SUB_EXPLAIN]
    return html.Div([html.Ul(items, style={"margin": "2px 0"}), html.Div(_SUB_NOTE, style=_CAP)], style=_CAP)


def _glossary_card() -> html.Div:
    rows = [html.Tr([html.Th("專業名詞"), html.Th("白話解釋")])]
    rows += [html.Tr([html.Td(html.B(term)), html.Td(plain)]) for term, plain in _GLOSSARY]
    return html.Div(
        [html.H4("名詞解釋（專業詞 → 白話）"), html.Table(rows, style={"borderCollapse": "collapse", "width": "100%"})],
        style=_CARD,
    )


def create_app(base_url: str = DEFAULT_API) -> Dash:
    """建立 Dash app（由上而下：說明 → 監控參數 → 設定 → 四張圖（大到小）→ 名詞解釋）。"""
    app = Dash(__name__, title="製程健康度監控")
    app.layout = html.Div(
        [
            html.H2("製程健康度監控 — 隱性飄移偵測"),
            _intro_card(),
            html.Div(
                [
                    html.H4("監控的製程參數 / 量測值"),
                    html.Div(id="monitored-params", children="按下「分析」後顯示本資料監控的製程參數。"),
                ],
                style=_CARD,
            ),
            _settings_card(),
            html.Div(id="status", style={"fontWeight": "bold", "margin": "8px 0"}),
            dcc.Graph(id="health-graph"),
            html.P(_CAP_HEALTH, style=_CAP),
            dcc.Graph(id="subscore-graph"),
            _subscore_caption(),
            dcc.Graph(id="contribution-graph"),
            html.P(_CAP_CONTRIB, style=_CAP),
            dcc.Graph(id="timeline-graph"),
            html.P(_CAP_TIMELINE, style=_CAP),
            html.Div(
                [
                    html.Span("⑤ 看哪個參數的管制圖："),
                    dcc.Dropdown(
                        id="spc-variable",
                        options=[{"label": f"x{i:02d}", "value": f"x{i:02d}"} for i in range(10)]
                        + [{"label": "全部(標準化)", "value": "__all__"}],
                        value="x03", style={"width": "180px"},
                    ),
                ],
                style={"display": "flex", "gap": "8px", "alignItems": "center", "marginTop": "6px"},
            ),
            dcc.Graph(id="spc-graph"),
            html.P(_CAP_SPC, style=_CAP),
            dcc.Graph(id="softsensor-graph"),
            html.P(_CAP_SOFT, style=_CAP),
            dcc.Graph(id="yhealth-graph"),
            html.P(_CAP_YHEALTH, style=_CAP),
            dcc.Graph(id="fwer-graph"),
            html.P(_CAP_FWER, style=_CAP),
            _glossary_card(),
        ],
        style={"maxWidth": "1100px", "margin": "0 auto", "fontFamily": "system-ui, sans-serif"},
    )

    _fwer_memo: dict = {}  # 記憶化 AC-6 fwer（tep_tp 約 80s）——避免改 contrib/spc 下拉就整段重算（紅隊 B）

    @app.callback(
        Output("health-graph", "figure"),
        Output("subscore-graph", "figure"),
        Output("contribution-graph", "figure"),
        Output("timeline-graph", "figure"),
        Output("spc-graph", "figure"),
        Output("softsensor-graph", "figure"),
        Output("yhealth-graph", "figure"),
        Output("fwer-graph", "figure"),
        Output("status", "children"),
        Output("monitored-params", "children"),
        Output("spc-variable", "options"),
        Input("run", "n_clicks"),
        Input("contrib-campaign", "value"),
        Input("spc-variable", "value"),
        State("dataset", "value"),
        State("seed", "value"),
        State("drift", "value"),
    )
    def _update(_n, contrib_cid, spc_var, dataset, seed, drift):  # pragma: no cover - 互動回呼（純函式已測）
        try:
            analysis = fetch_analysis(base_url, dataset_id=dataset, seed=seed, drift_strength=drift)
            timeline = fetch_timeline(base_url, dataset_id=dataset, seed=seed, drift_strength=drift)
            contrib = fetch_contribution(base_url, dataset_id=dataset, seed=seed, drift_strength=drift)
            series = fetch_series(base_url, dataset_id=dataset, seed=seed, drift_strength=drift)
            soft = fetch_softsensor(base_url, dataset_id=dataset, seed=seed, drift_strength=drift)
            yh = fetch_yhealth(base_url, dataset_id=dataset, seed=seed, drift_strength=drift)
        except Exception as exc:  # noqa: BLE001
            empty = go.Figure()
            return empty, empty, empty, empty, empty, empty, empty, empty, f"後端錯誤：{exc}", "（無法取得）", []
        try:  # AC-6 fwer 較重（permutation/block-bootstrap）→ 獨立 try + 記憶化，失敗不拖垮其餘圖
            _k = (dataset, seed, drift)
            if _k not in _fwer_memo:
                if len(_fwer_memo) > 16:
                    _fwer_memo.clear()  # 有界，避免長跑無限增長
                _fwer_memo[_k] = fetch_fwer(base_url, dataset_id=dataset, seed=seed, drift_strength=drift)
            fw_fig = build_fwer_figure(_fwer_memo[_k])
        except Exception as exc:  # noqa: BLE001
            fw_fig = go.Figure()
            fw_fig.add_annotation(text=f"AC-6 計算失敗：{exc}", showarrow=False, xref="paper", yref="paper", x=0.5, y=0.5)
        n_alarm = sum(c["is_alarm"] for c in analysis["campaigns"])
        status = f"共 {analysis['n_campaigns']} 段產品，{n_alarm} 段告警，換產品後回歸段＝{analysis['reentry_campaigns']}"
        vs = analysis.get("variables", [])
        monitored = f"監控 {len(vs)} 個製程參數：{'、'.join(vs)}" if vs else "（此資料未提供參數清單）"
        spc_opts = [{"label": v, "value": v} for v in vs] + [{"label": "全部(標準化)", "value": "__all__"}]
        cid = int(contrib_cid) if contrib_cid is not None else 4
        return (
            build_health_figure(analysis),
            build_subscore_figure(analysis),
            build_contribution_figure(contrib, cid),
            build_timeline_figure(timeline),
            build_spc_figure(series, spc_var or (vs[0] if vs else "__all__")),
            build_softsensor_figure(soft),
            build_yhealth_figure(yh),
            fw_fig,
            status,
            monitored,
            spc_opts,
        )

    return app


app = create_app()


if __name__ == "__main__":  # pragma: no cover
    app.run(host="127.0.0.1", port=8050, debug=False)
