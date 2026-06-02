"""單一超參數真相（Health_Index）。

所有偵測器/前處理的超參集中於此（紅隊 D1：單一 config 治理）。
- 預設值多為起手值，將於 M1 後在 TEP ground-truth 上掃描定值；標『勿動除非…』。
- 含 RNG 者一律經 ``random_state``，確保可重現（NFR-1/5）。
- 固定 seed＝可重現，**不等於**統計確定性（紅隊 H7）：permutation/CP 的 p-value 仍有
  蒙地卡羅變異，需以容忍帶斷言（見 tests），且優先採解析門檻。

不變式：所有欄位皆為純量超參，不在此放資料或模型物件。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    """五維度判斷鏈的全域超參（frozen，避免執行期被偷改）。"""

    # --- 全域可重現 ---
    random_state: int = 42  # 所有 RNG（permutation/CP/FastMCD）共用；勿動除非做 seed 敏感度分析

    # --- L1 資料品質 ---
    mcd_support_fraction: float = 0.75   # FastMCD 子集比例；勿動除非高污染率
    dqi_x_threshold_factor: float = 3.0  # DQI_x 門檻 = factor × LOO trimmed mean（AVM 慣例）

    # --- 前處理：分段/對齊 ---
    ssd_penalty: float = 10.0     # ruptures PELT penalty；須 TEP 掃描定值，勿硬信此預設
    transition_width: int = 10    # 換線/維修後 settling 段長度（排除於 golden-A baseline）
    cpd_min_size: int = 12        # ruptures 變點偵測最小段長（取代硬編 magic；紅隊建議）
    x_lag_order: int = 2          # DPCA 時間落後階數；過大惡化 n/p（紅隊 H5）

    # --- L2 MSPC ---
    pca_var_explained: float = 0.90  # 保留主成分的累積變異比例
    mspc_alpha: float = 0.01         # T²/SPE 控制限顯著水準
    min_samples_per_dim: int = 10    # 硬 gate：n ≥ factor·p(l+1)，不足退靜態 PCA（紅隊 H5）

    # --- L3 軟測量/可信度 ---
    cp_alpha: float = 0.10        # Conformal 風險預算（目標覆蓋率 1−α）
    cp_min_calibration: int = 200  # split-CP 上線最小 calibration 樣本；不足走 GSI/ICAD（紅隊 H1）

    # --- L4 漂移 ---
    drift_window: int = 60          # 漂移偵測窗大小（與檢定力下限相關，AC-2）
    ks_alpha: float = 0.01          # KS first-pass 顯著水準（廉價 1D 哨兵）
    mmd_bandwidth: float = 1.0      # MMD RBF bandwidth；或改 MMDAgg kernel set
    sinkhorn_eps: float = 0.1       # Sinkhorn 熵正則 ε；小→保 OT 幾何但貴/樣本需求大（紅隊 F2）
    perm_B: int = 200               # permutation 重抽次數（影響 p-value 解析度 1/(B+1)）
    drift_persistence_k: int = 2    # 連續 k 窗超標才告警，濾單點 outlier

    # --- 融合/決策 ---
    fwer_method: str = "holm"  # 多重比較校正法；單一融合決策點之外的 type-I 保險（紅隊 N2）


DEFAULT = Config()
"""預設組態單例；正式跑須以 TEP 掃描值覆寫並版本化。"""
