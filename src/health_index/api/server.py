"""FastAPI 後端：判斷鏈的 REST 封裝。

啟動（地端）：``uvicorn health_index.api.server:app --port 8000``
端點：
- GET  /health（健康檢查）
- GET  /datasets
- POST /analyze（判斷鏈→per-campaign 健康度/告警/re-entry）
- POST /timeline（逐樣本 T²/SPE/GSI + 控制限 + campaign 邊界；B1）
- POST /contribution（per-campaign RBC 肇因排序 + 單變數 3σ 越界率對照；B1）

命名偏離誠實標記（Rule 12）：functional_design §5 原訂 ``GET /analyze/{job}/health`` 與
``/contribution``；本 MVP **無狀態**（請求帶 seed/drift 重算、無 job 持久層）故改為無路徑段的
``POST /timeline`` / ``POST /contribution``。**尚未實作**：/baseline、Ŷ vs Y 軟測量端點、/crossval。

MVP：資料源為合成連續製程（真實 TEP/PRONTO/Gas adapter 待資料就緒後加入同介面）。
"""

from __future__ import annotations

import numpy as np
from fastapi import FastAPI, HTTPException

from .. import __version__
from ..adapters import synthetic as syn
from ..health import HealthIndex, detect_reentry_campaigns
from ..interface import CAMPAIGN_ID, GRADE_LABEL, MODE, Mode, ProcessDataset
from ..preprocess import segment as seg
from .schemas import (
    AnalyzeRequest,
    AnalyzeResponse,
    CampaignContribution,
    CampaignResult,
    CampaignSpan,
    ContributionResponse,
    ContributionVar,
    DatasetInfo,
    SeriesResponse,
    SoftSensorResponse,
    TimelineResponse,
)
from ..detectors.soft_sensor import SoftSensor
from ..interface import Y_VALUE

app = FastAPI(title="Health_Index API", version=__version__)

_DATASETS = {"synthetic": "合成連續製程（grade A→B→A→C→A，注入隱性飄移）"}


@app.get("/health")
def health() -> dict:
    """健康檢查（啟動手冊煙霧測試用）。"""
    return {"status": "ok", "version": __version__}


@app.get("/datasets", response_model=list[DatasetInfo])
def datasets() -> list[DatasetInfo]:
    return [DatasetInfo(id="synthetic", name=_DATASETS["synthetic"], n_vars=10)]


def _prepare(req: AnalyzeRequest):
    """共用前置：驗資料集→generate→segment→golden-A 上 fit HealthIndex（凍結）。

    Returns: (ds, gt, fr, ds_seg, cols, hi)。/analyze、/timeline、/contribution 共用同一
    凍結模型，確保三端點對同一 request 看到一致的判斷鏈（薄封裝，零重算分歧，Rule 3）。
    Raises: HTTPException(404) 未知資料集。
    """
    if req.dataset_id not in _DATASETS:
        raise HTTPException(status_code=404, detail=f"未知資料集: {req.dataset_id}")
    ds, gt = syn.generate(seed=req.seed, drift_strength=req.drift_strength)
    cols = list(ds.x_columns)
    fr = seg.segment(ds)
    ds_seg = ProcessDataset(frame=fr, x_columns=ds.x_columns, name="synthetic")
    Xg = ds.frame.loc[gt.golden_mask, cols].to_numpy()
    hi = HealthIndex().fit(Xg)
    return ds, gt, fr, ds_seg, cols, hi


@app.post("/analyze", response_model=AnalyzeResponse)
def analyze(req: AnalyzeRequest) -> AnalyzeResponse:
    """跑判斷鏈：合成資料→分段→golden-A 上 fit Health Index→per-campaign 健康度與告警。"""
    _ds, _gt, fr, ds_seg, cols, hi = _prepare(req)
    reentry = detect_reentry_campaigns(ds_seg)

    campaigns: list[CampaignResult] = []
    for cid in sorted(int(c) for c in fr[CAMPAIGN_ID].unique()):
        sub = fr[(fr[CAMPAIGN_ID] == cid) & (fr[MODE] == Mode.STEADY.value)]
        if sub.empty:
            continue
        X = sub[cols].to_numpy()
        ss = hi.subscores(X)
        lo, hi_ = _health_band(hi, X)
        campaigns.append(
            CampaignResult(
                campaign_id=cid,
                grade=str(sub[GRADE_LABEL].iloc[0]),
                is_reentry=cid in reentry,
                health_index=round(hi.health_index(X), 4),
                is_alarm=hi.is_alarm(X),
                subscores={k: round(v, 4) for k, v in ss.items()},
                health_lo=lo,
                health_hi=hi_,
            )
        )
    return AnalyzeResponse(
        dataset_id=req.dataset_id,
        n_campaigns=len(campaigns),
        reentry_campaigns=reentry,
        campaigns=campaigns,
        variables=cols,
    )


