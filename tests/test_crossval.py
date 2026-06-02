"""M9 cross-validation WHY 測試（Rule 9）。

marquee WHY（紅隊 D2/H2）：**同一個** HealthIndex（零 per-config 調參）在多種刻意多樣化的合成
組態（不同 p/noise/drift/seed）上都滿足 AC-1/2/3——證明偵測邏輯**對組態超參 robust**（排除對
單一 seed/維度的過擬合）。當 index 在任一組態喪失鑑別力（drift 不再被抓、或 golden 被誤判）時，
測試必須失敗。

範圍誠實標記（Rule 12，紅隊精準化）：本層證明的是「**單一合成 DGP 內的超參 robustness**」，
所有組態共用同一生成機制——**不等於**跨 DGP / 真實製程的外部泛化。完整 AC-4「真實集
(TEP/PRONTO/Gas)不退化」需下載真實資料，列 backlog，**不在此宣稱已達成 AC-4**。
"""

import numpy as np
import pytest

from health_index.adapters import synthetic as syn
from health_index.validation.crossval import (
    DEFAULT_GRID,
    ACResult,
    cross_validate,
    evaluate_configuration,
    format_report,
)


@pytest.fixture(scope="module")
def cv_results():
    # cross_validate 跑整個網格（每組態含 GPR/MMD），較貴 → module 範圍跑一次共用。
    return cross_validate()


def test_same_logic_robust_across_configs(cv_results):
    # marquee WHY：零 per-config 調參，**全部**組態 AC-1/2/3 皆過 → 對組態超參 robust（排除過擬合）。
    # 註（紅隊精準化）：這是「單一合成 DGP 內超參 robustness」，非跨 DGP 外部泛化（後者需真實集，backlog）。
    # 當任一組態 index 喪失鑑別力時此測試失敗（Rule 9：停止偵測仍綠的測試是錯的）。
    assert len(cv_results) == len(DEFAULT_GRID)
    for r in cv_results:
        assert r.ac1_golden_healthy, f"{r.label}: golden 不健康 {r.detail}"
        assert r.ac2_drift_caught_spc_blind, f"{r.label}: drift 未抓或 SPC 不盲 {r.detail}"
        assert r.ac3_clean_vs_drift, f"{r.label}: 乾淨/drift 未分離 {r.detail}"
        assert r.all_pass


def test_spc_blind_but_hi_catches_every_config(cv_results):
    # WHY（index 存在的理由，判準 2）：每組態的隱性飄移對單變數 3σ SPC 近乎隱形(<0.1)，HI 卻判
    # 不健康。若 HI 只是 SPC 的鏡像，這裡 hi_drift 不會明顯低於 golden。
    for r in cv_results:
        assert r.detail["spc_drift"] < 0.1                    # 單變數 SPC 盲
        assert r.detail["hi_drift"] < r.detail["hi_golden"]   # HI 卻抓到（drift 明顯低於 golden）


def test_drift_separated_from_clean_reentry(cv_results):
    # WHY（判準 3）：每組態 drift HI 明顯低於乾淨換線回歸 HI（區分殘留飄移 vs 乾淨回歸）。
    for r in cv_results:
        assert r.detail["hi_drift"] < r.detail["hi_clean"] - 0.2


def test_ac_check_is_not_vacuous_when_no_drift():
    # mutant-killer（紅隊 D2 / Rule 12）：當實際上**沒有**隱性飄移（drift_strength=0，drift 段≈golden）
    # 時，AC2「drift 被抓」與 AC3「drift 遠離乾淨回歸」必須為 False、all_pass=False——證明 AC 檢核
    # 會「對沒飄移的情況失敗」，不是恆真的假綠斷言。
    r = evaluate_configuration(seed=5, drift_strength=0.0)
    assert r.ac1_golden_healthy is True              # golden 仍健康
    assert r.ac2_drift_caught_spc_blind is False     # 無真飄移 → 不該被判不健康
    assert r.ac3_clean_vs_drift is False             # 無真飄移 → 不該遠離乾淨回歸
    assert r.all_pass is False


