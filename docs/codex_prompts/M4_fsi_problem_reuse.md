# M4 — FSI 問題重用（消除每 iter 重建 OpenMDAO Problem）

## 背景

`src/hpa_mdo/fsi/coupling.py:67`（`FSICoupling._solve_once`）目前長這樣：

```python
def _solve_once(self, aero_load, load_factor, optimizer_method):
    mapped = self.mapper.map_loads(...)
    optimizer = SparOptimizer(self.cfg, self.aircraft, mapped, self.materials_db)
    result = optimizer.optimize(method=...)
    return result, self._extract_deformed_z(result)
```

`run_two_way()` 在每次迭代都呼叫 `_solve_once()`，意味著
**每個 FSI iter 都重建一個全新的 SparOptimizer**，
而 `SparOptimizer.__init__()` 會呼叫 `build_structural_problem()`，
那是個包含 OpenMDAO `prob.setup()`、derivative declaration、矩陣 allocation 的重操作。

對 20 iter 的 two-way FSI 來說 = 20 次 setup overhead，**~10× 效能浪費**。

> 前提：本任務必須等 M3 API DRY 重構完成並 push 之後再開工。

## 目標

讓 `FSICoupling` 在 `__init__()` 時建立**一次** `SparOptimizer` 並重用，
之後每個 iter 只更新外部載荷（aero_loads）然後重新呼叫 `optimize()` / `analyze()`。

預期效果：
- two-way FSI（20 iter）總時間從 ~10500 s 降到 ~530 s（單次最佳化的時間）
- 因為**只有外部載荷在變**，OpenMDAO 內部所有的 component setup / partial declaration
  都不需要重做

## 設計約束

**禁止**：
- 不要破壞 `run_one_way()` 的行為（它目前依賴新 SparOptimizer 的 cold start）
- 不要動 `FSICoupling` 對外的 method 簽章
- 不要動 `FSIResult` dataclass 結構
- 不要改 `_normalize_optimizer_method()` / `_extract_deformed_z()`
- 不要在 `SparOptimizer` 上加 `update_loads()` 之外的任何新 public method
  （避免擴大 API 表面積）
- 不要動 `build_structural_problem()` 的簽章
- 不要直接操作 `prob.set_val("struct.case_xxx.ext_loads.lift_per_span", ...)` 之類的
  深層路徑——讓 SparOptimizer 自己負責這個

## 要做的事

### Step 1：在 `SparOptimizer` 加 `update_aero_loads()` 方法

**檔案**：`src/hpa_mdo/structure/optimizer.py`

在 `SparOptimizer` class 內加一個新 method（放在 `analyze()` 旁邊）：

```python
def update_aero_loads(self, aero_loads: dict) -> None:
    """Replace the aerodynamic loads on the existing OpenMDAO problem
    without rebuilding it.
    
    This is the FSI-friendly path: build_structural_problem() is expensive
    (component setup, partial declaration, matrix allocation), so for
    iterative FSI we want to keep the same Problem instance and only
    refresh the external load inputs between iterations.
    
    Parameters
    ----------
    aero_loads : dict
        Same shape as the aero_loads passed to __init__:
        either a mapped-load dict (legacy single-case) or
        {case_name: mapped_loads} for multi-case configs.
    
    Notes
    -----
    The new aero_loads must use the **same structural mesh** as the
    original problem (i.e. same n_nodes, same wing.y). If the mesh
    changes, you must rebuild the problem from scratch.
    """
    self.aero_loads = aero_loads
    
    # The problem already has ExternalLoadsComp instances bound at setup
    # time with lift_per_span / torque_per_span as options. We need to
    # push fresh values into them.
    #
    # Both the legacy single-case path and the multi-case path build
    # their ExternalLoadsComp(s) inside HPAStructuralGroup; we look them
    # up by case name and overwrite their `options` AND set the new
    # input vectors directly.
    
    case_entries = _normalise_load_case_inputs_for_update(self.cfg, aero_loads)
    
    for case_name, case_loads in case_entries.items():
        # Single-case legacy path stores ExternalLoadsComp at struct.ext_loads;
        # multi-case path stores it at struct.case_<name>.ext_loads.
        if len(case_entries) == 1 and not self.cfg.flight.cases:
            ext_loads_path = "struct.ext_loads"
        else:
            ext_loads_path = f"struct.case_{case_name}.ext_loads"
        
        # The lift / torque vectors are stored as ExternalLoadsComp.options,
        # not as inputs. We have to mutate the options and re-trigger setup
        # by setting an explicit input. The cleanest path: walk the model,
        # find the component, mutate options.
        comp = self._prob.model._get_subsystem(ext_loads_path)
        if comp is None:
            raise RuntimeError(
                f"Cannot locate ExternalLoadsComp at '{ext_loads_path}' "
                f"to refresh FSI loads."
            )
        comp.options["lift_per_span"] = np.asarray(
            case_loads["lift_per_span"], dtype=float
        )
        comp.options["torque_per_span"] = np.asarray(
            case_loads.get("torque_per_span", np.zeros_like(case_loads["lift_per_span"])),
            dtype=float,
        )
```

