"""G1 模型打包：fitted HealthIndex(+YHealthIndex) 的 save/load + 指紋重放驗證。

D1 決策（docs/deployment_plan.md §4）：**joblib + 指紋重放**。load 時重放黃金指紋樣本、比對存檔時的
輸出，行為不符即 fail-loud——涵蓋 GPR/PLS/MinCovDet 等難手寫序列化的 sklearn 物件，且比「格式層相容」
更根本：不管是 numpy/sklearn 升版漂移還是檔案損毀，**只要凍結模型對同一輸入給出不同答案就拒載**（Rule 12）。

不變式：bundle 一旦 build 即凍結；``created_at`` 由呼叫端傳入（git 時間為權威，不在此取 now）。
"""

from __future__ import annotations

import platform
from dataclasses import dataclass, field

import joblib
import numpy as np

from ..config import DEFAULT, Config
from ..health import HealthIndex


class BundleIntegrityError(RuntimeError):
    """指紋重放與存檔輸出不符（版本漂移／檔案損毀）→ 拒載，不靜默用壞模型。"""


def _versions() -> dict[str, str]:
    """擷取建模環境版本（供診斷指紋不符的根因）。"""
    import sklearn

    return {
        "python": platform.python_version(),
        "numpy": np.__version__,
        "sklearn": sklearn.__version__,
        "joblib": joblib.__version__,
    }


@dataclass
class ModelBundle:
    """凍結的 per-product 模型 + 黃金指紋 + 環境版本。

    Attributes:
        product: 產品/模型識別（單一產品一個模型）。
        health: 已 fit 並凍結的 HealthIndex（L1/L2/L4）。
        x_columns: 模型期望的 X 欄名序（線上資料須對齊）。
        config: 建模時的超參（單一 config 治理）。
        created_at: 建模時間字串（呼叫端傳入，git 時間為權威）。
        fingerprint_x: 黃金指紋樣本（重放用）。
        fingerprint_hi/fingerprint_sub: 存檔時對指紋的 health_index / subscores 輸出。
        versions: 建模環境版本。
        y_health: 選配的 YHealthIndex（無軟量測時 None）。
    """

    product: str
    health: HealthIndex
    x_columns: tuple[str, ...]
    config: Config
    created_at: str
    fingerprint_x: np.ndarray
    fingerprint_hi: float
    fingerprint_sub: dict[str, float]
    versions: dict[str, str] = field(default_factory=_versions)
    y_health: object | None = None
    window: int | None = None  # 紅隊 A20：模型部署評分窗長（單一真相）——下鑽/匯出/總覽燈一律讀此、不各自帶；
                               # None＝舊 bundle（getattr fallback 到呼叫端預設）。不入指紋（窗長與 fit 時凍結的控制限解耦）。

    def verify(self, *, rtol: float = 1e-6, atol: float = 1e-9) -> None:
        """重放黃金指紋，比對存檔輸出；不符即 ``BundleIntegrityError``（fail-loud）。"""
        hi = float(self.health.health_index(self.fingerprint_x))
        if not np.isclose(hi, self.fingerprint_hi, rtol=rtol, atol=atol):
            raise BundleIntegrityError(
                f"指紋重放不符：health_index 重算={hi:.8g} vs 存檔={self.fingerprint_hi:.8g}"
                f"（版本漂移或檔案損毀；建模環境 {self.versions}）"
            )
        sub = self.health.subscores(self.fingerprint_x)
        for k, v in self.fingerprint_sub.items():
            if not np.isclose(float(sub[k]), v, rtol=rtol, atol=atol):
                raise BundleIntegrityError(
                    f"指紋子分數 {k} 重放不符：{sub[k]:.8g} vs 存檔 {v:.8g}（版本漂移/損毀）"
                )


def build_bundle(
    product: str,
    health: HealthIndex,
    x_columns,
    *,
    golden: np.ndarray,
    created_at: str,
    y_health: object | None = None,
    window: int | None = None,
    n_fingerprint: int = 20,
) -> ModelBundle:
    """從已 fit 的 HealthIndex + 黃金資料建 bundle，並擷取重放指紋。

    Args:
        product: 產品識別。
        health: 已 fit 的 HealthIndex。
        x_columns: X 欄名序（與 health fit 時一致）。
        golden: 黃金資料 (n,p)，取前 ``n_fingerprint`` 列為指紋。
        created_at: 建模時間字串（git 時間，呼叫端提供）。
        y_health: 選配 YHealthIndex。
        n_fingerprint: 指紋樣本數（≥1）。

    Returns:
        ModelBundle（指紋 hi/sub 為當下輸出）。

    Raises:
        ValueError: golden 為空或 n_fingerprint<1。
    """
    g = np.asarray(golden, dtype=float)
    if g.ndim != 2 or len(g) == 0:
        raise ValueError(f"golden 須為非空 (n,p) 陣列，得 shape={g.shape}")
    k = max(1, min(int(n_fingerprint), len(g)))
    fx = g[:k].copy()
    return ModelBundle(
        product=str(product),
        health=health,
        x_columns=tuple(x_columns),
        config=getattr(health, "config", DEFAULT),
        created_at=str(created_at),
        fingerprint_x=fx,
        fingerprint_hi=float(health.health_index(fx)),
        fingerprint_sub={k_: float(v) for k_, v in health.subscores(fx).items()},
        y_health=y_health,
        window=None if window is None else int(window),
    )


def save(bundle: ModelBundle, path: str) -> str:
    """joblib 序列化 bundle 到 path（建模端）。回傳 path。"""
    joblib.dump(bundle, path)
    return path


def load(path: str, *, verify: bool = True) -> ModelBundle:
    """載入 bundle；``verify=True``（預設）重放指紋，不符即 ``BundleIntegrityError``（拒載壞模型）。"""
    bundle = joblib.load(path)
    if not isinstance(bundle, ModelBundle):
        raise BundleIntegrityError(f"檔案非 ModelBundle（得 {type(bundle).__name__}）")
    if verify:
        bundle.verify()
    return bundle
