# M6 — `oas_structural.py` God-File 拆解（2040 行 → 7 個模組）

## 背景

`src/hpa_mdo/structure/oas_structural.py` 目前 **2040 行**，含 10 個 OpenMDAO
component class、2 個 group class、`build_structural_problem()`、`run_*` 函式、
`_extract_results()`、以及一堆 module-level helper（`_timoshenko_element_stiffness`、
`_cs_norm`、`_rotation_matrix`、`_transform_12x12`、`_normalise_load_case_inputs`、
`_elem_to_seg_mean` 等）。

問題：
- 單檔太大，難以 navigation、難以平行 review
- 元件之間的相依關係不顯眼（看不出來 `VonMisesStressComp` 用了 `_rotation_matrix`）
- 任何元件改動都會 touch 同一個檔，PR diff 難看
- 新人 onboarding 時這檔是 wall of text

> 前提：本任務必須等 M2 / M3 / M4 / M5 全部完成並 push 之後再開工。
> M6 是大重構，前面幾個 mission 留下的 commits 越穩，這次拆解越安全。

## 目標

把 `oas_structural.py` 拆成 7 個檔案，**完全保留現有對外行為**：所有現有的
import 路徑（例如 `from hpa_mdo.structure.oas_structural import build_structural_problem`）
都要繼續可用，所有測試要繼續通過，`check_totals` 兩個都要繼續通過。

**核心約束**：這是 **pure refactor**，不做任何邏輯修改。任何「順手優化」都要拒絕。

## 設計：目標檔案結構

```
src/hpa_mdo/structure/
├── oas_structural.py              ← 變成 re-export shim（~50 行）
├── fem/
│   ├── __init__.py
│   ├── elements.py                ← _timoshenko_element_stiffness, _rotation_matrix,
│   │                                _transform_12x12, _cs_norm, _has_only_finite_values
│   └── assembly.py                ← SpatialBeamFEM
├── components/
│   ├── __init__.py
│   ├── spar_props.py              ← DualSparPropertiesComp, SegmentToElementComp
│   ├── loads.py                   ← ExternalLoadsComp
│   └── constraints.py             ← VonMisesStressComp, KSFailureComp,
│                                    TwistConstraintComp, TipDeflectionConstraintComp,
│                                    StructuralMassComp
└── groups/
    ├── __init__.py
    ├── load_case.py               ← StructuralLoadCaseGroup
    └── main.py                    ← HPAStructuralGroup, _normalise_load_case_inputs,
                                     _is_single_mapped_load, build_structural_problem,
                                     run_analysis, run_optimization, _extract_results,
                                     _elem_to_seg_mean, compute_outer_radius_from_wing
```

**估行數**（總和應該約 2040 ± 100）：

| 新檔 | 內容 | 估行數 |
|------|------|-------|
| `fem/elements.py` | 5 個 helper 函式 | ~150 |
| `fem/assembly.py` | `SpatialBeamFEM` (618–865) | ~250 |
| `components/spar_props.py` | `SegmentToElementComp` + `DualSparPropertiesComp` (100–481) | ~380 |
| `components/loads.py` | `ExternalLoadsComp` (1078–1153) | ~80 |
| `components/constraints.py` | 5 個 constraint comp (866–1077, 1154–1230) | ~360 |
| `groups/load_case.py` | `StructuralLoadCaseGroup` (1231–1376) | ~150 |
| `groups/main.py` | `HPAStructuralGroup` + builders + helpers + 2 個 normalise/elem helper | ~700 |
| `oas_structural.py` (shim) | re-export 全部 public 名稱 | ~50 |

## 設計約束

**禁止**：
- 不要改任何 component 的 `setup()` / `compute()` / `compute_partials()` 內部邏輯
  ——一行都不要動
- 不要改任何 import 路徑的對外可見性。`from hpa_mdo.structure.oas_structural import X`
  必須對所有現有的 X 都繼續工作
- 不要改 `build_structural_problem()` 的簽章
- 不要改 component / group 的 class 名稱
- 不要新增任何新功能、新的 ExecComp、新的 constraint
- 不要動 `tests/`（除非新建的相對 import 在測試端炸掉，那就改 import path）
- 不要動 `optimizer.py` 的任何 import
- 不要動 `examples/` 的任何 import
- 不要 reformat / re-order import 區塊（diff 越小越好）
- 不要把 helper 函式從 module-private (`_xxx`) 改成 public