**重要**：

1. 如果 `ExternalLoadsComp` 把 `lift_per_span` / `torque_per_span` 存成
   `om.options` 或 `np.array` attribute，那 mutate options 就夠了。
   但如果它在 `setup()` 內把 options 拷貝成 instance attribute（例如
   `self._lift = options["lift_per_span"]`），mutation **不會生效**。
   開工前必須先 `grep -n "lift_per_span" src/hpa_mdo/structure/oas_structural.py`
   看 ExternalLoadsComp 怎麼用 lift_per_span，必要時擴張 `update_aero_loads`
   去動正確的位置。
2. 如果發現 ExternalLoadsComp 的設計就是「lift_per_span 在 setup 時 frozen」
   ——那就**順便重構 ExternalLoadsComp**：把 lift / torque 從 options 改成
   inputs，這樣 `prob.set_val(...)` 就直接生效，update_aero_loads 也變成單行。
   這個改動的副作用是要更新 declare_partials 的處理，且要確認 check_totals 還能過。
3. **不要**在這層處理「mesh 大小變動」的情境，那不是 FSI 用例（FSI iter 只變載荷不變網格）。
   有 size mismatch 直接 raise ValueError。

### Step 2：寫一個 helper `_normalise_load_case_inputs_for_update`

如果 `oas_structural.py` 的 `_normalise_load_case_inputs()` 是 module-private
（單底線），可以直接 `from hpa_mdo.structure.oas_structural import _normalise_load_case_inputs`
重用。**不要複製貼上邏輯**。

### Step 3：改寫 `FSICoupling`

**檔案**：`src/hpa_mdo/fsi/coupling.py`

把 `__init__` 改成：

```python
def __init__(
    self,
    cfg,
    aircraft,
    materials_db,
    load_mapper: Optional[LoadMapper] = None,
):
    self.cfg = cfg
    self.aircraft = aircraft
    self.materials_db = materials_db
    self.mapper = load_mapper or LoadMapper()
    # FSI iterative path reuses one SparOptimizer instance to avoid
    # paying OpenMDAO setup() overhead per iteration. Lazy-built on
    # first _solve_once() call so we have a real aero_loads to seed it.
    self._optimizer: Optional[SparOptimizer] = None
```

把 `_solve_once()` 改成：

```python
def _solve_once(
    self,
    aero_load: SpanwiseLoad,
    load_factor: float,
    optimizer_method: str,
) -> tuple[OptimizationResult, np.ndarray]:
    mapped = self.mapper.map_loads(
        aero_load,
        self.aircraft.wing.y,
        scale_factor=load_factor,
        actual_velocity=self.cfg.flight.velocity,
        actual_density=self.cfg.flight.air_density,
    )

    if self._optimizer is None:
        self._optimizer = SparOptimizer(
            self.cfg, self.aircraft, mapped, self.materials_db
        )
    else:
        self._optimizer.update_aero_loads(mapped)

    result = self._optimizer.optimize(
        method=self._normalize_optimizer_method(optimizer_method)
    )
    return result, self._extract_deformed_z(result)
```

注意 `run_one_way()` 也會走到 `_solve_once()`，所以一次性 build + 放在 `self._optimizer`
對 one-way 完全沒副作用（cold start 一次而已）。

### Step 4：寫測試 `tests/test_fsi_problem_reuse.py`

