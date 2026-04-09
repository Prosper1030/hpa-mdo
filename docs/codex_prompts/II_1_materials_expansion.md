# Phase II Milestone II-1 — 擴充 `data/materials.yaml`（HPA 全料庫）

**優先度：高**　｜　**前置條件：Milestone 1 全綠（M2–M6 完成）**

---

## 背景

目前 `data/materials.yaml` 只有 7 種材料：三種碳纖、鋁合金、鋼、巴沙木、克維拉。
這勉強夠用於主翼梁最佳化，但後續 Phase II 任務（翼肋質量模型、蒙皮層疊最佳化、
拉索系統、接頭分析）都需要存取更完整的 HPA 材料庫。

缺少的材料類型：

| 類型 | 典型應用 |
|------|----------|
| 泡沫核心（Rohacell 31/51、巴沙木修訂值） | 翼肋核心、夾層板 |
| 織物增強材（Kevlar 49 補強、E-glass UD） | 蒙皮、翼肋面板 |
| 預浸布（CFRP prepreg UD T700） | 蒙皮蒙皮、D-box 補強 |
| 金屬接頭材（Ti-6Al-4V） | 高應力接頭與鉸鏈 |
| 張力索（Dyneema SK75） | 升力鋼索（tension-only） |

> **注意**：`balsa` 已存在於 `data/materials.yaml`，**不得修改**。
> 本任務新增 `rohacell_31`、`rohacell_51` 作為獨立條目，並新增其餘材料。

---

## 目標

1. 在 `data/materials.yaml` 新增 8 種材料（不動現有 7 種）
2. 在 `Material` dataclass 新增 2 個 optional 欄位：`shear_strength` 與 `tension_only`
3. 新增 `tests/test_materials_expand.py` 驗證每個新材料都能被 `MaterialDB` 載入
4. 不改動 `MaterialDB` 對外 API、不改動 optimizer 對材料的存取方式

---

## Step 1：閱讀現有檔案（必做，禁止跳過）

```bash
cat data/materials.yaml
cat src/hpa_mdo/core/materials.py
```

確認以下事項後再動筆：

- 現有欄位：`name`, `E`, `G`, `density`, `tensile_strength`, `compressive_strength`,
  `poisson_ratio`, `description`
- `compressive_strength` 已經是 `Optional[float] = None`（null 合法）
- `G` 缺席時，`MaterialDB._load()` 會自動用 `E / (2*(1+nu))` 推算
- `Material` 是 `@dataclass(frozen=True)`，加欄位要同步改 `_load()` 的實例化

---

## Step 2：擴充 `Material` dataclass

開啟 `src/hpa_mdo/core/materials.py`，在 `compressive_strength` 欄位之後新增：

```python
shear_strength: Optional[float] = None   # in-plane shear failure strength [Pa]
tension_only: Optional[bool] = None      # True = member carries tension only (e.g. cables)
```

同時更新 `MaterialDB._load()` 中的 `Material(...)` 實例化，加入這兩個欄位：

```python
self._materials[key] = Material(
    name=props.get("name", key),
    E=float(props["E"]),
    G=float(props["G"]) if "G" in props else float(props["E"]) / (2 * (1 + float(props.get("poisson_ratio", 0.3)))),
    density=float(props["density"]),
    tensile_strength=float(props["tensile_strength"]),
    compressive_strength=float(props["compressive_strength"]) if props.get("compressive_strength") else None,
    poisson_ratio=float(props.get("poisson_ratio", 0.3)),
    description=props.get("description", ""),
    shear_strength=float(props["shear_strength"]) if props.get("shear_strength") else None,
    tension_only=bool(props["tension_only"]) if props.get("tension_only") is not None else None,
)
```

**不要改動** `sigma_c` property、`MaterialDB.get()`、`MaterialDB.register()` 等其他方法。

---

## Step 3：在 `data/materials.yaml` 新增 8 種材料

在現有最後一個條目（`kevlar_49`）之後，**逐條附加**以下內容。
**絕對不要修改** `carbon_fiber_hm`、`carbon_fiber_std`、`carbon_fiber_im`、
`aluminum_6061_t6`、`steel_4130`、`balsa`、`kevlar_49` 這 7 個已有條目。