def _health_band(hi, X, *, B: int = 10, seed: int = 0) -> tuple[float, float]:
    """健康分數的 bootstrap 信賴帶（5/95 百分位）——融合點分數的不確定度（紅隊：點估非確定性）。

    對窗內樣本有放回重抽 B 次、各算 health_index，取百分位。B 偏小以控線上成本（Rule 6）。
    """
    rng = np.random.default_rng(seed)
    n = len(X)
    boots = np.array([hi.health_index(X[rng.choice(n, size=n, replace=True)]) for _ in range(B)])
    return round(float(np.percentile(boots, 5)), 4), round(float(np.percentile(boots, 95)), 4)


@app.post("/softsensor", response_model=SoftSensorResponse)
def softsensor(req: AnalyzeRequest) -> SoftSensorResponse:
    """L3 軟測量：GPR 以 golden (X→Y) 訓練，逐樣本預測 Ŷ + 可信帶 + 實際 Y（量測值偏移視圖）。

    可信帶：標籤足量時用 Conformal Prediction（有限樣本覆蓋保證）；標籤稀少（synthetic Y 稀疏，
    < cp_min_calibration）則退回 2×GPR 後驗 std，並以 band_kind 誠實標來源（紅隊 H1 雙路）。
    用途：drift 段 X→Y 映射偏移 → Ŷ 偏離實際 Y、落出可信帶＝量測值層飄移 / Ŷ 不可信。
    """
    _ds, gt, fr, _ds_seg, cols, hi = _prepare(req)
    Xg = _ds.frame.loc[gt.golden_mask, cols].to_numpy()
    yg = _ds.frame.loc[gt.golden_mask, Y_VALUE].to_numpy()
    ss = SoftSensor(hi.config).fit(Xg, yg)
    ss.calibrate_cp(Xg, yg)

    X = fr[cols].to_numpy()
    yhat, std = ss.predict(X, return_std=True)
    if ss.cp_available:
        band_half = np.full(len(X), float(ss.cp_q_))
        kind = "CP"
    else:
        band_half = 2.0 * std
        kind = "GPR_std"
    y_actual = fr[Y_VALUE].to_numpy()
    spans = [CampaignSpan(campaign_id=c, start=s, end=e, grade=g) for c, s, e, g in _campaign_spans(fr, cols)]
    return SoftSensorResponse(
        dataset_id=req.dataset_id,
        yhat=[round(float(v), 4) for v in yhat],
        band_half=[round(float(v), 4) for v in band_half],
        y_actual=[None if not np.isfinite(v) else round(float(v), 4) for v in y_actual],
        cp_available=ss.cp_available,
        band_kind=kind,
        campaigns=spans,
    )


def _campaign_spans(fr, cols) -> list[tuple[int, int, int, str]]:
    """回傳 [(campaign_id, start_pos, end_pos_exclusive, grade)]，依時間序位置切。

    不變式：假設每個 campaign 在序列中**連續不交錯**（synthetic 與 ruptures 切段成立）。若真實
    資料同 grade 交錯出現，min..max 區間會吞入中間段——屆時須改用逐段邊界（M-later）。
    """
    camp_ids = fr[CAMPAIGN_ID].to_numpy()
    grades = fr[GRADE_LABEL].to_numpy()
    spans: list[tuple[int, int, int, str]] = []
    for cid in sorted(int(c) for c in np.unique(camp_ids)):
        pos = np.where(camp_ids == cid)[0]
        spans.append((cid, int(pos.min()), int(pos.max()) + 1, str(grades[pos[0]])))
    return spans


