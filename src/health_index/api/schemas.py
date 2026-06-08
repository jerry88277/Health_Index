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
    health_lo: float = 0.0  # 健康分數 bootstrap 信賴帶下界（5 百分位；不確定度）
    health_hi: float = 0.0  # 健康分數 bootstrap 信賴帶上界（95 百分位）


class AnalyzeResponse(BaseModel):
    dataset_id: str
    n_campaigns: int
    reentry_campaigns: list[int]
    campaigns: list[CampaignResult]
    variables: list[str] = []  # 監控的製程參數欄名（供前端「監控參數有哪些」）


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


class SeriesResponse(BaseModel):
    """逐樣本原始製程參數時序 + golden 3σ 單變數管制線（SPC 視圖；示範隱性飄移對 SPC 隱形）。"""

    dataset_id: str
    variables: list[str]
    series: dict             # var -> 逐樣本原始值 list[float]
    spc_upper: dict          # var -> golden mean + 3σ
    spc_lower: dict          # var -> golden mean - 3σ
    campaigns: list[CampaignSpan]


class YHealthCampaign(BaseModel):
    """單一 campaign 的 Y 分布健康（Y-MSPC：T²/SPE on 品質 Y）。"""

    campaign_id: int
    grade: str
    is_reentry: bool
    y_health: float       # 1−Y 異常率（1=Y 分布健康）
    y_flagged: bool       # Y 分布是否顯著偏離 golden（如換產品 G/H 比例變）


class YHealthResponse(BaseModel):
    """Y 分布健康（Y-MSPC）。多維品質才有意義；純量品質資料集 available=False。"""

    dataset_id: str
    available: bool
    quality_vars: list[str]
    campaigns: list[YHealthCampaign]
    note: str = ""


class SoftSensorResponse(BaseModel):
    """L3 軟測量：逐樣本預測量測 Ŷ + 可信帶 + 實際 Y（量測值偏移視圖）。"""

    dataset_id: str
    yhat: list[float]               # 逐樣本 GPR 預測 Ŷ
    band_half: list[float]          # 逐樣本可信帶半寬（CP 半寬，或退回 2×GPR 後驗 std）
    y_actual: list                  # 實際 Y（有觀測處為 float，否則 None）
    cp_available: bool              # 是否以 Conformal Prediction 可信帶（標籤足量）
    band_kind: str                  # "CP" 或 "GPR_std"（誠實標可信帶來源）
    y_delay_steps: int = 0          # 估計 X→Y 延遲步數（0=資料列對齊/無可復原延遲，映射以 X(t−d) 訓練）
    campaigns: list[CampaignSpan]


class FwerCampaign(BaseModel):
    """單一 campaign 的 AC-6 決策（Holm over L1/L2/L4 對 golden null 的 p-value）。"""

    campaign_id: int
    grade: str
    is_reentry: bool
    fwer_alarm: bool          # AC-6 單一決策點：family 內任一層拒絕虛無即告警
    pvalues: dict[str, float] # 各層 p-value（L1/L2/L4；越小越異常）
    rejected: list[str]       # Holm 校正後被拒絕（判異常）的層


class FwerResponse(BaseModel):
    """AC-6 per-campaign fwer_alarm（保時序情境下隱性飄移的主偵測路徑；融合 HI 可能不過閾）。"""

    dataset_id: str
    alpha: float
    campaigns: list[FwerCampaign]