```yaml
# =============================================================================
# Phase II additions — HPA expanded material library
# Added: 2026-04-09 (Phase II Milestone II-1)
# =============================================================================

rohacell_31:
  name: "Rohacell 31 IG (closed-cell PMI foam)"
  E: 36.0e6               # Young's modulus [Pa]
  G: 13.0e6               # Shear modulus [Pa]
  density: 32.0            # [kg/m³]
  tensile_strength: 0.5e6  # UTS [Pa]
  compressive_strength: 0.4e6
  poisson_ratio: 0.38
  description: "Rib core, sandwich panel core — very low density"

rohacell_51:
  name: "Rohacell 51 IG (closed-cell PMI foam)"
  E: 70.0e6
  G: 24.0e6
  density: 52.0
  tensile_strength: 1.0e6
  compressive_strength: 0.8e6
  poisson_ratio: 0.38
  description: "Rib core — higher density/stiffness than Rohacell 31"

kevlar_49_ud:
  name: "Kevlar 49 Unidirectional"
  E: 125.0e9
  G: 2.9e9
  density: 1380.0
  tensile_strength: 3600.0e6
  compressive_strength: 290.0e6
  poisson_ratio: 0.34
  description: "UD Kevlar tape; high tensile strength, poor in compression"

eglass_ud:
  name: "E-Glass UD (unidirectional)"
  E: 45.0e9
  G: 5.0e9
  density: 2100.0
  tensile_strength: 1000.0e6
  compressive_strength: 620.0e6
  poisson_ratio: 0.28
  description: "E-glass UD roving/tape; skin and rib face-sheet layups"

dyneema_sk75:
  name: "Dyneema SK75 (UHMWPE fibre)"
  E: 108.0e9
  G: null                  # tension-only member; shear mode irrelevant
  density: 970.0
  tensile_strength: 3500.0e6
  compressive_strength: null
  poisson_ratio: null
  tension_only: true
  description: "Lift wire / bracing cord — tension only, zero buckling capacity"

titanium_6al4v:
  name: "Titanium 6Al-4V (Grade 5)"
  E: 114.0e9
  G: 44.0e9
  density: 4430.0
  tensile_strength: 950.0e6
  compressive_strength: 950.0e6
  poisson_ratio: 0.34
  description: "High-stress fittings, hinges, cable end-fittings"

cfrp_prepreg_t700:
  name: "CFRP Prepreg UD T700/250°F epoxy"
  E: 135.0e9
  G: 5.5e9
  density: 1550.0
  tensile_strength: 2550.0e6
  compressive_strength: 1500.0e6
  poisson_ratio: 0.30
  description: "Autoclave-cured UD tape; spar cap strip, D-box skin"

eglass_woven:
  name: "E-Glass Plain Weave Fabric (cured)"
  E: 23.0e9               # balanced in-plane modulus [Pa]
  G: 4.5e9
  density: 1850.0
  tensile_strength: 350.0e6
  compressive_strength: 280.0e6
  shear_strength: 65.0e6
  poisson_ratio: 0.17
  description: "0/90 balanced weave; skin closeout and torsion box wrap"
```

---

## Step 4：處理 `dyneema_sk75` 的 null G

`dyneema_sk75` 的 `G` 與 `poisson_ratio` 都是 `null`。
`MaterialDB._load()` 目前的邏輯在 `G` 不存在時用 `E/(2*(1+nu))` 推算，
但 `poisson_ratio` 也是 null 會導致 `TypeError`。

在 `_load()` 的 G 推算處改為：

```python
G=float(props["G"]) if props.get("G") is not None else (
    float(props["E"]) / (2 * (1 + float(props.get("poisson_ratio") or 0.3)))
),
```

同樣的防護也需要套用到 `poisson_ratio`：

```python
poisson_ratio=float(props["poisson_ratio"]) if props.get("poisson_ratio") is not None else 0.3,
```

---

## Step 5：新增測試 `tests/test_materials_expand.py`

