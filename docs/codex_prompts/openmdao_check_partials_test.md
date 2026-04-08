# Codex 任務：P1#7 OpenMDAO 全模型 check_partials 測試

## 背景

`docs/codex_tasks.md` P1#7 一直掛著「待做」。目前只有個別 component 的
check_partials（buckling、spar_properties、twist），但**整個 OpenMDAO problem
組合起來**是否每條偏導都正確，沒有端到端驗證。

P3#13 解析偏導完成後，這變得更急迫：若 `compute_partials()` 寫錯，SLSQP 會
朝錯誤方向收斂，且**不會報錯**（silent failure）。

## 必讀

- `/Volumes/Samsung SSD/hpa-mdo/CLAUDE.md`
- `/Volumes/Samsung SSD/hpa-mdo/src/hpa_mdo/structure/oas_structural.py`
  （`build_structural_problem` 函式）
- 既有的 component 級測試：`tests/test_buckling.py`、
  `tests/test_spar_properties_partials.py`、`tests/test_twist_constraint.py`

## 任務

### 1. 新增 `tests/test_partials.py`

```python
"""Whole-problem check_partials for OpenMDAO structural model."""
from __future__ import annotations

import numpy as np
import pytest

from hpa_mdo.core.config import load_config
from hpa_mdo.structure.oas_structural import build_structural_problem
from hpa_mdo.aero.load_mapper import LoadMapper
# ... 視需要 import 其他


@pytest.fixture(scope="module")
def structural_prob():
    cfg = load_config("configs/blackcat_004.yaml")
    # Build a minimal load case (use uniform load to avoid VSPAero IO)
    n_struct = 60
    span = cfg.geometry.half_span
    y = np.linspace(0, span, n_struct)
    loads = {
        "y": y,
        "lift_per_span": np.full(n_struct, 50.0),  # N/m
        "drag_per_span": np.full(n_struct, 1.0),
        "moment_per_span": np.zeros(n_struct),
        "chord": np.full(n_struct, 0.6),
    }
    prob = build_structural_problem(cfg, loads, force_alloc_complex=True)
    # Set design variables to mid-range
    for k in ("main_t_seg", "rear_t_seg"):
        try:
            prob[k] = np.full_like(prob[k], 0.0008)
        except KeyError:
            pass
    prob.run_model()
    return prob


def test_check_partials_full_model(structural_prob):
    """整個結構 problem 的 cs check_partials 全部 abs error < 1e-5."""
    data = structural_prob.check_partials(
        compact_print=True,
        method="cs",
        out_stream=None,
    )
    failures = []
    for comp_name, comp_data in data.items():
        for (of, wrt), errs in comp_data.items():
            abs_err = errs["abs error"][0]
            rel_err = errs["rel error"][0]
            # 容忍：abs<1e-5 或 rel<1e-5（小數值靠 abs，大數值靠 rel）
            if not (abs_err < 1e-5 or rel_err < 1e-5):
                failures.append(
                    f"{comp_name}: d({of})/d({wrt}) abs={abs_err:.2e} rel={rel_err:.2e}"
                )
    assert not failures, "Partial derivative errors:\n" + "\n".join(failures)


def test_check_totals_objective_to_dvs(structural_prob):
    """End-to-end check_totals: d(mass)/d(t_seg) 必須對得上 cs。"""
    data = structural_prob.check_totals(
        of=["struct.mass.total_mass_full"],
        wrt=["main_t_seg", "rear_t_seg"],
        method="cs",
        compact_print=True,
        out_stream=None,
    )
    for key, errs in data.items():
        assert errs["abs error"][0] < 1e-6 or errs["rel error"][0] < 1e-6, key
```

### 2. 注意事項

- **`force_alloc_complex=True`** 必須在 `prob.setup()` 時啟用，否則 cs 模式失效
- 如果 `build_structural_problem` 沒接受這個參數，需要加（也允許從 fixture 內手動 setup）
- 用 uniform load 而不是真實 VSPAero 載荷，避免測試依賴外部檔案
- 設計變數設成 mid-range（避開 0.5mm 上下界），不然某些 partial 在邊界退化

### 3. 如果有失敗

回報哪個 component 的哪條偏導壞掉。**不要自己改數學**，等使用者確認後再決定。
最有可能的嫌疑犯：
- `DualSparPropertiesComp`（剛改完 analytic）
- `BucklingComp`（cs 在 KS max-shift 邊界處可能有 round-off）
- `ExternalLoadsComp`（lumped mass 那段有 element length 乘法）

## 驗收

1. `pytest tests/test_partials.py -v` → 2 tests pass
2. `pytest tests/ -q --ignore=tests/test_blackcat_pipeline.py` → 54 tests pass
3. 如果發現任何 partial 錯誤，stop and report — **不要自行修正數學**

## Git

兩個 commit（如果一切順利只要一個）：
1. `test: 新增 tests/test_partials.py 全模型 check_partials 端到端驗證`
2. （若需修 bug）`fix: <component>.compute_partials 修正 ...`

完成後 `git pull --rebase --autostash origin main && git push origin main`。
