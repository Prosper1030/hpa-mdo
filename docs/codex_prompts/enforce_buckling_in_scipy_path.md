# Codex 任務：scipy 優化路徑強制執行 buckling_index 約束

## 背景與發現經過

P4#16 屈曲約束已完成，端到端跑 `blackcat_004_optimize.py` 也成功
（`val_weight: 14.3579 kg`）。但事後 review `optimizer.py` 發現一個
**latent silent failure**：

- `BucklingComp` 在 `oas_structural.py` 內已透過 `model.add_constraint(...)` 註冊
- 但 scipy DE/SLSQP 路徑（`_optimize_scipy()`）把 OpenMDAO 當 black-box function 用，
  **OpenMDAO 內部的 add_constraint 不會被 scipy 看到**
- `_eval()` 字典只回傳 `mass / failure / twist / tip_defl`，**沒有 `buckling`**
- 結果：scipy 完全忽略 buckling，只是因為剛好 `tip_deflection` 是主導約束
  把牆推厚到 buckling 被動滿足（實測 `buckling_index = -0.856`）

**現在運氣好沒事，但若 config 改動**（更鬆的撓度上限、更短跨距、更高密度碳纖、
更激進的 load factor），buckling 可能變 active，而 scipy 會給出**違反 buckling 的
「最佳解」且不會發出任何警告**。這是必須修的 silent failure mode。

## 必讀

- `/Volumes/Samsung SSD/hpa-mdo/CLAUDE.md`
- `/Volumes/Samsung SSD/hpa-mdo/src/hpa_mdo/structure/optimizer.py`（重點 L65–100, 230–440）
- `/Volumes/Samsung SSD/hpa-mdo/src/hpa_mdo/utils/visualization.py`（找 `write_optimization_summary`）

## 任務內容

### 1. `optimizer.py` `_eval()` 字典加入 buckling

**位置**：`_optimize_scipy()` 內 L275 附近

```python
res = {
    "mass": _get_scalar("struct.mass.total_mass_full"),
    "failure": _get_scalar("struct.failure.failure"),
    "twist": _get_scalar("struct.twist.twist_max_deg"),
    "tip_defl": _get_scalar("struct.tip_defl.tip_deflection_m"),
    "buckling": _get_scalar("struct.buckling.buckling_index"),  # NEW
}
```

### 2. `penalty_obj` 加入 buckling 懲罰

**位置**：L287 附近的 `penalty_obj()` 內，與 failure/twist 懲罰並列

```python
# Buckling violation — strong penalty (silent failure mode if missed)
if r["buckling"] > 0:
    penalty += 800.0 * (1.0 + r["buckling"]) ** 2
```

懲罰係數 800 介於 failure 的 500 與 twist 的 1000 之間，反映 buckling
是「中等緊急」的破壞模式（local shell buckling 通常給警告但不立即解體）。

### 3. SLSQP `constraints` 加入 buckling

**位置**：L340 附近

```python
constraints = [
    {"type": "ineq", "fun": lambda x: -_eval(x)["failure"]},
    {"type": "ineq", "fun": lambda x: max_twist - _eval(x)["twist"]},
    {"type": "ineq", "fun": lambda x: -_eval(x)["buckling"]},  # NEW
]
if max_defl < float("inf"):
    constraints.append({"type": "ineq", "fun": lambda x: max_defl - _eval(x)["tip_defl"]})
```

### 4. 可行性檢查 `de_feas / sq_feas` 加入 buckling

**位置**：L359-364

```python
tol_f = 0.01
tol_b = 0.01  # NEW: buckling tolerance
tol_tw = max_twist * 1.02
tol_df = max_defl * 1.02 if max_defl < float("inf") else float("inf")

de_feas = (
    r_de["failure"] <= tol_f
    and r_de["buckling"] <= tol_b   # NEW
    and r_de["twist"] <= tol_tw
    and r_de["tip_defl"] <= tol_df
)
sq_feas = (
    r_sq["failure"] <= tol_f
    and r_sq["buckling"] <= tol_b   # NEW
    and r_sq["twist"] <= tol_tw
    and r_sq["tip_defl"] <= tol_df
)
```

### 5. infeasible fallback 也納入 buckling

**位置**：L378 附近