```python
"""Regression tests for Phase II material library expansion.

Verifies that every newly added material can be loaded by MaterialDB
and exposes non-None density and Young's modulus.  Does NOT test any
optimizer behaviour — purely a DB integrity check.
"""
from __future__ import annotations

from pathlib import Path
from typing import List

import pytest

from hpa_mdo.core.materials import MaterialDB

REPO_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = REPO_ROOT / "data" / "materials.yaml"

# All material keys added in Phase II Milestone II-1.
# Do NOT include keys from the original 7 — those are tested elsewhere.
NEW_MATERIAL_KEYS: List[str] = [
    "rohacell_31",
    "rohacell_51",
    "kevlar_49_ud",
    "eglass_ud",
    "dyneema_sk75",
    "titanium_6al4v",
    "cfrp_prepreg_t700",
    "eglass_woven",
]


@pytest.fixture(scope="module")
def mat_db() -> MaterialDB:
    return MaterialDB(path=DB_PATH)


@pytest.mark.parametrize("key", NEW_MATERIAL_KEYS)
def test_new_material_loadable(mat_db: MaterialDB, key: str) -> None:
    """Each new material key must be present in the DB."""
    assert key in mat_db, (
        f"Material '{key}' not found in {DB_PATH}. "
        f"Available keys: {sorted(mat_db.keys())}"
    )


@pytest.mark.parametrize("key", NEW_MATERIAL_KEYS)
def test_new_material_density_not_none(mat_db: MaterialDB, key: str) -> None:
    mat = mat_db.get(key)
    assert mat.density is not None and mat.density > 0, (
        f"Material '{key}' has invalid density: {mat.density}"
    )


@pytest.mark.parametrize("key", NEW_MATERIAL_KEYS)
def test_new_material_E_not_none(mat_db: MaterialDB, key: str) -> None:
    mat = mat_db.get(key)
    assert mat.E is not None and mat.E > 0, (
        f"Material '{key}' has invalid Young's modulus: {mat.E}"
    )


def test_dyneema_is_tension_only(mat_db: MaterialDB) -> None:
    """Dyneema SK75 must carry tension_only flag."""
    mat = mat_db.get("dyneema_sk75")
    assert mat.tension_only is True, (
        "dyneema_sk75 must have tension_only=True; "
        f"got tension_only={mat.tension_only}"
    )


def test_dyneema_no_compressive_strength(mat_db: MaterialDB) -> None:
    """Dyneema SK75 has no compressive strength — compressive_strength must be None."""
    mat = mat_db.get("dyneema_sk75")
    assert mat.compressive_strength is None, (
        f"dyneema_sk75 compressive_strength should be None, got {mat.compressive_strength}"
    )


def test_eglass_woven_has_shear_strength(mat_db: MaterialDB) -> None:
    """E-glass woven fabric must expose a non-None shear_strength."""
    mat = mat_db.get("eglass_woven")
    assert mat.shear_strength is not None and mat.shear_strength > 0, (
        f"eglass_woven shear_strength should be a positive float, got {mat.shear_strength}"
    )


def test_original_materials_untouched(mat_db: MaterialDB) -> None:
    """Regression guard: original 7 materials must still load with correct E values."""
    expected = {
        "carbon_fiber_hm": 230.0e9,
        "carbon_fiber_std": 135.0e9,
        "carbon_fiber_im": 175.0e9,
        "aluminum_6061_t6": 68.9e9,
        "steel_4130": 205.0e9,
        "balsa": 3.4e9,
        "kevlar_49": 112.0e9,
    }
    for key, e_expected in expected.items():
        mat = mat_db.get(key)
        assert abs(mat.E - e_expected) / e_expected < 1e-6, (
            f"Original material '{key}' E changed: expected {e_expected:.3e}, "
            f"got {mat.E:.3e}. Do NOT modify existing material entries."
        )
```

---

## Step 6：執行驗證

```bash
# 確認既有測試全綠（不要打壞任何東西）
.venv/bin/python -m pytest -x -m "not slow" --tb=short -q

# 跑新材料測試
.venv/bin/python -m pytest -v tests/test_materials_expand.py

# 快速冒煙：確認 MaterialDB 直接呼叫不炸
.venv/bin/python -c "
from hpa_mdo.core.materials import MaterialDB
db = MaterialDB()
for key in ['rohacell_31', 'rohacell_51', 'kevlar_49_ud', 'eglass_ud',
            'dyneema_sk75', 'titanium_6al4v', 'cfrp_prepreg_t700', 'eglass_woven']:
    m = db.get(key)
    print(f'{key:25s}  E={m.E:.3e}  rho={m.density}  tension_only={m.tension_only}')
"

# 確認 optimizer 不受影響（基準案例仍可跑）
.venv/bin/python examples/blackcat_004_optimize.py 2>&1 | tail -3
```

