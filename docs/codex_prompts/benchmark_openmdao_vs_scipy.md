# Benchmark: method="openmdao" vs method="scipy"（讀寫分離量測）

## 背景（給 Codex 的脈絡，不要再去 grep）

P3#13 已完成 `DualSparPropertiesComp` 的解析偏導，但端到端量測（current 729068f vs baseline 0c2df89）顯示
DE 與 SLSQP 段的耗時都沒變化：

| commit | de_global_s | slsqp_local_s | total_s | mass |
|--------|-------------|---------------|---------|------|
| 729068f (analytic partials) | 528.890 | 2.203 | 531.132 | 14.357903 |
| 0c2df89 (baseline)          | 519.485 | 2.119 | 521.628 | 14.357903 |

原因經過源碼追查已確認：

1. `examples/blackcat_004_optimize.py:156` 寫死 `opt.optimize(method="scipy")`
2. `SparOptimizer._optimize_scipy()` 在 `src/hpa_mdo/structure/optimizer.py:236-289`
   完全把 OpenMDAO 當黑盒分析器在用：
   - DE：`differential_evolution(penalty_obj, ...)` → `_eval(x)` → `run_analysis(prob)` → `prob.run_model()`
   - SLSQP：`scipy_minimize(obj, x_de, method="SLSQP", ...)` 沒傳 `jac=`，constraints 也都是 lambda 包 `_eval`
3. 兩條路最後都只呼叫 `prob.run_model()`（oas_structural.py:1391），**從來不會呼叫
   `prob.run_driver()` 或 `prob.compute_totals()`**，所以 `DualSparPropertiesComp.compute_partials()`
   永遠不會被觸發。

OpenMDAO driver 路徑其實已經完整 wired up（oas_structural.py:1278-1335）：
DV / objective / constraints / `om.ScipyOptimizeDriver` 都註冊好了，
`SparOptimizer._optimize_openmdao()` 只是呼叫 `run_optimization(prob)` → `prob.run_driver()`
（optimizer.py:229-234），但這條路從來沒在 blackcat_004 上被端到端量過。

## 目標

寫一個 read-only benchmark 腳本，從同一個初始點 cold start 跑兩條路徑，量化以下對比：

1. **是否收斂到等價的解**（mass、failure、buckling、twist、tip_defl 全部列出）
2. **總耗時**（wall clock）
3. **`run_model` / `compute_partials` 實際被呼叫的次數**（這是判斷 partials 有沒有被用到的唯一可信指標）
4. 如果 openmdao 路徑收斂得到同樣或更好的解，後續才能討論要不要把 example default 切過去

**重要：這個任務只做量測與報告，不要修改 production default、不要動 optimizer.py 內部邏輯。**

## 要做的事

### Step 1：在元件加 call counter（最小侵入）

修改 `src/hpa_mdo/structure/spar_model.py` 的 `DualSparPropertiesComp`，
在 class 上加 class-level 計數器（不要用 instance 屬性，避免被多次 setup 重置）：

```python
class DualSparPropertiesComp(om.ExplicitComponent):
    # Class-level call counters for benchmarking (not thread-safe).
    _n_compute = 0
    _n_compute_partials = 0

    @classmethod
    def reset_counters(cls) -> None:
        cls._n_compute = 0
        cls._n_compute_partials = 0
```

並在現有的 `compute()` 與 `compute_partials()` 方法**第一行**加：

```python
def compute(self, inputs, outputs):
    type(self)._n_compute += 1
    # ... existing body unchanged ...

def compute_partials(self, inputs, partials):
    type(self)._n_compute_partials += 1
    # ... existing body unchanged ...
```

如果 `compute_partials()` 目前不存在於 class 上（已經是解析偏導，照理應該存在），
就找到實際定義的位置加。先用 `grep -n "def compute_partials" src/hpa_mdo/structure/spar_model.py` 確認。

**禁止**：
- 不要改其它元件
- 不要改任何輸出/輸入介面
- 不要把 counter 寫成 module-level global（會干擾測試）

### Step 2：寫 benchmark 腳本

新增 `examples/benchmark_openmdao_vs_scipy.py`，內容大致如下：

