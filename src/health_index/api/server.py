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
from ..health import HealthIndex, _holm_reject, detect_reentry_campaigns
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
    FwerCampaign,
    FwerResponse,
    SeriesResponse,
    SoftSensorResponse,
    TimelineResponse,
    YHealthCampaign,
    YHealthResponse,
)
from ..adapters import tep
from ..detectors.mspc import MSPCModel
from ..detectors.soft_sensor import SoftSensor
from ..interface import Y_VALUE
from ..preprocess.align import delay_align_train, estimate_delay

app = FastAPI(title="Health_Index API", version=__version__)

_DATASETS = {
    "synthetic": "合成連續製程（grade A→B→A→C→A，注入隱性飄移）",
    "tep": "Tennessee Eastman 真實連續製程（Mode1/2/3 模態切換 + 注入隱性飄移；iid 重抽）",
    "tep_tp": "TEP（保時序）：連續不重抽、保真實自相關；隱性飄移由 AC-6/L2 SPE 偵測（②）",
}
_DATASET_NVARS = {"synthetic": 10, "tep": 22, "tep_tp": 22}


@app.get("/health")
def health() -> dict:
    """健康檢查（啟動手冊煙霧測試用）。"""
    return {"status": "ok", "version": __version__}


@app.get("/datasets", response_model=list[DatasetInfo])
def datasets() -> list[DatasetInfo]:
    return [DatasetInfo(id=k, name=v, n_vars=_DATASET_NVARS[k]) for k, v in _DATASETS.items()]


def _prepare(req: AnalyzeRequest):
    """共用前置：驗資料集→generate→segment→golden-A 上 fit HealthIndex（凍結）。

    Returns: (ds, gt, fr, ds_seg, cols, hi)。/analyze、/timeline、/contribution 共用同一
    凍結模型，確保三端點對同一 request 看到一致的判斷鏈（薄封裝，零重算分歧，Rule 3）。
    Raises: HTTPException(404) 未知資料集。
    """
    if req.dataset_id not in _DATASETS:
        raise HTTPException(status_code=404, detail=f"未知資料集: {req.dataset_id}")
    if req.dataset_id in ("tep", "tep_tp"):
        # TEP：drift_strength 為注入比例（0–1，打亂變數佔比）；clamp 上界。tep_tp＝保時序（②）
        ds, gt = tep.generate(
            seed=req.seed,
            drift_strength=min(req.drift_strength, 1.0),
            time_preserving=(req.dataset_id == "tep_tp"),
        )
    else:
        ds, gt = syn.generate(seed=req.seed, drift_strength=req.drift_strength)
    cols = list(ds.x_columns)
    fr = seg.segment(ds)
    ds_seg = ProcessDataset(frame=fr, x_columns=ds.x_columns, name=req.dataset_id)
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