**允許**：
- 同一個 class 內部的 method 順序如果跨檔案搬不方便，可以動，但要在 PR description 註明
- 新檔的 module docstring 可以是 1–3 行英文 summary

## 要做的事

### Step 0：跑前快照

```bash
.venv/bin/python -m pytest -m "not slow" --tb=no -q 2>&1 | tail -5
.venv/bin/python -m pytest -m "not slow" -k "check_totals" -v 2>&1 | tail -20
```

把通過數量記下來。任何 commit 之後這個數字都不能掉。

### Step 1：建立目錄結構（純檔案搬移，零邏輯修改）

```bash
mkdir -p src/hpa_mdo/structure/fem
mkdir -p src/hpa_mdo/structure/components
mkdir -p src/hpa_mdo/structure/groups
touch src/hpa_mdo/structure/fem/__init__.py
touch src/hpa_mdo/structure/components/__init__.py
touch src/hpa_mdo/structure/groups/__init__.py
```

### Step 2：搬 `fem/elements.py`

把以下從 `oas_structural.py` 整段剪出來搬到 `fem/elements.py`：

| 行 | 名稱 |
|----|------|
| 482–561 | `_timoshenko_element_stiffness` |
| 562–566 | `_cs_norm` |
| 567–572 | `_has_only_finite_values` |
| 573–609 | `_rotation_matrix` |
| 610–617 | `_transform_12x12` |

`fem/elements.py` 開頭加：

```python
"""Low-level beam element kinematics and stiffness primitives.

These helpers are used by SpatialBeamFEM and are pure functions of
geometry / material — no state, no OpenMDAO. Kept module-private to
discourage downstream coupling outside the structure package.
"""
from __future__ import annotations

import numpy as np
```

把這些搬走後，**oas_structural.py 內 `SpatialBeamFEM` 的 import** 必須加：

```python
from hpa_mdo.structure.fem.elements import (
    _timoshenko_element_stiffness,
    _cs_norm,
    _has_only_finite_values,
    _rotation_matrix,
    _transform_12x12,
)
```

跑測試：
```bash
.venv/bin/python -m pytest -x -m "not slow"
```
**這一步必須全綠才能繼續。** 不綠的話 revert 重來，找出哪個 helper 漏搬。

### Step 3：搬 `fem/assembly.py`

把 `SpatialBeamFEM`（618–865）搬到 `fem/assembly.py`，
從 `fem.elements` import 上一步的 helpers。

`fem/__init__.py` 加：
```python
from hpa_mdo.structure.fem.assembly import SpatialBeamFEM
from hpa_mdo.structure.fem.elements import (
    _timoshenko_element_stiffness,
    _cs_norm,
    _has_only_finite_values,
    _rotation_matrix,
    _transform_12x12,
)
__all__ = ["SpatialBeamFEM"]
```

`oas_structural.py` 加：
```python
from hpa_mdo.structure.fem.assembly import SpatialBeamFEM  # noqa: F401
```

跑測試。全綠才繼續。

### Step 4：搬 `components/spar_props.py`

`SegmentToElementComp`（100–160）+ `DualSparPropertiesComp`（161–481）。

注意 `DualSparPropertiesComp` 內部用了 `compute_dual_spar_section()`，那是
`spar_model.py` 的東西，不要動 import 來源。

### Step 5：搬 `components/loads.py`

`ExternalLoadsComp`（1078–1153）。
注意它用了 `G_STANDARD`（M2 之後從 `core.constants` import），保持原樣。

### Step 6：搬 `components/constraints.py`

5 個 constraint comp 一起搬：
- `VonMisesStressComp` (866–995)
- `KSFailureComp` (996–1045)
- `StructuralMassComp` (1046–1077)
- `TwistConstraintComp` (1154–1205)
- `TipDeflectionConstraintComp` (1206–1230)

`components/__init__.py`：
```python
from hpa_mdo.structure.components.spar_props import (
    SegmentToElementComp,
    DualSparPropertiesComp,
)
from hpa_mdo.structure.components.loads import ExternalLoadsComp
from hpa_mdo.structure.components.constraints import (
    VonMisesStressComp,
    KSFailureComp,
    StructuralMassComp,
    TwistConstraintComp,
    TipDeflectionConstraintComp,
)

__all__ = [
    "SegmentToElementComp",
    "DualSparPropertiesComp",
    "ExternalLoadsComp",
    "VonMisesStressComp",
    "KSFailureComp",
    "StructuralMassComp",
    "TwistConstraintComp",
    "TipDeflectionConstraintComp",
]
```