def test_grid_is_genuinely_diverse():
    # WHY（防假泛化）：DEFAULT_GRID 須真的多樣（相異 seed + 多種 p/noise/drift），否則「泛化」無意義
    # ——若有人把網格縮成單一組態仍宣稱泛化，此測試擋下。
    seeds = {c["seed"] for c in DEFAULT_GRID}
    ps = {c["p"] for c in DEFAULT_GRID}
    noises = {c["noise_sigma"] for c in DEFAULT_GRID}
    drifts = {c["drift_strength"] for c in DEFAULT_GRID}
    assert len(DEFAULT_GRID) >= 3
    assert len(seeds) == len(DEFAULT_GRID)           # seed 全相異＝獨立組態
    assert len(ps) >= 2 and len(noises) >= 2 and len(drifts) >= 2


def test_all_pass_requires_all_three():
    # WHY：all_pass = 三 AC 的 AND（mutant：改成 OR 必被抓）。
    base = dict(
        label="x",
        ac1_golden_healthy=True,
        ac2_drift_caught_spc_blind=True,
        ac3_clean_vs_drift=True,
    )
    assert ACResult(**base).all_pass is True
    for flip in ("ac1_golden_healthy", "ac2_drift_caught_spc_blind", "ac3_clean_vs_drift"):
        d = dict(base)
        d[flip] = False
        assert ACResult(**d).all_pass is False


def test_custom_grid_is_honored():
    # WHY：cross_validate 跑傳入的網格（非寫死 DEFAULT_GRID）。
    grid = [{"seed": 7, "drift_strength": 1.5, "p": 8, "noise_sigma": 0.2, "n_per_campaign": 300}]
    rs = cross_validate(grid)
    assert len(rs) == 1
    assert rs[0].label == "seed7_p8_noise0.2_drift1.5"


def test_evaluate_deterministic():
    # WHY（決定論，鎖 RNG）：同組態 → 同 AC 結果與 detail（決定論偵測器，紅隊 RNG 風險）。
    cfg = dict(seed=7, drift_strength=1.5, p=8, noise_sigma=0.2)
    r1 = evaluate_configuration(**cfg)
    r2 = evaluate_configuration(**cfg)
    assert (r1.ac1_golden_healthy, r1.ac2_drift_caught_spc_blind, r1.ac3_clean_vs_drift) == (
        r2.ac1_golden_healthy,
        r2.ac2_drift_caught_spc_blind,
        r2.ac3_clean_vs_drift,
    )
    assert r1.detail == r2.detail


def test_synthetic_marginal_variance_invariant():
    # WHY（鎖 SPC 盲的根因，紅隊 A-Q3）：synthetic drift 段「只改方向不改邊際變異」——drift 段各欄
    # std 應≈golden 段。這正是單變數 SPC 對隱性飄移**該盲**的數學保證。若 generator 哪天破壞此
    # 不變式，AC-2 的 SPC 盲前提瓦解、整個 index 存在理由失守，此測試擋下（而非讓 SPC 測試悄悄變鬆）。
    ds, gt = syn.generate(seed=5, drift_strength=1.2)
    cols = list(ds.x_columns)
    Xg = ds.frame.loc[gt.golden_mask, cols].to_numpy()
    Xd = ds.frame.loc[gt.drift_mask, cols].to_numpy()
    ratio = Xd.std(axis=0) / Xg.std(axis=0)
    assert np.all(np.abs(ratio - 1.0) < 0.25)   # 各欄邊際變異守恆（容忍帶含噪聲+有限樣本）


def test_format_report_marks_scope_and_reflects_results(cv_results):
    # WHY（M9「泛化報告」交付 + 不過度宣稱）：報告須含每組態結果，且抬頭明標「backlog/非完整 AC-4」，
    # 避免「N/N 全過」被誤讀為真實集已驗證（Rule 12）。
    md = format_report(cv_results)
    assert "泛化報告" in md
    assert "backlog" in md and "AC-4" in md          # 誠實標記真實集未驗
    for r in cv_results:
        assert r.label in md                          # 每組態都入報告
    assert f"{sum(r.all_pass for r in cv_results)}/{len(cv_results)}" in md


def test_format_report_is_windows_console_safe(cv_results):
    # WHY（M10 啟動手冊的 print 命令須在 Windows cp950 主控台可跑）：報告不得含非 cp950 字元，
    # 否則文件化的 `python -c "...print(format_report(...))"` 會 UnicodeEncodeError（曾因 ✅/∧ 發生）。
    format_report(cv_results).encode("cp950")        # 不丟 UnicodeEncodeError 即過
