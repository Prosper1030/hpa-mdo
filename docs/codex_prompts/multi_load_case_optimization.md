# Codex 任務：P4#17 多工況優化（multi load case）

## 背景與動機

目前 `blackcat_004.yaml` 只用單一巡航工況優化。HPA 實際上會遇到三種代表性工況：

| 工況 | 描述 | n_load_factor | 特徵 |
|------|------|---------------|------|
| `cruise` | 巡航 | 1.0 | 撓度可能 active |
| `gust` | 突風 | 2.5 | failure_index 可能 active |
| `turn` | 急轉彎 | 1.5 | twist 可能 active |

理想情況下，每個工況都要滿足自己的應力 / 撓度 / 扭轉 / 屈曲約束，
**目標仍是單一質量**（飛機只有一套翼梁）。

## 必讀

- `/Volumes/Samsung SSD/hpa-mdo/CLAUDE.md`
- `/Volumes/Samsung SSD/hpa-mdo/src/hpa_mdo/core/config.py`（`FlightConfig` / `SafetyConfig`）
- `/Volumes/Samsung SSD/hpa-mdo/src/hpa_mdo/structure/oas_structural.py`
  （`build_structural_problem`，理解現有 LoadComp / FailureComp / TwistConstraintComp / BucklingComp 接線）
- `/Volumes/Samsung SSD/hpa-mdo/src/hpa_mdo/structure/optimizer.py`
  （`_optimize_scipy` 的 `_eval` / `penalty_obj` / SLSQP constraints）
- `/Volumes/Samsung SSD/hpa-mdo/configs/blackcat_004.yaml`

## 設計

### 1. Config schema 擴充

在 `core/config.py` 新增：

```python
class FlightCase(BaseModel):
    name: str
    velocity: float
    air_density: float
    aerodynamic_load_factor: float
    max_tip_deflection_m: Optional[float] = None  # None 表示用 safety 預設
    max_twist_deg: Optional[float] = None

class FlightConfig(BaseModel):
    # 既有欄位保留作為單工況「向後相容預設」
    velocity: float
    air_density: float
    aerodynamic_load_factor: float
    # 新增
    cases: List[FlightCase] = Field(default_factory=list)
```

`yaml` 範例（在 `flight:` 區塊下加）：

```yaml
flight:
  velocity: 9.5
  air_density: 1.225
  aerodynamic_load_factor: 1.5
  cases:
    - name: cruise
      velocity: 9.5
      air_density: 1.225
      aerodynamic_load_factor: 1.0
    - name: gust
      velocity: 9.5
      air_density: 1.225
      aerodynamic_load_factor: 2.5
    - name: turn
      velocity: 11.0
      air_density: 1.225
      aerodynamic_load_factor: 1.5
```

**向後相容**：若 `cases` 為空，行為與目前完全相同。

### 2. OpenMDAO 模型重構策略

兩種選擇：

**方案 A：單一 problem 內裝多個 case 子系統**（推薦）
- `struct_cruise / struct_gust / struct_turn` 三個 group，各自有 LoadComp
  / 撓度 / 應力 / 扭轉 / 屈曲，**共用同一組設計變數** `main_t_seg / rear_t_seg`
- 約束改名：`failure_cruise / failure_gust / failure_turn` 等
- mass 只算一次（與工況無關）

**方案 B：跑 N 次 problem，外面包一層**
- 簡單但每個 SLSQP step 要 N× evaluation
- 不推薦，會破壞 timing 結構

走方案 A。`build_structural_problem` 改為接受 `loads_dict: dict[str, dict]`
（key 為 case name），對每個 case 建立平行的子 group。

### 3. `optimizer.py` 配套修改

`_eval()` 字典回傳每個 case 的約束值：

```python
res = {
    "mass": _get_scalar("struct.mass.total_mass_full"),
    "failure": {name: _get_scalar(f"struct_{name}.failure.failure") for name in case_names},
    "twist": {name: _get_scalar(f"struct_{name}.twist.twist_max_deg") for name in case_names},
    "tip_defl": {name: _get_scalar(f"struct_{name}.tip_defl.tip_deflection_m") for name in case_names},
    "buckling": {name: _get_scalar(f"struct_{name}.buckling.buckling_index") for name in case_names},
}
```

`penalty_obj` 對每個 case 都套相同懲罰（500 / 800 / 1000 係數）。
SLSQP `constraints` 列表變成 `4 × n_cases` 個。
`de_feas / sq_feas` 對每個 case 都檢查。

### 4. `OptimizationResult` 擴充

```python
@dataclass
class OptimizationResult:
    ...
    failure_index: float | dict[str, float]    # 單工況維持 float
    buckling_index: float | dict[str, float]
    twist_max_deg: float | dict[str, float]
    tip_deflection_m: float | dict[str, float]
```

`__str__` 視需要列印每個 case 一行。

### 5. 載荷產生

`LoadMapper` 已經接受 velocity / density / load_factor 參數。
對每個 case 各呼叫一次 `map_loads()`，得到 N 份 spanwise loads dict。

## 測試

### `tests/test_multi_load_case.py`

```python
def test_single_case_backward_compat():
    """cases=[] 時行為與舊版完全相同（同 val_weight）。"""

def test_multi_case_problem_builds():
    """3 個 cases 時 problem 能成功 setup 且 run_model 收斂。"""

def test_multi_case_constraints_per_case():
    """每個 case 都有獨立的 failure/twist/buckling/tip_defl 約束。"""

def test_gust_case_drives_thicker_walls():
    """用 cruise + gust 兩工況跑，比只用 cruise 重至少 5%。"""
```

### 整合測試

新增 `examples/blackcat_004_multicase.py`，跑三工況優化，輸出
`val_weight: <float>`。

## 驗收

1. `pytest tests/ -q --ignore=tests/test_blackcat_pipeline.py` 全過
2. `python examples/blackcat_004_optimize.py` → `val_weight: 14.3579 ± 0.01`
   （單工況回歸，cases=[] 時數值不變）
3. `python examples/blackcat_004_multicase.py` → 質量 > 14.36 kg 且每個 case
   的所有約束都滿足
4. summary 報告為每個 case 列印一個區塊

## 不要做的事

- ❌ 不要動單工況路徑的數學（必須完全 backward compatible）
- ❌ 不要把 mass 變成工況相關
- ❌ 不要重構 `BucklingComp / DualSparPropertiesComp` 內部
- ❌ 不要動 KS ρ 設定

## Git 工作流

四個 commit：
1. `feat: config schema 加入 FlightCase 多工況支援`
2. `feat: build_structural_problem 支援多工況平行子系統`
3. `feat: optimizer 多工況約束 + OptimizationResult 擴充`
4. `test: 新增 test_multi_load_case.py + examples/blackcat_004_multicase.py`

完成後 `git pull --rebase --autostash origin main && git push origin main`。

## ⚠️ 範圍警告

這是大任務（預估 4 小時 + debug 時間）。如果中途卡住，**先 commit 已完成的
部分**並回報，不要硬幹。Claude 會在另一邊幫你做數學 review。