```python
"""FSI 問題重用驗證：確保 two-way FSI 不會在每個 iter 重建 SparOptimizer。"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock

import numpy as np
import pytest

from hpa_mdo.aero.base import SpanwiseLoad
from hpa_mdo.core.aircraft import Aircraft
from hpa_mdo.core.config import load_config
from hpa_mdo.core.materials import MaterialDB
from hpa_mdo.fsi.coupling import FSICoupling
from hpa_mdo.structure.optimizer import SparOptimizer


REPO_ROOT = Path(__file__).resolve().parents[1]


def _make_aero(span_half: float) -> SpanwiseLoad:
    y = np.linspace(0.0, span_half, 12)
    return SpanwiseLoad(
        y=y,
        chord=np.full(12, 1.0),
        cl=np.full(12, 0.55),
        cd=np.full(12, 0.02),
        cm=np.full(12, 0.04),
        lift_per_span=np.full(12, 75.0),
        drag_per_span=np.full(12, 2.0),
        aoa_deg=3.0,
        velocity=10.0,
        dynamic_pressure=0.5 * 1.225 * 10.0**2,
    )


def test_fsi_two_way_reuses_single_optimizer_instance():
    cfg = load_config(REPO_ROOT / "configs" / "blackcat_004.yaml")
    with patch.object(cfg.solver, "n_beam_nodes", 10):
        aircraft = Aircraft.from_config(cfg)
    mat_db = MaterialDB()

    # Use one-way to avoid the actual DE solve cost; we only want to
    # verify that __init__ is called exactly once.
    fsi = FSICoupling(cfg, aircraft, mat_db)

    init_calls = []
    update_calls = []

    real_init = SparOptimizer.__init__
    real_update = getattr(SparOptimizer, "update_aero_loads", None)

    def spy_init(self, *args, **kwargs):
        init_calls.append(1)
        return real_init(self, *args, **kwargs)

    def spy_update(self, *args, **kwargs):
        update_calls.append(1)
        return real_update(self, *args, **kwargs)

    with patch.object(SparOptimizer, "__init__", spy_init), \
         patch.object(SparOptimizer, "update_aero_loads", spy_update), \
         patch.object(SparOptimizer, "optimize", lambda self, method="auto":
                      MagicMock(tip_deflection_m=0.1, disp=np.zeros((aircraft.wing.n_stations, 6)))):
        # Two synthetic FSI iterations
        fsi._solve_once(_make_aero(aircraft.wing.half_span), 1.0, "auto")
        fsi._solve_once(_make_aero(aircraft.wing.half_span), 1.0, "auto")
        fsi._solve_once(_make_aero(aircraft.wing.half_span), 1.0, "auto")

    assert sum(init_calls) == 1, (
        f"Expected SparOptimizer to be built once, got {sum(init_calls)} builds"
    )
    assert sum(update_calls) == 2, (
        f"Expected update_aero_loads to be called twice, got {sum(update_calls)}"
    )


def test_fsi_one_way_still_works():
    """Smoke test: run_one_way must still produce a valid FSIResult."""
    cfg = load_config(REPO_ROOT / "configs" / "blackcat_004.yaml")
    with patch.object(cfg.solver, "n_beam_nodes", 10):
        aircraft = Aircraft.from_config(cfg)
    mat_db = MaterialDB()
    fsi = FSICoupling(cfg, aircraft, mat_db)

    with patch.object(SparOptimizer, "optimize",
                      lambda self, method="auto": MagicMock(
                          tip_deflection_m=0.1,
                          disp=np.zeros((aircraft.wing.n_stations, 6)),
                      )):
        result = fsi.run_one_way(
            _make_aero(aircraft.wing.half_span),
            optimizer_method="scipy",
        )

    assert result.converged is True
    assert result.n_iterations == 1
```

## 驗收標準

1. `pytest -x -m "not slow" tests/test_fsi_problem_reuse.py` 兩個測試都過
2. `pytest -x -m "not slow"` 全綠（所有現有測試）
3. `update_aero_loads()` 在 `SparOptimizer` 內 docstring 完整、英文
4. **沒有**新建 module-level helper、沒有動 `build_structural_problem()` 簽章
5. `coupling.py` 的 `FSICoupling.__init__` / `_solve_once` 改動 < 30 行
6. 如果為了讓 update 生效**順便重構了 ExternalLoadsComp**（lift/torque options → inputs），
   `tests/test_partials.py::test_check_totals_full_structural_model` 與
   `test_check_totals_multi_case_structural_model` 兩個都必須繼續通過
7. 程式碼註解 / docstring 全英文（鐵律 #8）

## 不要做的事

- 不要在這個 PR 加 FSI 多工況支援（FSI 目前只跑單一 flight condition，那是另一個 mission）
- 不要 refactor `_extract_deformed_z()`、`_validate_two_way_backend()`
- 不要在這個 PR 動 `LoadMapper`
- 不要把 FSI 改成跑 derivative-based 路徑（本任務只是 perf reuse，不改最佳化方法）
- 不要加 logging.info 描述效能改善（測試會驗證 init_calls，不需要文字 log）

## Commit 訊息範本

```
perf: FSI 兩向耦合重用 SparOptimizer instance（消除 per-iter setup 開銷）

- FSICoupling.__init__ 改為 lazy-build self._optimizer
- _solve_once() 第一次走 SparOptimizer(...)，後續走 update_aero_loads()
- SparOptimizer 新增 update_aero_loads(aero_loads) 方法：在不重建 problem
  的前提下重設外部載荷，支援 legacy 單工況與 {case_name: ...} 多工況
- 新增 tests/test_fsi_problem_reuse.py：以 spy 驗證 __init__ 只發生 1 次、
  update_aero_loads 在後續 iter 被呼叫；run_one_way smoke test 不變
- 預期 two-way FSI（20 iter）效能提升約 10×（消除 prob.setup() overhead）
```

## 完成後

```
.venv/bin/python -m pytest -x -m "not slow"
git add -A src/ tests/test_fsi_problem_reuse.py docs/codex_prompts/M4_fsi_problem_reuse.md
git commit -m "..."
git pull --rebase --autostash origin main
git push origin main
```