期望輸出：

- `pytest -m "not slow"` 通過數等於或大於重構前（不能掉）
- `test_materials_expand.py` 全 16 個測試通過
- 冒煙腳本輸出 8 行，每行 `E` 與 `density` 非零
- `blackcat_004_optimize.py` 最後一行仍為 `val_weight: <float>`，數值相較 M5 baseline 不超過 ±0.01 kg

---

## 驗收標準

| # | 項目 | 判斷方式 |
|---|------|----------|
| 1 | 8 個新材料鍵全部存在於 `materials.yaml` | `test_new_material_loadable` 全綠 |
| 2 | 每個新材料 `density > 0` 且 `E > 0` | `test_new_material_density/E_not_none` 全綠 |
| 3 | `dyneema_sk75.tension_only == True` | `test_dyneema_is_tension_only` 通過 |
| 4 | `dyneema_sk75.compressive_strength is None` | `test_dyneema_no_compressive_strength` 通過 |
| 5 | `eglass_woven.shear_strength > 0` | `test_eglass_woven_has_shear_strength` 通過 |
| 6 | 原有 7 種材料 `E` 值未被動 | `test_original_materials_untouched` 通過 |
| 7 | `pytest -m "not slow"` 通過數不減少 | 執行前後數量比對 |
| 8 | `blackcat_004_optimize.py` 輸出 `val_weight: <float>` | 末行格式確認 |
| 9 | `Material` dataclass 新增 `shear_strength` 與 `tension_only` | grep 確認欄位存在 |
| 10 | `MaterialDB._load()` 正確讀取新欄位（null 安全） | 冒煙腳本不拋例外 |

---

## 不要做的事

- **不要修改**任何已有材料條目（`carbon_fiber_hm` 等 7 條）
- **不要**在 Python 程式碼中硬編碼材料屬性數值（鐵律 #1 與 #5）
- **不要**在 `MaterialDB.get()` 或 `MaterialDB.register()` 加入新的業務邏輯
- **不要**在 `optimizer.py`、`spar_model.py` 或任何求解器程式碼中變更材料取用方式
- **不要**把 `tension_only` 的判斷邏輯注入到 FEM 求解器（那是 Phase II 後續任務）
- **不要**新增 `MaterialCategory` enum 或其他分類機制（超出本 milestone 範疇）
- **不要**為新材料建立 ANSYS 截面定義（那屬於 CAE 匯出任務）
- **不要**修改 `core/config.py`（本任務不新增任何 config 欄位）

---

## Commit 訊息範本

```
feat(materials): 擴充 HPA 材料庫，新增 8 種 Phase II 材料（II-1）

data/materials.yaml:
  新增 rohacell_31, rohacell_51（PMI 泡沫核心）
  新增 kevlar_49_ud（UD Kevlar 帶材，修正模量）
  新增 eglass_ud, eglass_woven（E-glass UD 與平紋織物）
  新增 dyneema_sk75（張力索，tension_only=true）
  新增 titanium_6al4v（高應力接頭用鈦合金）
  新增 cfrp_prepreg_t700（T700 預浸布）
  未動原有 7 種材料

src/hpa_mdo/core/materials.py:
  Material dataclass 新增 shear_strength: Optional[float] = None
  Material dataclass 新增 tension_only: Optional[bool] = None
  MaterialDB._load() 對應讀取新欄位，null 安全

tests/test_materials_expand.py:
  16 個參數化測試，覆蓋載入 + density/E 非零 + 特殊屬性驗證
  regression guard 確認原 7 種材料 E 值未被動

優化結果：blackcat_004 baseline mass 未改變（± 0.01 kg 內）
```

---

## 完成後

```bash
.venv/bin/python -m pytest -v tests/test_materials_expand.py
.venv/bin/python -m pytest -x -m "not slow" -q
git add data/materials.yaml \
        src/hpa_mdo/core/materials.py \
        tests/test_materials_expand.py \
        docs/codex_prompts/II_1_materials_expansion.md
git commit -m "..."
git pull --rebase --autostash origin main
git push origin main
```