每搬一個 component 跑一次 test。

### Step 7：搬 `groups/load_case.py`

`StructuralLoadCaseGroup`（1231–1376）。
這個 group 在 setup 內 import 一堆 component，全部改成從 `components.*` import。

### Step 8：搬 `groups/main.py`

最大也最棘手的一步。把以下全部搬過去：

| 行 | 名稱 |
|----|------|
| 43–47 | `_is_single_mapped_load` |
| 48–99 | `_normalise_load_case_inputs` |
| 1377–1684 | `HPAStructuralGroup` |
| 1685–1695 | `compute_outer_radius_from_wing` |
| 1696–1933 | `build_structural_problem` |
| 1934–1952 | `_elem_to_seg_mean` |
| 1953–1965 | `run_analysis` |
| 1966–1978 | `run_optimization` |
| 1979–2040 | `_extract_results` |

`groups/main.py` 內 import：
```python
from hpa_mdo.structure.fem.assembly import SpatialBeamFEM
from hpa_mdo.structure.components.spar_props import (
    SegmentToElementComp, DualSparPropertiesComp,
)
from hpa_mdo.structure.components.loads import ExternalLoadsComp
from hpa_mdo.structure.components.constraints import (
    VonMisesStressComp, KSFailureComp, StructuralMassComp,
    TwistConstraintComp, TipDeflectionConstraintComp,
)
from hpa_mdo.structure.groups.load_case import StructuralLoadCaseGroup
```

`groups/__init__.py`：
```python
from hpa_mdo.structure.groups.load_case import StructuralLoadCaseGroup
from hpa_mdo.structure.groups.main import (
    HPAStructuralGroup,
    build_structural_problem,
    run_analysis,
    run_optimization,
    compute_outer_radius_from_wing,
)
__all__ = [
    "StructuralLoadCaseGroup",
    "HPAStructuralGroup",
    "build_structural_problem",
    "run_analysis",
    "run_optimization",
    "compute_outer_radius_from_wing",
]
```

### Step 9：把 `oas_structural.py` 變成 re-export shim

最後 `oas_structural.py` 只剩：

```python
"""Backward-compat shim for the legacy oas_structural import path.

The structural OpenMDAO stack used to live in this single file. It has
been split across hpa_mdo.structure.{fem,components,groups} modules.
This module re-exports every public name so that existing imports
continue to work without modification.

New code should import directly from the package layout:

    from hpa_mdo.structure.fem import SpatialBeamFEM
    from hpa_mdo.structure.components import DualSparPropertiesComp
    from hpa_mdo.structure.groups import build_structural_problem
"""
from __future__ import annotations

# ── FEM primitives (kept module-private; re-exported for tests) ──
from hpa_mdo.structure.fem.elements import (
    _timoshenko_element_stiffness,
    _cs_norm,
    _has_only_finite_values,
    _rotation_matrix,
    _transform_12x12,
)
from hpa_mdo.structure.fem.assembly import SpatialBeamFEM

# ── OpenMDAO components ──
from hpa_mdo.structure.components.spar_props import (
    SegmentToElementComp,
    DualSparPropertiesComp,
)
from hpa_mdo.structure.components.loads import ExternalLoadsComp
from hpa_mdo.structure.components.constraints import (
    VonMisesStressComp,
    KSFailureComp,
    StructuralMassComp,
    TwistConstraintComp,
    TipDeflectionConstraintComp,
)

# ── Groups and entry points ──
from hpa_mdo.structure.groups.load_case import StructuralLoadCaseGroup
from hpa_mdo.structure.groups.main import (
    _is_single_mapped_load,
    _normalise_load_case_inputs,
    _elem_to_seg_mean,
    HPAStructuralGroup,
    compute_outer_radius_from_wing,
    build_structural_problem,
    run_analysis,
    run_optimization,
    _extract_results,
)

__all__ = [
    "SegmentToElementComp",
    "DualSparPropertiesComp",
    "SpatialBeamFEM",
    "VonMisesStressComp",
    "KSFailureComp",
    "StructuralMassComp",
    "ExternalLoadsComp",
    "TwistConstraintComp",
    "TipDeflectionConstraintComp",
    "StructuralLoadCaseGroup",
    "HPAStructuralGroup",
    "build_structural_problem",
    "run_analysis",
    "run_optimization",
    "compute_outer_radius_from_wing",
]
```

