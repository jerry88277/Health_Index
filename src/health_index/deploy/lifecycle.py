"""G4 模型生命週期：per-product 模型庫 + 模型時效評估（重建基準觸發）+ 哨兵。

第一性原理（docs/deployment_plan.md §6 G4）：單一產品一個模型；製程**刻意變更**（新配方/換料）或基準
**自然老化**後須重建 golden 基準。本模組提供 (a) per-product 模型庫（目錄式，重用 bundle save/load）；
(b) 時效評估——以「現場確認為正常」的近期 golden 餵入現役模型，若仍持續判不健康 → 建議重建；
(c) 重建便利（refit + 版本替換）。

誠實邊界（Rule 12）：時效評估**無法**自動區分「基準老化」vs「真實飄移」——兩者都讓近期資料判不健康。
故輸入必須是**現場/品保確認為正常**的近期 A 段；輸出為**建議**（需人決），非自動重建（避免把真飄移
當老化而把問題基準化）。重建為高風險動作，預設不自動執行。
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import numpy as np

from ..health import HealthIndex
from .bundle import ModelBundle, build_bundle, load, save


class ModelRegistry:
    """目錄式 per-product 模型庫（單一產品一個現役模型）。"""

    def __init__(self, models_dir: str):
        self.models_dir = models_dir
        os.makedirs(models_dir, exist_ok=True)

    def _path(self, product: str) -> str:
        return os.path.join(self.models_dir, f"{product}.joblib")

    def has_model(self, product: str) -> bool:
        return os.path.exists(self._path(product))

    def list_models(self) -> list[str]:
        """已註冊產品（依檔名）。"""
        return sorted(f[:-7] for f in os.listdir(self.models_dir) if f.endswith(".joblib"))

    def save_model(self, bundle: ModelBundle) -> str:
        """存/覆蓋某產品現役模型。"""
        return save(bundle, self._path(bundle.product))

    def load_model(self, product: str, *, verify: bool = True):
        """載入產品現役模型（verify=True 走指紋重放，拒載漂移/損毀）。"""
        if not self.has_model(product):
            raise FileNotFoundError(f"模型庫無產品 '{product}' 的模型；可用: {self.list_models()}")
        return load(self._path(product), verify=verify)


@dataclass
class CurrencyReport:
    """模型時效評估結果。"""

    product: str
    n_recent: int
    recent_health: float  # 近期確認-正常 golden 的健康指標
    recent_alarm_rate: float  # 近期窗告警率（理想≈0；高＝基準與現況不符）
    recommendation: str  # "CURRENT" | "REBUILD_RECOMMENDED"
    reason: str


def assess_model_currency(
    bundle: ModelBundle,
    recent_confirmed_golden: np.ndarray,
    *,
    window: int | None = None,
    alarm_rate_max: float = 0.3,
) -> CurrencyReport:
    """以**現場確認為正常**的近期 golden 評估現役模型是否仍貼合現況。

    若近期確認-正常資料被現役模型持續判不健康（告警率 > alarm_rate_max），代表基準已與現況不符
    → 建議重建（**需人決**：可能是基準老化、也可能輸入其實不正常）。

    Args:
        bundle: 現役模型 bundle。
        recent_confirmed_golden: 近期、**經現場確認為正常**的 A 段資料。
        window: 評估窗長（None→config.drift_window）。
        alarm_rate_max: 告警率上限；超過＝建議重建。

    Returns:
        CurrencyReport（recommendation 為建議，非自動重建）。
    """
    from .runner import RunnerState, poll_once
    from .sources import FrameSource
    import pandas as pd

    hi = bundle.health
    w = int(window or bundle.config.drift_window)
    R = np.asarray(recent_confirmed_golden, dtype=float)
    src = FrameSource(pd.DataFrame(R, columns=list(bundle.x_columns)), bundle.x_columns)
    scores, _ = poll_once(bundle, src, RunnerState(), window=w, persistence_k=1, compute_fwer=False)
    if not scores:
        return CurrencyReport(bundle.product, len(R), float("nan"), float("nan"), "CURRENT",
                              f"近期資料不足一個窗（n={len(R)}<{w}），無法評估時效")
    health = float(np.mean([s.health_index for s in scores]))
    alarm_rate = float(np.mean([s.raw_alarm for s in scores]))
    if alarm_rate > alarm_rate_max:
        rec, reason = "REBUILD_RECOMMENDED", (
            f"近期確認-正常資料告警率 {alarm_rate:.2f} > {alarm_rate_max} → 基準與現況不符；"
            "請確認資料確為正常後重建基準（亦可能為真實飄移，需人判）"
        )
    else:
        rec, reason = "CURRENT", f"近期確認-正常資料告警率 {alarm_rate:.2f} ≤ {alarm_rate_max} → 基準仍貼合"
    return CurrencyReport(bundle.product, len(R), round(health, 4), round(alarm_rate, 4), rec, reason)


def rebuild_model(
    registry: ModelRegistry,
    product: str,
    new_golden: np.ndarray,
    x_columns,
    *,
    created_at: str,
    y_health: object | None = None,
) -> ModelBundle:
    """以新 golden 重建某產品基準並替換現役模型（高風險：覆蓋舊基準，須人觸發）。

    Args:
        registry: 模型庫。
        product: 產品識別。
        new_golden: 新 golden 基準（製程刻意變更後的新正常，或老化後重採的正常段）。
        x_columns: X 欄序。
        created_at: 重建時間（git 時間權威，呼叫端提供）。

    Returns:
        新 ModelBundle（已存入模型庫）。
    """
    Xg = np.asarray(new_golden, dtype=float)
    bundle = build_bundle(product, HealthIndex().fit(Xg), x_columns, golden=Xg, created_at=created_at, y_health=y_health)
    registry.save_model(bundle)
    return bundle
