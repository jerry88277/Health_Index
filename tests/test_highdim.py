"""桶3 高維／規模穩健 WHY 測試（Rule 9）。

marquee WHY：當樣本少於變數（p≫n），FastMCD（``MinCovDet``）**不 raise** 而**靜默**回奇異
協方差（rank<p、cond 爆、噴數值警告），下游 DQI_x 距離在 noise 子空間計算、且模型不可重現
——這是 Rule 12 的靜默失敗紅線。桶3 以 PCA-score 預降維（L1）與有效秩截斷（L4）讓問題**良定義**
並把不可解情形（變異匱乏）以 ``degraded_`` 旗標**誠實 surface**。

誠實邊界（不造假，Rule 12）：桶3 對 L1 的價值是**數值良定義＋適用性旗標**，**非**提升漂移鑑別力
（實證兩路徑 DQI 都能分離域位移，因 leading PC 仍估得準；L1 本為粗域閘，主訊號在 L2 SPE/L4）。
故下列測試斷言「奇異性已消除／旗標如實／向後相容／域閘不被降維破壞」，**不**宣稱降維讓 L1 多抓 drift。
"""

import warnings

import numpy as np
import pytest

from health_index.config import Config
from health_index.detectors.dqi_x import DQIxGate
from health_index.detectors.drift import DriftDetector
from health_index.detectors.highdim import effective_rank, reduction_plan


def _latent_hd(n, p, latent, seed, *, loadings=None, zshift=0.0):
    """潛因子高維生成：``latent`` 個潛變數經固定載荷驅動 p 維（低秩相關結構 + 小噪）。"""
    r = np.random.default_rng(seed)
    if loadings is None:
        loadings = np.random.default_rng(10_000 + seed).standard_normal((latent, p))
    Z = r.standard_normal((n, latent)) + zshift
    return Z @ loadings + 0.1 * r.standard_normal((n, p)), loadings


# ----------------------- 共用 helper 單元 -----------------------

def test_effective_rank_counts_signal_dims():
    """有效秩＝大於 rtol×max 的特徵值數；近零 noise 方向不計（截斷的數學核心）。"""
    assert effective_rank(np.array([10.0, 1.0, 1e-15, 0.0]), rtol=1e-9) == 2
    assert effective_rank(np.array([5.0, 5.0, 5.0])) == 3  # 全為真實方向
    assert effective_rank(np.array([])) == 0
    assert effective_rank(np.array([0.0, 0.0])) == 1  # 全零退化 → 至少 1（不回 0 製造除零）


def test_reduction_plan_triggers_only_when_starved():
    """n<min_n_over_p×p 才降維；r 綁 max_frac×n 確保降維後 n>2r；degraded 標變異匱乏。"""
    # p≫n：觸發，r=min(rank,floor(.4·60))=24，var 需 50>24 → degraded
    need, r, deg = reduction_plan(60, 200, rank=59, var_components=50, min_n_over_p=2.0, max_frac=0.4)
    assert need and r == 24 and deg
    # 同 n,p 但低秩（var 需 10<24）→ 不匱乏
    need, r, deg = reduction_plan(60, 200, rank=59, var_components=10, min_n_over_p=2.0, max_frac=0.4)
    assert need and r == 24 and not deg
    # n≫2p：不降維、r=p、不 degraded（向後相容路徑）
    need, r, deg = reduction_plan(2000, 30, rank=30, var_components=12, min_n_over_p=2.0, max_frac=0.4)
    assert (not need) and r == 30 and not deg


# ----------------------- L1 DQIxGate -----------------------

def test_l1_reduction_restores_mcd_validity_at_p_gg_n():
    """WHY：p≫n 時直接在 p 維估協方差必奇異（rank=n−1<p）；桶3 降維到 r 維使 n>2r、協方差滿秩。

    當有人移除降維（reduced_ 應為 True 卻變 False），MCD 退回奇異 p 維 → 本測試失敗。
    """
    n, p = 60, 200
    Xg, _ = _latent_hd(n, p, latent=5, seed=1)
    g = DQIxGate().fit(Xg)
    assert g.reduced_ is True
    assert g.r_ <= int(np.floor(0.4 * n))      # r 受 n 上限拘束
    assert n > 2 * g.r_                          # MCD 有效性前提恢復
    # 直接 p 維（桶3 前）標準化 golden 的秩 = n−1 < p（奇異，下游協方差不可逆）
    Xs = (Xg - np.median(Xg, axis=0)) / (1.4826 * np.median(np.abs(Xg - np.median(Xg, axis=0)), axis=0) + 1e-9)
    assert np.linalg.matrix_rank(Xs) < p
    # 降維工作空間 Z 滿秩 r_（奇異性已消除）
    Z = Xs @ g.reduce_V_
    assert np.linalg.matrix_rank(Z) == g.r_


