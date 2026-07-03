"""TDD-3 batch-AVM 結構隔離 WHY 測試（Rule 9）。

marquee WHY（隔離裁決 A + 風險稽核）：batch-AVM/[param×stat] 只隔離於**告警/KPI 融合層**、
呈現/下鑽放行——「放行顯示是安全的」這個前提**靠融合隔離被結構鎖死**才成立。既有測試只鎖
舊特徵層 token（segment_*）與 features→skeleton 單向；batch-AVM 新模組（batch_features/
conformal_cv/batch_avm 套件）沒有任何自動鎖，不變式靠 docstring 慣例＝會靜默腐爛。
X* 聚合已丟批內跨感測相關（對 covert drift 天生鈍），若回流融合會稀釋主訊號 L2 SPE——
本檔測試失敗＝有人把 batch-AVM 接回主告警鏈，必須先撤回再談。
"""

import ast
import inspect
import os
import subprocess
import sys
from pathlib import Path

import health_index.health as health_mod
from health_index.deploy import demo
from health_index.detectors import conformal_cv as conformal_cv_mod
from health_index.preprocess import batch_features as batch_features_mod

# batch-AVM 側模組/符號——主告警路徑不得引用
_BATCH_TOKENS = (
    "batch_avm",
    "batch_features",
    "batch_temporal_overlay",
    "batch_indicator_matrix",
    "conformal_cv",
    "CVPlusConformal",
)

def _imported_modules(mod) -> list[str]:
    """AST 抽取模組實際 import 的模組名（含函式內 lazy import）——純度驗 import 耦合，不誤傷 docstring 散文。"""
    tree = ast.parse(inspect.getsource(mod))
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            out.append(node.module or "")
    return out


def test_main_path_functions_do_not_reference_batch_avm():
    """主路徑函式（score_timeline/window_detail）原始碼不得出現 batch-AVM token。"""
    for fn in (demo.score_timeline, demo.window_detail):
        src = inspect.getsource(fn)
        for tok in _BATCH_TOKENS:
            assert tok not in src, f"主路徑 {fn.__name__} 引用了 batch-AVM：{tok}"


def test_health_module_does_not_import_batch_avm():
    """HealthIndex 所在模組（health.py 全檔）不得出現 batch-AVM token。"""
    src = inspect.getsource(health_mod)
    for tok in _BATCH_TOKENS:
        assert tok not in src, f"health.py 引用了 batch-AVM：{tok}"


def test_batch_features_is_pure_of_skeleton():
    """batch_features 為純 numpy/pandas 函數層：不得 import 骨架/偵測器（本層出錯不可能影響 HI/alarm）。"""
    for m in _imported_modules(batch_features_mod):
        assert not any(b in m for b in ("health", "detectors", "deploy", "interface")), \
            f"batch_features import 了骨架模組：{m}"


def test_conformal_cv_does_not_touch_live_detectors():
    """conformal_cv 只吃 make_estimator 工廠：不得 import HealthIndex/MSPC/DQIx（僅允許 config）。"""
    for m in _imported_modules(conformal_cv_mod):
        assert not any(b in m for b in ("health", "mspc", "dqi_x", "drift", "deploy")), \
            f"conformal_cv import 了骨架模組：{m}"


def test_main_import_graph_excludes_batch_avm():
    """模組層 import graph：載入主路徑（health + deploy.demo）不得連帶載入任何 batch-AVM 模組。

    子行程檢查（不受本測試行程既有 import 汙染）——比原始碼字串掃描更強：
    擋住「主路徑模組層 import batch-AVM」這種掃描函式原始碼抓不到的耦合。
    """
    repo = Path(__file__).resolve().parents[1]
    code = (
        "import sys; import health_index.health, health_index.deploy.demo; "
        "bad = sorted(m for m in sys.modules if 'batch_avm' in m or 'batch_features' in m or 'conformal_cv' in m); "
        "assert not bad, f'主路徑 import graph 含 batch-AVM 模組: {bad}'"
    )
    env = {**os.environ, "PYTHONPATH": str(repo / "src")}
    r = subprocess.run([sys.executable, "-c", code], cwd=str(repo), env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