```python
v_de = max(0, r_de["failure"]) + max(0, r_de["twist"] - max_twist) + max(0, r_de["buckling"])
v_sq = max(0, r_sq["failure"]) + max(0, r_sq["twist"] - max_twist) + max(0, r_sq["buckling"])
```

（如果該段已經有 tip_defl 違反加總邏輯，把 buckling 平行加上去。）

### 6. `OptimizationResult` dataclass 加入欄位

**位置**：L65 附近

```python
@dataclass
class OptimizationResult:
    ...
    failure_index: float           # KS ≤ 0 means feasible
    buckling_index: float          # NEW: KS ≤ 0 means feasible
    tip_deflection_m: float
    ...
```

更新 `_feasible` 判斷（L93）：
```python
self.failure_index <= 0
and self.buckling_index <= 0   # NEW
and (self.max_tip_deflection_m is None or ...)
```

更新 `__str__`（L114 附近）：
```python
lines.append(
    f"  Buckling index : {self.buckling_index:.4f} "
    f"({'SAFE' if self.buckling_index <= 0 else 'VIOLATED'})"
)
```

### 7. `_to_result()` 與 `run_analysis()` 連動

**位置**：`optimizer.py` L433 附近的 `_to_result()`

```python
return OptimizationResult(
    ...
    failure_index=raw["failure"],
    buckling_index=raw["buckling_index"],  # or raw["buckling"], 看 run_analysis 怎麼包
    ...
)
```

**注意**：你需要先檢查 `run_analysis()` 函式（grep 找出定義位置，可能在 `oas_structural.py`），
確保它的 raw dict 也包含 `buckling_index`。如果沒有，加進去：

```python
raw = {
    ...
    "failure": ...,
    "buckling_index": float(np.asarray(prob.get_val("struct.buckling.buckling_index")).item()),
    ...
}
```

### 8. `visualization.py` 的 summary 報告加入 buckling 行

**位置**：`utils/visualization.py` 內 `write_optimization_summary` 與 `print_optimization_summary`

在 `Failure index` 行下方加：
```
  Buckling index : -0.8555  (SAFE)
```

格式對齊現有 `Failure index` 行的對齊方式。

### 9. 新增測試 `tests/test_optimizer_buckling.py`

包含至少 3 個測試：

```python
def test_optimization_result_has_buckling_index():
    """OptimizationResult dataclass exposes buckling_index field."""
    # 用 dummy raw dict 建構 OptimizationResult，斷言 buckling_index 屬性存在

def test_eval_dict_includes_buckling():
    """SparOptimizer._optimize_scipy._eval returns dict with 'buckling' key."""
    # 建一個小型 SparOptimizer，呼叫內部 _eval，斷言 'buckling' in result

def test_summary_text_contains_buckling_line():
    """Summary text output contains 'Buckling index' line."""
    # 建 dummy OptimizationResult，呼叫 print/write_optimization_summary，
    # 斷言輸出含 'Buckling index'
```

第二個測試可能需要把 `_eval` 從巢狀函式提取出來，或用整合測試方式跑一次 `optimize()`
然後檢查 result。如果太麻煩，可以用 pytest 的 monkeypatch 或直接驗證 OptimizationResult 行為。

## 驗收

1. `pytest tests/ -q --ignore=tests/test_blackcat_pipeline.py` → 全過（46 + 新測試）
2. `python examples/blackcat_004_optimize.py` → `val_weight: 14.3579 ± 0.01`
   （數值不應改變，因為 buckling 在 Black Cat 004 本來就被動滿足）
3. summary 文字輸出含 `Buckling index : -0.8555 (SAFE)` 或類似行
4. `optimization_summary.txt` 也含此行

## 不要做的事

- ❌ 不要動 `BucklingComp` 內部公式或 KS 聚合邏輯
- ❌ 不要動 `oas_structural.py` 的接線（除非為了讓 `run_analysis` raw dict 加 buckling_index）
- ❌ 不要改 buckling 約束在 OpenMDAO 問題中的註冊方式
- ❌ 不要改物理係數（0.65 knockdown、1.3 enhancement、0.605 classical）

## Git 工作流

兩個 commit（先程式邏輯，後測試）：

1. `fix: scipy 優化路徑強制執行 buckling_index 約束（補強 silent failure）`
2. `test: 新增 test_optimizer_buckling.py 驗證 buckling 整合至 result/eval/summary`

完成後：
```bash
git pull --rebase --autostash origin main
git push origin main
```
