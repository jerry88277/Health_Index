"""API 請求/回應 schema（pydantic）。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class DatasetInfo(BaseModel):
    id: str
    name: str
    n_vars: int


class AnalyzeRequest(BaseModel):
    dataset_id: str = "synthetic"
    seed: int = Field(5, ge=0)  # numpy default_rng 要求非負（負值→422 而非 500）
    drift_strength: float = Field(1.2, gt=0, le=100)  # >0，上界防 inf/極端值


class CampaignResult(BaseModel):
    campaign_id: int
    grade: str
    is_reentry: bool
    health_index: float
    is_alarm: bool
    subscores: dict[str, float]


class AnalyzeResponse(BaseModel):
    dataset_id: str
    n_campaigns: int
    reentry_campaigns: list[int]
    campaigns: list[CampaignResult]


class CampaignSpan(BaseModel):
    """時間軸上一個 campaign 的位置區間（end 為 exclusive）。"""

    campaign_id: int
    start: int
    end: int
    grade: str


class TimelineResponse(BaseModel):
    """逐樣本 T²/SPE/GSI 時間軸 + 控制限 + campaign 邊界（B1）。"""

    dataset_id: str
    t2: list[float]
    spe: list[float]
    gsi: list[float]
    t2_limit: float
    spe_limit: float
    campaigns: list[CampaignSpan]


class ContributionVar(BaseModel):
    """單一變數的肇因：RBC 強度 + 對照其單變數 3σ 越界率（證 SPC 盲）。"""

    variable: str
    rbc: float
    spc_exceedance: float


class CampaignContribution(BaseModel):
    """一個 campaign 的 top-k 肇因變數排序（RBC 由高到低）。"""

    campaign_id: int
    grade: str
    is_reentry: bool
    top_variables: list[ContributionVar]


class ContributionResponse(BaseModel):
    """per-campaign RBC 肇因分解（B1，指出哪個參數帶飄移）。"""

    dataset_id: str
    campaigns: list[CampaignContribution]
