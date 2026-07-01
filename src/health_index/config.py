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
    dqi_x_threshold_factor: float = 3.0  # DQI_x 門檻 = factor × MCD-support 內 90% trimmed mean
                                         # （刻意以 in-sample≈LOO 取代 AVM 原文 LOO，見 dqi_x.py docstring）

    # --- L1/L4 高維／規模穩健（桶3）---
    hd_min_n_over_p: float = 2.0     # n < 此×p → L1 啟動 PCA-score 預降維（MinCovDet 在 p≫n 靜默回奇異
                                     # 協方差、cond 爆、汙染 DQI_x 距離且不 raise，Rule 12 靜默失敗）
    hd_reduce_max_frac: float = 0.4  # 預降維維度 r ≤ floor(此×n)，確保降維後 n>2r、MCD 在 score 空間仍有效
    hd_rank_rtol: float = 1e-9       # 有效數值秩容差：特徵值 > 此×max 才算真實方向（L4 截斷近零 noise 維，
                                     # 免 per-component KS 在任意方向檢定並把 Bonferroni ×p 過度膨脹）

    # --- 前處理：分段/對齊 ---
    ssd_penalty: float = 10.0     # ruptures PELT penalty；須 TEP 掃描定值，勿硬信此預設
    transition_width: int = 10    # 換線/維修後 settling 段長度（排除於 golden-A baseline）
    cpd_min_size: int = 12        # ruptures 變點偵測最小段長（取代硬編 magic；紅隊建議）
    golden_auto_min_frac: float = 0.12  # 桶4b golden='auto' 候選段最小長度佔比（變點切段後濾過短段）
    golden_auto_ramp_max: float = 0.5   # 桶4b golden='auto' 段內 ramp 上限（標準化空間每特徵跨段漂移均值）：
                                        # 超過＝段內非平穩(暫態/漸變)，不可當乾淨基準（紅隊 A：scoring 不可靠，改最早平穩段）
    y_max_lag: int = 10           # X→Y 延遲估計搜尋上限（步）
    x_lag_order: int = 2          # DPCA 時間落後階數；過大惡化 n/p（紅隊 H5）

    # --- 特徵建構層（混合疊加；可解釋視圖，非偵測器）---
    seg_method: str = "trim"      # 段定義：trim（預設零調參）| ssd（PELT-on-raw）| wavelet（PELT-on-HF-energy）
    seg_trim_head: int = 10       # trim：丟頭樣本數（暫態 settling）
    seg_trim_tail: int = 10       # trim：丟尾樣本數
    seg_min_len: int = 20         # pseudo-run 最小長度（納入閘；短於此不成段）
    seg_min_obs_factor: float = 1.0  # 統計可靠閘：段內樣本須 ≥ factor·p 才算偏離 z（類比 min_samples_per_dim，與 seg_min_len 分離）
    seg_statistics: tuple = ("mean", "std", "min", "max", "range", "median")  # 6 統計；count→段級 metadata；mode 連續退化不提供
    seg_wavelet: str = "db4"      # wavelet 模式母小波（高頻細節能量→PELT 切點，抓振盪/高頻暫態）
    # ssd/wavelet 切點後皆復用 ssd_penalty/golden_auto_ramp_max/cpd_min_size 穩態準則（不另造門檻，紅隊 B5）

    # --- L2 MSPC ---
    pca_var_explained: float = 0.90  # 保留主成分的累積變異比例
    mspc_alpha: float = 0.01         # T²/SPE 控制限顯著水準
    min_samples_per_dim: int = 10    # 硬 gate：n ≥ factor·p(l+1)，不足退靜態 PCA（紅隊 H5）

    # --- L3 軟測量/可信度 ---
    cp_alpha: float = 0.10        # Conformal 風險預算（目標覆蓋率 1−α）
    cp_min_calibration: int = 200  # split-CP 上線最小 calibration 樣本；不足走 GSI/ICAD（紅隊 H1）
    pls_components: int = 5       # PLS 軟測量潛在成分數（上限，實際 cap 至 min(p, n_obs−1)）；軟測量潛因子
    soft_sensor_pls_min_features: int = 30   # X 維 > 此 → 選 PLS（共線/高維，GPR RBF 退化、O(n³) 貴）
    soft_sensor_pls_min_samples: int = 1000  # 觀測 > 此 → 選 PLS（GPR O(n³) 不可擴展）；否則 GPR（小資料非線性友善）

    # --- Y 健康融合（桶2b）：映射健康 ⊕ 分布健康 → 單一 0–1 ---
    y_map_scale: float = 1.0     # 映射健康 exp 衰減尺度：殘差/可信帶 比超 1 的均值越大→映射越不健康
    y_map_min_obs: int = 5       # 映射健康最少 Y 觀測數（不足回 None，誠實標不可算非靜默 0）
    y_fusion_weights: tuple = (1.0, 1.0)  # (映射健康, 分布健康) 融合權重；分布健康僅多維品質有
    y_flag_threshold: float = 0.5  # 任一 Y 健康分量 < 此 → y_flagged（安全網，類比 X 側 hard-gate；
                                   # 抓分量塌陷如換產品 dist→0，即使融合均值被另一分量稀釋未過閾）
    y_trend_z_max: float = 3.0   # 增量8：預測品質 Ŷ 窗均值相對 golden Ŷ 的水準漂移（golden-σ 單位）超此→品質飄移旗標（3σ SPC）
    y_extrap_confidence_min: float = 0.6  # 紅隊 A13：窗 confidence（域相似度）< 此 → X 離建模域＝GPR 外推（Ŷ→prior mean、z 縮小不可信為健康）→ 標 yhat_drift_reliable=False

    # --- L4 漂移 ---
    drift_window: int = 60          # 漂移偵測窗大小（與檢定力下限相關，AC-2）
    ks_alpha: float = 0.01          # KS first-pass 顯著水準（廉價 1D 哨兵）
    mmd_bandwidth: float = 1.0      # MMD RBF bandwidth；或改 MMDAgg kernel set
    sinkhorn_eps: float = 0.1       # Sinkhorn 熵正則 ε；小→保 OT 幾何但貴/樣本需求大（紅隊 F2）
    perm_B: int = 200               # permutation 重抽次數（影響 p-value 解析度 1/(B+1)）
    w_null_reps: int = 50           # Wasserstein 量級 null 的重抽次數（紅隊建議 ≥50）
    drift_block_z: float = 1.96     # L4 block-bootstrap 區塊長度估計的自相關顯著帶（PC1 ρ<z/√n→iid）；
                                    # iid 資料 → 區塊長度 1（統計等價向後相容，≈95% 走 iid 路徑）；
                                    # 強自相關（連續 TEP）→ >1 加寬 null
    drift_persistence_k: int = 2    # 連續 k 窗超標才告警，濾單點 outlier（預留，M9 接線；M6 未使用）

    # --- L5 批次軌跡 DTW（B4）---
    dtw_resample_len: int = 100   # 批次軌跡降採樣固定點數（控 O(n²) 成本，Rule 6；FastDTW 替身）
    dtw_band: float = 0.15        # Sakoe-Chiba band 比例（限 warping、再降成本）
    dtw_threshold_k: float = 2.0  # 偏移門檻 = 參考批 LOO 距離 mean + k·std（k=2 ≈ 5% 正常 FPR）

    # --- 融合/決策 ---
    fusion_severity_scale: float = 3.0  # P1：L1/L2 per-sample 標準化嚴重度 z → 健康 exp(-z/scale) 的衰減尺度；
                                        # z=3（偏離 golden 3σ）→ 健康≈0.37；取代原「超限比例」之飽和（弱飄移漏報）
    drift_scale: float = 5.0          # L4 Wasserstein z → 健康子分數的衰減尺度（exp(-z/scale)）；TEP 校準
    hi_alarm_threshold: float = 0.6   # Health Index 告警門檻（< 即告警）；須 TEP 校準
    fusion_weights: tuple = (1.0, 2.0, 1.0)  # (L1, L2, L4) 融合權重；L2 為隱性飄移主訊號加重；M9 校準
    fwer_method: str = "holm"   # 多重比較校正法標記；B3 的 _holm_reject **硬編 Holm**（未依此欄 dispatch），
                                # 其他方法（Hochberg/BH）待擴充——此欄目前僅文件性，勿誤以為可切換
    fwer_alpha: float = 0.05    # AC-6 族系錯誤率（FWER）目標水準；golden-A 誤報率須 ≤ 此值（B3）
    fwer_n_boot: int = 200      # L1/L2 窗級 p-value 的 golden bootstrap null 重抽次數（解析度 1/(B+1)）


DEFAULT = Config()
"""預設組態單例；正式跑須以 TEP 掃描值覆寫並版本化。"""