@app.post("/timeline", response_model=TimelineResponse)
def timeline(req: AnalyzeRequest) -> TimelineResponse:
    """逐樣本 T²/SPE/GSI（全序列原始順序）+ 控制限 + campaign 邊界。

    供前端時間軸圖：看出隱性飄移在序列中**何時**讓 SPE 越限（campaign 級彙總看不到的時序）。
    薄封裝（Rule 3）：直接用 /analyze 同一凍結 MSPC 模型逐樣本算，零重算分歧。
    """
    _ds, _gt, fr, _ds_seg, cols, hi = _prepare(req)
    m = hi.mspc_
    X = fr[cols].to_numpy()  # 全序列、原始時間順序（含 transition，忠實呈現時序）
    spans = [CampaignSpan(campaign_id=c, start=s, end=e, grade=g) for c, s, e, g in _campaign_spans(fr, cols)]
    return TimelineResponse(
        dataset_id=req.dataset_id,
        t2=[round(float(v), 4) for v in m.t2(X)],
        spe=[round(float(v), 4) for v in m.spe(X)],
        gsi=[round(float(v), 4) for v in m.gsi(X)],
        t2_limit=round(float(m.t2_lim_), 4),
        spe_limit=round(float(m.spe_lim_), 4),
        campaigns=spans,
    )


@app.post("/series", response_model=SeriesResponse)
def series(req: AnalyzeRequest) -> SeriesResponse:
    """逐樣本原始製程參數時序 + golden-A 的單變數 3σ 管制線（SPC 視圖）。

    用途：示範**隱性飄移對單變數 SPC 隱形**——drift 段每個參數多半仍在各自 3σ 管制線內（單看正常），
    但 /analyze 的融合健康度已告警。薄封裝（Rule 3）：管制線＝golden 各欄 mean±3σ，原始值直接出。
    """
    _ds, gt, fr, _ds_seg, cols, hi = _prepare(req)
    X = fr[cols].to_numpy()
    Xg = _ds.frame.loc[gt.golden_mask, cols].to_numpy()
    gm, gs = Xg.mean(axis=0), Xg.std(axis=0)
    spans = [CampaignSpan(campaign_id=c, start=s, end=e, grade=g) for c, s, e, g in _campaign_spans(fr, cols)]
    return SeriesResponse(
        dataset_id=req.dataset_id,
        variables=cols,
        series={c: [round(float(v), 4) for v in X[:, j]] for j, c in enumerate(cols)},
        spc_upper={c: round(float(gm[j] + 3 * gs[j]), 4) for j, c in enumerate(cols)},
        spc_lower={c: round(float(gm[j] - 3 * gs[j]), 4) for j, c in enumerate(cols)},
        campaigns=spans,
    )


@app.post("/contribution", response_model=ContributionResponse)
def contribution(req: AnalyzeRequest, top_k: int = 5) -> ContributionResponse:
    """per-campaign 逐變數 RBC 肇因排序（指出**哪個參數**帶飄移）+ 單變數 3σ 越界率對照。

    RBC（Alcala & Qin 2009）為「定位非因果」；多方向漂移有殘留 smearing（紅隊 H3）。每變數同時
    回報其單變數 3σ 越界率作對照：**隱性飄移**的 top-RBC 變數其越界率近 0（SPC 盲）——這就是本
    index 的核心區辨（單變數 SPC 看不到、多變量 RBC 點得出），前端據此呈現。
    （註：grade 均值位移段的 SPC 越界率視位移幅度而定、不必然高；RBC 對「均值位移 vs 關係漂移」
    不可直接互比，故此對照僅對隱性飄移段下「SPC 盲」結論。）
    """
    _ds, gt, fr, ds_seg, cols, hi = _prepare(req)
    m = hi.mspc_
    Xg = _ds.frame.loc[gt.golden_mask, cols].to_numpy()
    gm, gs = Xg.mean(axis=0), Xg.std(axis=0) + 1e-9
    reentry = set(detect_reentry_campaigns(ds_seg))
    Xall = fr[cols].to_numpy()
    k = max(1, min(int(top_k), len(cols)))

    out: list[CampaignContribution] = []
    for cid, s, e, grade in _campaign_spans(fr, cols):
        Xc = Xall[s:e]
        rbc = m.rbc_spe(Xc).mean(axis=0)
        spc = (np.abs(Xc - gm) > 3 * gs).mean(axis=0)
        order = np.argsort(rbc)[::-1][:k]
        top = [
            ContributionVar(variable=cols[j], rbc=round(float(rbc[j]), 4), spc_exceedance=round(float(spc[j]), 4))
            for j in order
        ]
        out.append(CampaignContribution(campaign_id=cid, grade=grade, is_reentry=cid in reentry, top_variables=top))
    return ContributionResponse(dataset_id=req.dataset_id, campaigns=out)
