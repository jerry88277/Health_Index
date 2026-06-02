"""FastAPI 後端：判斷鏈的 REST 封裝。

啟動（地端）：``uvicorn health_index.api.server:app --port 8000``
端點：GET /health（健康檢查）、GET /datasets、POST /analyze（跑判斷鏈→per-campaign 健康度）。

範圍誠實標記（Rule 12）：本 MVP 實作 functional_design §5 的 /datasets + /analyze（彙總式），加 /health
煙霧端點。**尚未實作**：/baseline、GET /analyze/{job}/health（時間軸）、/analyze/{job}/contribution
（RBC）、/crossval——列 M8（前端時間軸）/ M9（cross-validation）待辦，不宣稱完整覆蓋 §5。

MVP：資料源為合成連續製程（真實 TEP/PRONTO/Gas adapter 待資料就緒後加入同介面）。
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException

from .. import __version__
from ..adapters import synthetic as syn
from ..health import HealthIndex, detect_reentry_campaigns
from ..interface import CAMPAIGN_ID, GRADE_LABEL, MODE, Mode, ProcessDataset
from ..preprocess import segment as seg
from .schemas import AnalyzeRequest, AnalyzeResponse, CampaignResult, DatasetInfo

app = FastAPI(title="Health_Index API", version=__version__)

_DATASETS = {"synthetic": "合成連續製程（grade A→B→A→C→A，注入隱性飄移）"}


@app.get("/health")
def health() -> dict:
    """健康檢查（啟動手冊煙霧測試用）。"""
    return {"status": "ok", "version": __version__}


@app.get("/datasets", response_model=list[DatasetInfo])
def datasets() -> list[DatasetInfo]:
    return [DatasetInfo(id="synthetic", name=_DATASETS["synthetic"], n_vars=10)]


@app.post("/analyze", response_model=AnalyzeResponse)
def analyze(req: AnalyzeRequest) -> AnalyzeResponse:
    """跑判斷鏈：合成資料→分段→golden-A 上 fit Health Index→per-campaign 健康度與告警。"""
    if req.dataset_id not in _DATASETS:
        raise HTTPException(status_code=404, detail=f"未知資料集: {req.dataset_id}")
    ds, gt = syn.generate(seed=req.seed, drift_strength=req.drift_strength)
    cols = list(ds.x_columns)
    fr = seg.segment(ds)
    ds_seg = ProcessDataset(frame=fr, x_columns=ds.x_columns, name="synthetic")

    Xg = ds.frame.loc[gt.golden_mask, cols].to_numpy()
    hi = HealthIndex().fit(Xg)
    reentry = detect_reentry_campaigns(ds_seg)

    campaigns: list[CampaignResult] = []
    for cid in sorted(int(c) for c in fr[CAMPAIGN_ID].unique()):
        sub = fr[(fr[CAMPAIGN_ID] == cid) & (fr[MODE] == Mode.STEADY.value)]
        if sub.empty:
            continue
        X = sub[cols].to_numpy()
        ss = hi.subscores(X)
        campaigns.append(
            CampaignResult(
                campaign_id=cid,
                grade=str(sub[GRADE_LABEL].iloc[0]),
                is_reentry=cid in reentry,
                health_index=round(hi.health_index(X), 4),
                is_alarm=hi.is_alarm(X),
                subscores={k: round(v, 4) for k, v in ss.items()},
            )
        )
    return AnalyzeResponse(
        dataset_id=req.dataset_id,
        n_campaigns=len(campaigns),
        reentry_campaigns=reentry,
        campaigns=campaigns,
    )
