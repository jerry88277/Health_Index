"""#7 batch-AVM headless runner WHY 測試（Rule 9）。

marquee WHY：runner 讓 batch-AVM 能被外部排程器（cron/Windows 排程）驅動、**重啟安全**地增量
評分「新到齊」的批，且**不重複處理已發過的批**（重複＝重複告警／未來重複觸發 SMTP 扣費）。測試鎖：
(a) 冪等於 cursor：無新批→空結果且 cursor 不動；有新批→只處理新批、cursor 正確前進；
(b) 每批結果忠實帶 batch-AVM 訊號（Ŷ／T²·SPE 域外／正式 G3 AD 肇因）；
(c) save/load state round-trip → 重載後從斷點續跑（resume-safe），與一次跑完等價。
確定性（Rule 5）：同輸入同輸出。Y 側 G1/G2 與批內生命週期屬 #9，本 runner 到 X*→Ŷ + AD。
"""

import numpy as np

from health_index.batch_avm.mapping import fit_batch_model
from health_index.batch_avm.runner import (
    BatchRunnerState,
    load_state,
    poll_batches,
    run_all,
    save_state,
)


def _model(n=60, p=5, seed=0):
    rng = np.random.default_rng(seed)
    X = rng.normal(size=(n, p))
    y = 3.0 * X[:, 0] + 0.1 * rng.normal(size=n)
    return fit_batch_model(X, y, columns=[f"c{i}" for i in range(p)]), X


def test_poll_processes_only_new_batches_idempotent():
    # WHY(a)：冪等於 cursor——重入不重處理已發批（防重複告警）。
    m, X = _model()
    xall = X[:10]
    res1, st1 = poll_batches(m, xall, BatchRunnerState())
    assert len(res1) == 10 and st1.cursor == 10
    res2, st2 = poll_batches(m, xall, st1)          # 無新批
    assert res2 == [] and st2.cursor == 10
    xall2 = X[:13]                                   # 3 批新到齊
    res3, st3 = poll_batches(m, xall2, st2)
    assert len(res3) == 3 and st3.cursor == 13
    assert [r.index for r in res3] == [10, 11, 12]   # 全域索引正確、不回頭


def test_results_carry_batch_avm_signals():
    # WHY(b)：每批帶 Ŷ／域外／正式 G3 AD 肇因（接錯就抓）。
    m, X = _model()
    q = X.mean(axis=0).copy()
    q[0] += 6.0                                      # y=3·c0 → Ŷ 遠超 golden 範圍（G3 AD Ŷ 出範圍）
    res, _ = poll_batches(m, q.reshape(1, -1), BatchRunnerState())
    r = res[0]
    assert np.isfinite(r.yhat) and r.band_lo <= r.band_hi
    assert r.g3_ad_alarm is True and r.g3_ad_top is not None


def test_state_save_load_resume(tmp_path):
    # WHY(c)：斷點續跑——存/載狀態後從 cursor 續，與一次跑完等價（resume-safe）。
    m, X = _model()
    xall = X[:12]
    res_a, st_a = poll_batches(m, xall[:7], BatchRunnerState())
    p = str(tmp_path / "brun.json")
    save_state(st_a, p)
    st_loaded = load_state(p)
    assert st_loaded.cursor == 7
    res_b, st_b = poll_batches(m, xall, st_loaded)   # 續跑剩 5 批
    got = [r.index for r in res_a] + [r.index for r in res_b]
    assert got == list(range(12))                    # 續跑無縫接上、無重無漏
    # 與一次跑完等價（allclose：不同 predict 批量 shape 的 BLAS 捨入差 ~1e-10，非 runner 不確定）
    res_full, _ = poll_batches(m, xall, BatchRunnerState())
    assert np.allclose([r.yhat for r in res_full], [r.yhat for r in (res_a + res_b)], atol=1e-8)


def test_load_state_missing_file_is_fresh(tmp_path):
    # WHY：首次啟動（無 state 檔）→ 回初始狀態，不炸。
    st = load_state(str(tmp_path / "nope.json"))
    assert st.cursor == 0 and st.n_alarms == 0


def test_run_all_convenience():
    m, X = _model()
    res = run_all(m, X[:8])
    assert len(res) == 8 and [r.index for r in res] == list(range(8))


def test_deterministic():
    m, X = _model(seed=2)
    a, _ = poll_batches(m, X[:9], BatchRunnerState())
    b, _ = poll_batches(m, X[:9], BatchRunnerState())
    assert [r.yhat for r in a] == [r.yhat for r in b]
    assert [r.g3_ad_alarm for r in a] == [r.g3_ad_alarm for r in b]