```python
"""Benchmark: SparOptimizer.optimize(method="openmdao") vs method="scipy").

Read-only comparison run from a clean starting point. Reports timing,
final design metrics, and call counts for compute() / compute_partials()
on DualSparPropertiesComp so we can verify whether analytic partials are
actually being used by each path.

Usage:
    python examples/benchmark_openmdao_vs_scipy.py
"""
from __future__ import annotations

import json
from pathlib import Path
from time import perf_counter

from hpa_mdo.core import load_config, Aircraft, MaterialDB
from hpa_mdo.aero import VSPAeroParser, LoadMapper
from hpa_mdo.structure import SparOptimizer
from hpa_mdo.structure.spar_model import DualSparPropertiesComp


def _build_optimizer():
    cfg = load_config("configs/blackcat_004.yaml")
    ac = Aircraft.from_config(cfg)
    mat_db = MaterialDB()
    parser = VSPAeroParser(cfg.io.vsp_lod)
    aero = parser.parse()
    mapper = LoadMapper()
    loads = mapper.map_loads(
        aero[0],
        ac.wing.y,
        actual_velocity=cfg.flight.velocity,
        actual_density=cfg.flight.air_density,
    )
    return SparOptimizer(cfg, ac, loads, mat_db)


def _run_one(method: str) -> dict:
    DualSparPropertiesComp.reset_counters()
    opt = _build_optimizer()  # fresh problem so initial DVs are identical
    t0 = perf_counter()
    result = opt.optimize(method=method)
    elapsed = perf_counter() - t0
    return {
        "method": method,
        "success": bool(result.success),
        "message": result.message,
        "total_mass_full_kg": float(result.total_mass_full_kg),
        "failure_index": float(result.failure_index),
        "buckling_index": float(result.buckling_index),
        "twist_max_deg": float(result.twist_max_deg),
        "tip_deflection_m": float(result.tip_deflection_m),
        "wall_time_s": elapsed,
        "timing_s": dict(result.timing_s),
        "n_compute": int(DualSparPropertiesComp._n_compute),
        "n_compute_partials": int(DualSparPropertiesComp._n_compute_partials),
    }


def main() -> None:
    rows = []
    for method in ("openmdao", "scipy"):
        print(f"\n=== Running method={method} ===")
        try:
            rows.append(_run_one(method))
        except Exception as exc:  # noqa: BLE001 — explicitly capture for the report
            rows.append({
                "method": method,
                "success": False,
                "error": f"{type(exc).__name__}: {exc}",
            })

    out_dir = Path("docs")
    out_dir.mkdir(exist_ok=True)
    out_json = out_dir / "openmdao_vs_scipy_benchmark.json"
    out_json.write_text(json.dumps(rows, indent=2))
    print(f"\nWrote raw results to {out_json}")

    # Print human-readable comparison
    print("\n=== Comparison ===")
    for r in rows:
        print(json.dumps(r, indent=2))


if __name__ == "__main__":
    main()
```

**禁止**：
- 不要呼叫任何隨機種子改寫
- 不要把 benchmark 結果寫進 baseline JSON
- 不要在 example 裡做 plotting（純文字輸出）
- 不要 import `matplotlib`

### Step 3：跑 benchmark + 寫報告

跑：
```
.venv/bin/python examples/benchmark_openmdao_vs_scipy.py
```

把 stdout 與 `docs/openmdao_vs_scipy_benchmark.json` 整理成 `docs/openmdao_vs_scipy_benchmark.md`，
**用繁體中文**，包含以下章節：

1. **動機**：一句話帶過 P3#13 解析偏導為何要驗證
2. **量測方法**：cold start、同初始點、call counter 怎麼加
3. **結果表**：兩條路徑並排列出
   - success / message
   - total_mass_full_kg
   - failure_index / buckling_index / twist_max_deg / tip_deflection_m
   - wall_time_s
   - timing_s 子欄（如有）
   - n_compute / n_compute_partials
4. **解讀**：
   - openmdao 路徑的 `n_compute_partials` 是否 > 0（這是 P3#13 派上用場的證據）
   - 兩條路徑的 mass 是否一致（驗證 openmdao driver 收斂到合理解）
   - 哪條更快、差幾倍
5. **下一步建議**：是否值得把 example default 切到 `method="openmdao"`，或同時保留兩條路（auto fallback）

### Step 4：commit & push

```
.venv/bin/python -m pytest -x -m "not slow"   # 確認沒打壞既有測試
git add src/hpa_mdo/structure/spar_model.py \
        examples/benchmark_openmdao_vs_scipy.py \
        docs/openmdao_vs_scipy_benchmark.md \
        docs/openmdao_vs_scipy_benchmark.json
git commit -m "bench: 比較 OpenMDAO driver 與 scipy 黑盒路徑（驗證 P3#13 解析偏導實際生效）"
git pull --rebase --autostash origin main
git push origin main
```

## 驗收標準（不滿足就不要 commit）

1. `pytest -x -m "not slow"` 全綠（既有 52 tests 不能因為 counter 變紅）
2. `examples/benchmark_openmdao_vs_scipy.py` 可獨立執行不丟例外
3. `docs/openmdao_vs_scipy_benchmark.md` 存在，且包含上述五個章節
4. 報告裡 openmdao 路徑的 `n_compute_partials` 必須有實際數字（不是 0 也不是 N/A），
   否則代表 driver 沒走到 derivative 計算 → 必須先排查再 commit
5. 報告裡 scipy 路徑的 `n_compute_partials` 應該為 0
   （這是 Codex 先前推論的直接證據，如果不是 0 反而要解釋為什麼）
6. 不要動 `examples/blackcat_004_optimize.py`、不要動 `_optimize_scipy()` 內部邏輯、
   不要動 `add_design_var` / `add_constraint` 設定

## 不要做的事（再次強調）

- 不要把 `examples/blackcat_004_optimize.py` 的 `method="scipy"` 改成 `"openmdao"`
- 不要在這個 PR 裡 refactor optimizer.py 或 oas_structural.py
- 不要新增任何測試（這是 read-only benchmark，不是功能變更）
- 不要把 counter 開放成 public API（純內部驗證用）
- 不要在報告裡寫「建議立刻切換」這種結論性話術；先呈現數據，由使用者決定
- 如果 `method="openmdao"` 跑 crash，**不要**為了讓它跑通去改 driver 設定，
  改成在報告裡完整貼出 traceback + 你 grep 出的原因，停在這一步等使用者裁示