注意 `_xxx` 底線開頭的也 re-export，因為現有 `tests/` 與 `optimizer.py` 都是直接從
`oas_structural` import 它們的，**少 re-export 一個都會炸**。

### Step 10：完整測試 + check_totals

```bash
.venv/bin/python -m pytest -x -m "not slow"
.venv/bin/python -m pytest -v -k "check_totals"
.venv/bin/python -m pytest -v -k "spar_properties_partials"
.venv/bin/python -m pytest -v -k "multi_load_case"
```

四組都要全綠。任何一組掉 1 個就 stop ship，找到漏 export 的名稱補上。

### Step 11：grep 確認沒有殘留

```bash
# oas_structural.py 應該不再含任何 class 定義（全 import）
grep -n "^class " src/hpa_mdo/structure/oas_structural.py
# 預期：空輸出

# 任何測試或 production 程式碼都不該 from oas_structural import 私有名稱以外的東西
grep -rn "from hpa_mdo.structure.oas_structural" src/ tests/ examples/
# 預期：所有 import 行繼續存在，但都會走 shim
```

## 驗收標準

1. `pytest -m "not slow"` 通過數**等於**重構前的數字（不能掉一個）
2. `pytest -v -k check_totals` 兩個（單工況 + 多工況）都通過
3. `oas_structural.py` ≤ 80 行，**只**含 import 與 `__all__`，無 class / 無 def
4. 7 個新檔總行數約 2000 ± 200（不能多一倍——意味著有複製貼上）
5. `grep -rn "from hpa_mdo.structure.oas_structural" tests/ examples/` 顯示
   所有現有 import 行依然有效，且**沒有任何測試被改過**
6. `examples/blackcat_004_optimize.py` cold start 跑得起來，產生的
   `total_mass_full_kg` 與重構前的 baseline 相差 < 0.01 kg
   （拆解是 pure refactor，數字必須完全一致；浮點微差可以容忍但 ≥ 0.01 算 bug）
7. 所有新檔的 module docstring / 註解 / log 全英文（鐵律 #8）
8. M6 release notes 內容寫進 commit message body，包含「拆解動機 + 新檔對應表 + 驗收結果」

## 不要做的事

- 不要在這個 PR 改任何 component 的 algorithm
- 不要在這個 PR 改 ANSYS / NASTRAN export
- 不要在這個 PR 加新 unit test（refactor 期間 test surface 不變）
- 不要把私有 helper 提升成 public API
- 不要動 `from __future__ import annotations`
- 不要動既有 component class 的 docstring
- 不要 reformat（不要 black、不要 ruff fix --unsafe）
- 不要把 spar_props 內部對 `compute_dual_spar_section` 的呼叫改成新的 import 路徑
- 不要在 commit history 把這個 PR 拆成 7 個 commits——**單一 commit**，因為中間任何
  一步都會讓 tests 暫時不通過，分 commit 只會讓 bisect 變難

## Commit 訊息範本

```
refactor: 拆解 oas_structural.py（2040 行）為 7 個模組

動機：單檔過大難以 navigation 與 review；元件相依關係不顯眼。
本 commit 為 pure refactor，零邏輯修改。

新檔結構：
  structure/fem/elements.py     <helpers>
  structure/fem/assembly.py     SpatialBeamFEM
  structure/components/
    spar_props.py               SegmentToElementComp, DualSparPropertiesComp
    loads.py                    ExternalLoadsComp
    constraints.py              VonMises/KSFailure/Mass/Twist/TipDeflection
  structure/groups/
    load_case.py                StructuralLoadCaseGroup
    main.py                     HPAStructuralGroup, build_structural_problem, ...
  structure/oas_structural.py   re-export shim（< 80 行）

行為等價驗證：
- pytest -m "not slow"：<N>/<N> 通過（與重構前一致）
- pytest -k check_totals：兩個 case 都通過
- examples/blackcat_004_optimize.py cold start 結果與 baseline 完全一致
- 所有現有 from hpa_mdo.structure.oas_structural import X 維持有效
```

## 完成後

```
.venv/bin/python -m pytest -x -m "not slow"
git add -A src/hpa_mdo/structure/ docs/codex_prompts/M6_oas_structural_split.md
git commit -m "..."
git pull --rebase --autostash origin main
git push origin main
```
