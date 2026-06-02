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