@app.post("/fwer", response_model=FwerResponse)
def fwer(req: AnalyzeRequest) -> FwerResponse:
    """AC-6 單一決策點：per-campaign ``fwer_alarm``（Holm 校正 L1/L2/L4 對 golden null 的 p-value）。

    為何獨立端點（非併入 /analyze）：fwer p-value 走 permutation/block-bootstrap，比融合分數重，獨立
    端點避免拖慢 /analyze 熱路徑（Rule 6）。**保時序 TEP（tep_tp）情境的隱性飄移由此偵測**——融合
    Health Index 受權重稀釋可能不過閾（drift HI≈0.85>0.6），但 AC-6/L2 SPE 抓得到；前端據此誠實標示，
    避免「融合分數沒掉＝沒抓到」的誤讀。
    """
    _ds, _gt, fr, ds_seg, cols, hi = _prepare(req)
    reentry = detect_reentry_campaigns(ds_seg)
    alpha = hi.config.fwer_alpha
    camps: list[FwerCampaign] = []
    for cid in sorted(int(c) for c in fr[CAMPAIGN_ID].unique()):
        sub = fr[(fr[CAMPAIGN_ID] == cid) & (fr[MODE] == Mode.STEADY.value)]
        if sub.empty:
            continue
        pv = hi.fwer_pvalues(sub[cols].to_numpy())
        rej = _holm_reject(pv, alpha)
        camps.append(
            FwerCampaign(
                campaign_id=cid,
                grade=str(sub[GRADE_LABEL].iloc[0]),
                is_reentry=cid in reentry,
                fwer_alarm=any(rej.values()),
                pvalues={k: round(float(v), 4) for k, v in pv.items()},
                rejected=[k for k, r in rej.items() if r],
            )
        )
    return FwerResponse(dataset_id=req.dataset_id, alpha=alpha, campaigns=camps)


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

    X→Y 延遲對齊（③）：lab 量測 Y 相對製程 X 常有輸送/分析延遲，先以 ``estimate_delay`` 自 golden
    估計延遲 d，再以 ``delay_align_train`` 取 (X(t−d), Y(t)) 對訓練 GPR——避免錯位污染映射（Rule 9）。
    估計 d 回報於 ``y_delay_steps``（前端 ⑥ 圖標示）。

    誠實標（Rule 12，d=0 的兩種來源不可混淆）：
      - synthetic：golden 標籤數足（common obs ≥ 2p+1），estimate_delay **真跑 R² argmax** 得 d=0
        （X、Y 同時刻由共同潛變數生成，本就列對齊）。
      - tep（預設 n_per_campaign）：golden 稀疏標籤 common obs < 2p+1，低於 estimate_delay 可靠下限，
        故回**保守 fallback 0**（非 argmax 證得；與「seg 同列取 X 與 G/H」的列對齊一致，但屬「資料不足
        放棄」而非「搜尋後確認無延遲」）。增大 n_per_campaign/降稀疏度可使其轉為真 argmax（亦得 0）。
    預測路徑：d=0 時 Ŷ(t)=f(X(t)) 與訓練域一致（精確）；若未來真實資料 d>0，此處仍以 X(t) 預測，
    Ŷ(t) 實際估計的是 Y(t+d)（latent 不一致，屆時須對齊預測域）——目前 d=0 不觸發。
    """
    _ds, gt, fr, _ds_seg, cols, hi = _prepare(req)
    Xg = _ds.frame.loc[gt.golden_mask, cols].to_numpy()
    yg = _ds.frame.loc[gt.golden_mask, Y_VALUE].to_numpy()
    d = estimate_delay(Xg, yg, max_lag=hi.config.y_max_lag)  # X→Y 延遲（步）；列對齊/標籤不足回 0
    # 不變式：estimate_delay 僅在 common obs ≥ 2p+1（且 obs−max_lag≥0）時回 d>0，而 d≤max_lag，
    # 故 delay_align_train 對齊後留存 obs ≥ common ≥ 2p+1 ≥ 2，fit 不會因觀測不足拋例外。
    Xg_al, yg_al = delay_align_train(Xg, yg, d)              # (X(t−d), Y(t)) 對齊訓練對
    ss = SoftSensor(hi.config).fit(Xg_al, yg_al)
    ss.calibrate_cp(Xg_al, yg_al)

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
        y_delay_steps=int(d),
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


@app.post("/yhealth", response_model=YHealthResponse)
def yhealth(req: AnalyzeRequest) -> YHealthResponse:
    """Y 分布健康（Y-MSPC：T²/SPE on 多維品質 Y）：每段品質分布是否偏離 golden。

    與 /softsensor（X→Y 映射健康）互補——Y-MSPC 抓「品質分布本身變了」（如換產品 G/H 比例不同），
    軟測量抓「X→Y 關係斷了」（注入 drift：Y 分布不變但映射偏）。純量品質資料集（synthetic）
    available=False（Y 分布健康需多維品質）。
    """
    _ds, gt, fr, ds_seg, cols, hi = _prepare(req)
    qcols = [c for c in fr.columns if c.startswith("yq_")]
    if not qcols:
        return YHealthResponse(
            dataset_id=req.dataset_id, available=False, quality_vars=[], campaigns=[],
            note="此資料集為純量品質；Y 分布健康(Y-MSPC)需多維品質(如 G/H)。",
        )
    reentry = set(detect_reentry_campaigns(ds_seg))
    Yall = fr[qcols].to_numpy()
    obs = np.isfinite(Yall).all(axis=1)
    m = MSPCModel().fit(Yall[np.asarray(gt.golden_mask) & obs])  # golden 觀測 Y 上 fit
    camp_ids = fr[CAMPAIGN_ID].to_numpy()
    grades = fr[GRADE_LABEL].to_numpy()
    out: list[YHealthCampaign] = []
    for cid in sorted(int(c) for c in np.unique(camp_ids)):
        Yc = Yall[(camp_ids == cid) & obs]
        rate = float(m.is_anomaly(Yc).mean()) if len(Yc) else 0.0
        out.append(YHealthCampaign(
            campaign_id=cid, grade=str(grades[camp_ids == cid][0]), is_reentry=cid in reentry,
            y_health=round(1.0 - rate, 4), y_flagged=rate > 0.5,
        ))
    return YHealthResponse(dataset_id=req.dataset_id, available=True, quality_vars=qcols, campaigns=out)


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