def test_l1_no_singularity_warning_when_reduced():
    """WHY：桶3 前直接 p 維 MCD 噴 sklearn『not full rank/Determinant increased』奇異警告（靜默
    失敗的外顯訊號）；降維路徑應**零**此類警告（良條件）。對照組強制不降維以實證警告確實存在。"""
    n, p = 60, 200
    Xg, _ = _latent_hd(n, p, latent=5, seed=2)

    def count_singular_warnings(cfg):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            DQIxGate(cfg).fit(Xg)
        return sum("full rank" in str(x.message) or "Determinant" in str(x.message) for x in w)

    assert count_singular_warnings(Config(hd_min_n_over_p=0.0)) > 0   # 桶3 前：奇異警告
    assert count_singular_warnings(Config()) == 0                      # 桶3 後：零警告


def test_l1_degraded_flag_surfaces_variance_starvation():
    """WHY（Rule 12 誠實 surface）：當 golden 內在維度高、90% 變異需要的成分數 > 樣本能容納的 r，
    桶3 必須把 degraded_ 標 True（坦承『即使降維仍放不下全部真實變異』），而非靜默截斷假裝完好。"""
    n, p = 60, 200
    iso, _ = _latent_hd(n, p, latent=200, seed=3)  # 近各向同性（高內在維度）→ 變異分散
    g_iso = DQIxGate().fit(iso)
    assert g_iso.reduced_ and g_iso.degraded_ is True
    lowrank, _ = _latent_hd(n, p, latent=3, seed=3)  # 低秩 → 少數成分即足
    g_lr = DQIxGate().fit(lowrank)
    assert g_lr.reduced_ and g_lr.degraded_ is False


def test_l1_low_dim_is_exact_noop_backward_compat():
    """WHY：低維（n≫2p）不得啟動降維——reduced_=False、reduce_V_=None，_project 為恆等，
    數學路徑與桶3 前逐位元相同（向後相容）。改 hd_min_n_over_p 不影響低維結果。"""
    rng = np.random.default_rng(7)
    X = rng.standard_normal((800, 12))
    g = DQIxGate().fit(X)
    assert g.reduced_ is False and g.reduce_V_ is None
    # 與「強制永不降維」設定逐位元相等（證明降維分支對低維是真 no-op）
    g0 = DQIxGate(Config(hd_min_n_over_p=0.0)).fit(X)
    np.testing.assert_array_equal(g.score(X), g0.score(X))
    assert np.isfinite(g.threshold_) and g.threshold_ > 0


def test_l1_domain_gate_survives_reduction():
    """DoD（成功判準 1）：降維後 golden 仍維持健康（高 inlier 率），且明確域位移 drift 的 DQI
    嚴格大於 golden（域閘未被降維破壞）。當降維讓 golden 誤報或抹平域位移時，本測試失敗。"""
    n, p = 60, 200
    Xg, L = _latent_hd(n, p, latent=5, seed=11)
    Xd, _ = _latent_hd(n, p, latent=5, seed=13, loadings=L, zshift=1.5)  # 同結構、潛操作點位移
    g = DQIxGate().fit(Xg)
    assert g.is_inlier(Xg).mean() >= 0.9                       # golden 健康
    assert g.score(Xd).mean() > g.score(Xg).mean() * 1.3       # 域位移顯著抬高 DQI


# ----------------------- L4 DriftDetector -----------------------

def test_l4_truncates_to_effective_rank_at_p_gg_n():
    """WHY：p≫n 時協方差有 p−(n−1) 個近零 noise 特徵值；保留全 p 成分會讓 per-component KS
    在任意 noise 方向檢定並把 Bonferroni ×p 過度膨脹。桶3 截斷至有效秩 rank_<p、Sg_ 僅 rank_ 維。"""
    n, p = 70, 200
    Xg, _ = _latent_hd(n, p, latent=5, seed=21)
    d = DriftDetector().fit(Xg)
    assert d.rank_ < p
    assert d.rank_ <= n - 1            # 標準化資料的秩上限
    assert d.Sg_.shape == (n, d.rank_)


def test_l4_low_dim_full_rank_backward_compat():
    """WHY：低維良條件（n≫p）有效秩=p → 不截斷、Sg_ 維度=p，行為與桶3 前一致（向後相容）。"""
    rng = np.random.default_rng(22)
    X = rng.standard_normal((1000, 15))
    d = DriftDetector().fit(X)
    assert d.rank_ == 15 and d.Sg_.shape[1] == 15


def test_l4_truncation_does_not_dilute_real_signal():
    """WHY：截斷 noise 維後，真實漂移的 KS 最小 p-value 不會被 ×p 的 Bonferroni 稀釋——
    截斷版 ks_min_pvalue ≤ 不截斷版（noise 維只增加校正倍數、不帶訊號）。"""
    n, p = 70, 200
    Xg, L = _latent_hd(n, p, latent=5, seed=31)
    Xd, _ = _latent_hd(n, p, latent=5, seed=33, loadings=L, zshift=1.5)
    p_trunc = DriftDetector(Config()).fit(Xg).ks_min_pvalue(Xd)
    p_full = DriftDetector(Config(hd_rank_rtol=0.0)).fit(Xg).ks_min_pvalue(Xd)
    assert p_trunc <= p_full + 1e-12
