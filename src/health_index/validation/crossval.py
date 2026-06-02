"""cross-validation runner：固定偵測邏輯 × 多組態 → 檢核成功判準（AC-1/2/3）。

紅隊 D2/H2：須證明「同一偵測邏輯（**零 per-config 調參**）在多種條件下都成立」，而非貼合
單一組態。本 runner 在多組合成組態（不同維度 p、噪聲、drift 強度、seed）上跑**同一個**
HealthIndex（預設 config，不調參），檢核：
- **AC-1**：golden-A Health Index 高（健康）。
- **AC-2**：隱性 drift 被判不健康，且**單變數 3σ SPC 對其近乎全盲**（早於/勝過 SPC）。
- **AC-3**：drift 段 Health Index 明顯低於乾淨換線回歸（區分乾淨回歸 vs 殘留飄移）。

範圍誠實標記（Rule 12，紅隊精準化）：本 runner 證明的是「**單一合成 DGP（線性潛因子+列範數
守恆）內的超參 robustness**」——所有組態共用同一生成機制，僅換 seed/p/noise/drift。這**排除
了對單一 seed/維度的過擬合**，但**不等於跨 DGP / 真實製程的外部泛化**（不同 covariance 結構、
非線性、自相關均未涵蓋）。完整 **AC-4「真實集(TEP/PRONTO/Gas)不退化」需下載真實資料**
（Dataverse API + RData 解析 + 語意映射，非平凡），列 backlog——**不宣稱已達成 AC-4**。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..adapters import synthetic as syn
from ..health import HealthIndex

# 刻意多樣化的組態網格（不同 p/noise/drift/seed）；同一 HealthIndex 預設 config 跑全部。
DEFAULT_GRID: list[dict] = [
    {"seed": 5, "drift_strength": 1.2, "p": 10, "noise_sigma": 0.3, "n_per_campaign": 300},
    {"seed": 7, "drift_strength": 1.5, "p": 8, "noise_sigma": 0.2, "n_per_campaign": 300},
    {"seed": 11, "drift_strength": 1.2, "p": 12, "noise_sigma": 0.5, "n_per_campaign": 400},
    {"seed": 13, "drift_strength": 1.3, "p": 10, "noise_sigma": 0.3, "n_per_campaign": 300},
    {"seed": 17, "drift_strength": 1.5, "p": 10, "noise_sigma": 0.4, "n_per_campaign": 350},
]


@dataclass
class ACResult:
    """單一組態的成功判準檢核結果。"""

    label: str
    ac1_golden_healthy: bool
    ac2_drift_caught_spc_blind: bool
    ac3_clean_vs_drift: bool
    detail: dict = field(default_factory=dict)

    @property
    def all_pass(self) -> bool:
        return self.ac1_golden_healthy and self.ac2_drift_caught_spc_blind and self.ac3_clean_vs_drift


def evaluate_configuration(
    *,
    seed: int,
    drift_strength: float = 1.2,
    p: int = 10,
    noise_sigma: float = 0.3,
    n_per_campaign: int = 300,
) -> ACResult:
    """在一組合成組態上跑固定 HealthIndex 並檢核 AC-1/2/3。"""
    ds, gt = syn.generate(
        seed=seed, drift_strength=drift_strength, p=p, noise_sigma=noise_sigma, n_per_campaign=n_per_campaign
    )
    cols = list(ds.x_columns)
    Xg = ds.frame.loc[gt.golden_mask, cols].to_numpy()
    a, b, _ = gt.campaign_bounds[2]  # 乾淨 re-entry A
    Xc = ds.frame.iloc[a:b][cols].to_numpy()
    Xd = ds.frame.loc[gt.drift_mask, cols].to_numpy()

    hi = HealthIndex().fit(Xg)  # 預設 config，零 per-config 調參
    thr = hi.config.hi_alarm_threshold
    h_g, h_c, h_d = hi.health_index(Xg), hi.health_index(Xc), hi.health_index(Xd)
    gm, gs = Xg.mean(axis=0), Xg.std(axis=0)
    spc_drift = float((np.abs(Xd - gm) > 3 * gs).any(axis=1).mean())

    return ACResult(
        label=f"seed{seed}_p{p}_noise{noise_sigma}_drift{drift_strength}",
        ac1_golden_healthy=h_g > 0.8,
        ac2_drift_caught_spc_blind=(h_d < thr) and (spc_drift < 0.1),
        ac3_clean_vs_drift=h_d < h_c - 0.2,
        detail={"hi_golden": round(h_g, 3), "hi_clean": round(h_c, 3), "hi_drift": round(h_d, 3), "spc_drift": round(spc_drift, 3)},
    )


def cross_validate(grid: list[dict] | None = None) -> list[ACResult]:
    """在組態網格上逐一檢核；回傳每組態的 ACResult。"""
    return [evaluate_configuration(**cfg) for cfg in (grid if grid is not None else DEFAULT_GRID)]


def format_report(results: list[ACResult]) -> str:
    """把 cross-validation 結果渲染成 markdown 泛化報告（M9「泛化報告」交付）。

    報告抬頭即明標範圍（單一合成 DGP 內超參 robustness；真實集不退化列 backlog），避免讀者
    把「N/N 組態全過」誤讀為完整 AC-4 達成（Rule 12）。
    """
    lines = [
        "# Cross-validation 泛化報告（AC-1/2/3 跨組態）",
        "",
        "> **範圍**：單一合成 DGP（線性潛因子+列範數守恆）內的**超參 robustness**（不同 p/noise/drift/seed）。",
        "> 跨 DGP / 真實集(TEP/PRONTO/Gas)不退化**未驗**，列 backlog（需下載真實資料）——非完整 AC-4。",
        "",
        "| config | AC1 golden健康 | AC2 drift&SPC盲 | AC3 clean>drift | HI golden/clean/drift | SPC drift | 全過 |",
        "|---|:--:|:--:|:--:|---|--:|:--:|",
    ]
    # 標記用 ASCII（Y/-），避免非 cp950 字元在 Windows 預設主控台 print 時 UnicodeEncodeError。
    for r in results:
        d = r.detail
        lines.append(
            f"| {r.label} | {'Y' if r.ac1_golden_healthy else '-'} "
            f"| {'Y' if r.ac2_drift_caught_spc_blind else '-'} "
            f"| {'Y' if r.ac3_clean_vs_drift else '-'} "
            f"| {d['hi_golden']}/{d['hi_clean']}/{d['hi_drift']} "
            f"| {d['spc_drift']} | {'PASS' if r.all_pass else 'FAIL'} |"
        )
    n_pass = sum(r.all_pass for r in results)
    lines += [
        "",
        f"**{n_pass}/{len(results)} 組態 AC-1/2/3 全過**（同一 HealthIndex 預設 config，零 per-config 調參）。",
    ]
    return "\n".join(lines)
