"""映射模型比較 + conformal coverage 的離線 CV harness（batch-AVM X*→Ŷ 路徑）。

為何存在（與 crossval.py 分工，Rule 3/7）：``crossval.py`` 是主 HealthIndex 的 AC-1/2/3
驗收 runner（單一偵測邏輯跨組態 robustness）；本 harness 回答**另一問題**——對某資料集
**哪個映射模型（GPR/PLS）更準**、且 **CV+ conformal 帶是否真達其宣稱覆蓋**。兩者皆為離線、
**無洩漏（out-of-fold）**評估工具，不進 runtime 告警路徑。

確定性（Rule 5）：repeats 以**確定性乘法雜湊排列**（Knuth-style，無 RNG）產生**不同折分割**，
再逐分割做 K-fold；repeat 0＝恆等排列（＝一般 K-fold）。故 ``rmse_std`` 反映 CV 估計對折分配的
敏感度（穩定度），是真實訊號、非結構性 0（紅隊 must-fix：舊版 offset 旋轉只重命名 fold 標籤、
分割不變＝no-op，rmse_std 恆 0 且 n_eval 重複計數，已修）。
誠實口徑（Rule 12）：
- conformal coverage 底線與 ``CVPlusConformal`` 一致＝worst-case **1−2α**（非 split-CP 的 1−α），
  同時揭示 nominal 1−α 供參照，但**不宣稱**達成 nominal。
- repeats 用確定性排列、非 Monte-Carlo 隨機重排：分割確實不同（非 no-op），但排列族有限、
  不等於完整隨機 repeated CV 的變異估計；如需嚴格 Monte-Carlo 需 RNG（與 Rule 5 衝突，不採），侷限明標。
- ``n_eval``＝**distinct** out-of-fold 點數（=n）；RMSE 為 R 個分割池化殘差之估計（每點各分割各評一次）。
不碰骨架（Rule 3）：純評估工具，不改 mapping/conformal/soft_sensor 契約。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from ..config import DEFAULT, Config
from ..detectors.conformal_cv import CVPlusConformal

Factory = Callable[[], object]  # 無參工廠 → 未 fit 之估計器（具 fit(X,y)->self 與 predict(X)）


@dataclass
class CVScore:
    """單一模型的 repeated K-fold out-of-fold 誤差摘要。"""

    label: str
    rmse: float                    # R 個折分割的 oof 殘差池化 RMSE
    rmse_std: float                # 跨分割的 per-partition RMSE 標準差（對折分配的敏感度＝穩定度）
    mae: float
    n_eval: int                    # distinct out-of-fold 點數（=n；非 n×repeats）
    per_repeat_rmse: list = field(default_factory=list)


def _finite_xy(X, y):
    X = np.asarray(X, dtype=float)
    y = np.asarray(y, dtype=float)
    obs = np.isfinite(y)
    return X[obs], y[obs]


# 確定性乘法雜湊排列的固定乘數（Knuth-style 奇數；無 RNG，Rule 5）——供 repeats 產生不同折分割。
_MULTS = (2654435761, 40503, 2246822519, 3266489917, 668265263, 374761393)
_HASH_P = 2147483647  # 2^31−1（Mersenne prime）


def _perm(n: int, r: int) -> np.ndarray:
    """確定性排列 range(n)（r=0＝恆等；r≥1＝乘法雜湊 argsort）。不同 r → 不同排列，無 RNG。"""
    if r <= 0:
        return np.arange(n)
    mult = _MULTS[(r - 1) % len(_MULTS)]
    key = (np.arange(n, dtype=np.int64) * mult) % _HASH_P
    return np.argsort(key, kind="stable")  # argsort 恆為合法排列（ties 以 stable 確定性打破）


def _fold_of(n: int, k: int, r: int) -> np.ndarray:
    """第 r 個確定性折分割：以排列 _perm(n,r) 打散後按位置取模 → 不同 r 得不同分割（非只重命名）。"""
    fold = np.empty(n, dtype=int)
    fold[_perm(n, r)] = np.arange(n) % k
    return fold


def _oof_residuals(make_estimator: Factory, X: np.ndarray, y: np.ndarray, k: int, r: int) -> np.ndarray:
    """單一折分割的 out-of-fold 有號殘差（每點由**未見它**的折模型預測）。"""
    n = len(y)
    fold = _fold_of(n, k, r)
    resid = np.empty(n, dtype=float)
    for f in range(k):
        te = np.where(fold == f)[0]
        trn = np.where(fold != f)[0]
        if len(te) == 0 or len(trn) == 0:
            resid[te] = np.nan
            continue
        model = make_estimator().fit(X[trn], y[trn])
        pred = np.asarray(model.predict(X[te]), dtype=float).ravel()
        resid[te] = y[te] - pred
    return resid


def repeated_kfold_score(make_estimator: Factory, X, y, *, k: int = 5, repeats: int = 3,
                         label: str = "model", config: Config = DEFAULT) -> CVScore:
    """repeated K-fold out-of-fold 誤差（無洩漏；每 repeat 為一個**不同的**確定性折分割）。

    ``rmse``＝R 個分割池化殘差之 RMSE；``rmse_std``＝跨分割 per-partition RMSE 的標準差（對折分配的
    敏感度）；``n_eval``＝distinct 點數 n（非 n×repeats）。

    Raises:
        ValueError: 有效觀測 < k 或 k < 2（折無法成立）。
    """
    X, y = _finite_xy(X, y)
    n = len(y)
    if k < 2 or n < k:
        raise ValueError(f"CV 折不成立：n={n}, k={k}（需 k≥2 且 n≥k）")
    all_resid: list = []
    per_repeat: list = []
    for r in range(max(1, repeats)):
        resid = _oof_residuals(make_estimator, X, y, k, r=r)
        good = resid[np.isfinite(resid)]
        all_resid.append(good)
        per_repeat.append(round(float(np.sqrt(np.mean(good ** 2))), 6))
    pool = np.concatenate(all_resid)
    return CVScore(
        label=label,
        rmse=round(float(np.sqrt(np.mean(pool ** 2))), 6),
        rmse_std=round(float(np.std(per_repeat)), 6),
        mae=round(float(np.mean(np.abs(pool))), 6),
        n_eval=int(n),  # distinct oof 點數（各分割各評一次，不重複計數）
        per_repeat_rmse=per_repeat,
    )


def compare_models(candidates: dict[str, Factory], X, y, *, k: int = 5, repeats: int = 3,
                   config: Config = DEFAULT) -> dict:
    """多候選映射模型的 repeated CV 比較。回傳 {scores:{name→CVScore}, best:name（最小 RMSE）}。"""
    scores = {name: repeated_kfold_score(f, X, y, k=k, repeats=repeats, label=name, config=config)
              for name, f in candidates.items()}
    best = min(scores, key=lambda nm: scores[nm].rmse)
    return {"scores": scores, "best": best}


def conformal_coverage(make_estimator: Factory, X, y, *, outer_k: int = 5, config: Config = DEFAULT) -> dict:
    """稽核 CV+ conformal 帶的 **held-out** 覆蓋：外層 K-fold，每折當 test、其餘 fit CV+，量覆蓋。

    Returns:
        {achieved, floor(=1−2α), nominal(=1−α), mean_width, n_eval, n_folds_unavailable, meets_floor}。
        achieved/mean_width 僅統計 CV+ 可用的外折；全折不可用時 achieved=None（誠實不評）。
    """
    X, y = _finite_xy(X, y)
    n = len(y)
    if outer_k < 2 or n < outer_k:
        raise ValueError(f"外層折不成立：n={n}, outer_k={outer_k}")
    fold = _fold_of(n, outer_k, 0)
    covered = 0
    total = 0
    widths: list = []
    n_unavail = 0
    for f in range(outer_k):
        te = np.where(fold == f)[0]
        trn = np.where(fold != f)[0]
        cv = CVPlusConformal(config=config).fit(make_estimator, X[trn], y[trn])
        if not cv.available:
            n_unavail += 1
            continue
        lo, hi = cv.predict_interval(X[te])
        covered += int(np.sum((y[te] >= lo) & (y[te] <= hi)))
        total += len(te)
        widths.extend((hi - lo).tolist())
    floor = 1.0 - 2.0 * config.cp_alpha
    achieved = (covered / total) if total else None
    return {
        "achieved": round(achieved, 4) if achieved is not None else None,
        "floor": round(floor, 4),
        "nominal": round(1.0 - config.cp_alpha, 4),
        "mean_width": round(float(np.mean(widths)), 6) if widths else None,
        "n_eval": int(total),
        "n_folds_unavailable": int(n_unavail),
        "meets_floor": bool(achieved is not None and achieved >= floor),
    }


def nested_cv_selection(candidates: dict[str, Factory], X, y, *, outer_k: int = 5, inner_k: int = 4,
                        repeats: int = 1, config: Config = DEFAULT) -> dict:
    """nested CV：外層估**模型選擇程序**的無偏泛化——外折 train 上 inner CV 選最佳→refit→評外折 test。

    Returns:
        {mean_rmse（池化外折殘差 RMSE，無偏）, selection_counts:{name→次數}, per_fold:[{selected, rmse}]}。
    """
    X, y = _finite_xy(X, y)
    n = len(y)
    if outer_k < 2 or n < outer_k:
        raise ValueError(f"外層折不成立：n={n}, outer_k={outer_k}")
    fold = _fold_of(n, outer_k, 0)
    counts: dict = {name: 0 for name in candidates}
    per_fold: list = []
    pool: list = []
    for f in range(outer_k):
        te = np.where(fold == f)[0]
        trn = np.where(fold != f)[0]
        inner = compare_models(candidates, X[trn], y[trn], k=inner_k, repeats=repeats, config=config)
        sel = inner["best"]
        counts[sel] += 1
        model = candidates[sel]().fit(X[trn], y[trn])                 # refit 選中者於外折 train 全量
        pred = np.asarray(model.predict(X[te]), dtype=float).ravel()
        resid = y[te] - pred
        pool.append(resid)
        per_fold.append({"selected": sel, "rmse": round(float(np.sqrt(np.mean(resid ** 2))), 6)})
    allr = np.concatenate(pool)
    return {"mean_rmse": round(float(np.sqrt(np.mean(allr ** 2))), 6), "selection_counts": counts,
            "per_fold": per_fold}


def format_report(compare_result: dict, coverage: dict | None = None) -> str:
    """把比較 + coverage 結果渲染成 markdown（離線交付）。標記用 ASCII 避免 Windows 主控台編碼問題。"""
    scores = compare_result["scores"]
    lines = [
        "# 映射模型 CV 比較 + conformal coverage（離線、out-of-fold）",
        "",
        "> 範圍：某資料集上映射模型 repeated K-fold 誤差比較；覆蓋底線＝worst-case **1−2α**（非 1−α）。",
        "> repeats 為確定性 index 旋轉（非 Monte-Carlo 隨機重排），降變異效果有限——侷限明標（Rule 12）。",
        "",
        "| model | RMSE (oof) | RMSE std | MAE | n_eval | best |",
        "|---|--:|--:|--:|--:|:--:|",
    ]
    best = compare_result["best"]
    for name, s in scores.items():
        lines.append(f"| {name} | {s.rmse} | {s.rmse_std} | {s.mae} | {s.n_eval} | "
                     f"{'*' if name == best else ''} |")
    if coverage is not None:
        lines += [
            "",
            "## CV+ conformal coverage（held-out 稽核）",
            f"- achieved：**{coverage['achieved']}**（floor 1−2α = {coverage['floor']}，"
            f"nominal 1−α = {coverage['nominal']} 僅參照、不宣稱）",
            f"- 達底線：{'PASS' if coverage['meets_floor'] else 'FAIL'}｜平均帶寬 {coverage['mean_width']}"
            f"｜n_eval {coverage['n_eval']}｜不可用外折 {coverage['n_folds_unavailable']}",
        ]
    return "\n".join(lines)
