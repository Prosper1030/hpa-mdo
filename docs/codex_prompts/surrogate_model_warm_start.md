# Codex 任務：P4#18 Surrogate Model Warm Start

## 背景

目前每次優化都從 random DE population 開始，要花 ~500s。
若能用代理模型（surrogate）給出一個接近最佳的初始點，DE 可以縮減 generation
數，預期 SLSQP 段也會收斂更快。

## 必讀

- `/Volumes/Samsung SSD/hpa-mdo/CLAUDE.md`
- `/Volumes/Samsung SSD/hpa-mdo/src/hpa_mdo/structure/optimizer.py`
- `/Volumes/Samsung SSD/hpa-mdo/configs/blackcat_004.yaml`

## 設計

### 1. 新增 `src/hpa_mdo/utils/surrogate.py`

兩個 backend，使用者可從 config 切換：
- `gp`：sklearn `GaussianProcessRegressor`（default，數據少）
- `xgb`：`xgboost.XGBRegressor`（數據 > 200 點時更快）

```python
from __future__ import annotations
from pathlib import Path
import json
import numpy as np

class MassSurrogate:
    """Mass surrogate trained on (design_vars, mass) pairs."""

    def __init__(self, backend: str = "gp"):
        self.backend = backend
        self.model = None
        self.X_min = None
        self.X_max = None

    def fit(self, X: np.ndarray, y: np.ndarray) -> None:
        ...

    def predict(self, X: np.ndarray) -> np.ndarray:
        ...

    def suggest_initial_point(
        self,
        bounds: list[tuple[float, float]],
        n_samples: int = 1000,
    ) -> np.ndarray:
        """蒙地卡羅取樣，回傳預測 mass 最小的點作為 DE 初始 guess。"""
        ...

    def save(self, path: Path) -> None:
        ...

    @classmethod
    def load(cls, path: Path) -> "MassSurrogate":
        ...
```

### 2. 訓練資料收集器

新增 `scripts/collect_surrogate_data.py`：
- 跑 `n_samples=50` 次 LHS 取樣的設計變數
- 每次只跑 OpenMDAO `run_model()`（不優化），記錄 (x, mass, feasible_flags)
- 結果存 `data/surrogate_blackcat_004.npz`

### 3. `optimizer.py` 整合

`SparOptimizer.__init__` 加入 optional `surrogate_path: Path | None`。
若提供：
1. 載入 surrogate
2. 在 DE init 之前呼叫 `suggest_initial_point()` 得到 `x0`
3. 把 `x0` 注入 DE 的 `init` 參數（scipy DE 支援 `init=ndarray` 作為初始族群之一）

```python
init_pop = np.random.rand(15, len(bounds))  # 預設 LHS
if self.surrogate is not None:
    x0 = self.surrogate.suggest_initial_point(bounds)
    init_pop[0] = (x0 - lo) / (hi - lo)  # normalize 到 [0, 1]
de_result = differential_evolution(..., init=init_pop, ...)
```

### 4. Config 加入 surrogate 設定

```yaml
optimizer:
  surrogate:
    enabled: false        # 預設關閉
    backend: gp
    path: data/surrogate_blackcat_004.npz
```

## 測試

```python
def test_surrogate_fit_predict_smoke():
    """合成 quadratic 資料，train→predict 誤差 < 5%."""

def test_surrogate_save_load_roundtrip():
    """save 後 load 預測值 bit-exact."""

def test_optimizer_with_surrogate_warm_start():
    """有 surrogate 時 DE 段時間 < 無 surrogate 的 70%."""
    # 用小的 popsize / maxiter 加速測試
```

## 驗收

1. `pytest tests/test_surrogate.py -q` → 全過
2. `python scripts/collect_surrogate_data.py --n 30` 能跑完
3. `python examples/blackcat_004_optimize.py --surrogate data/surrogate_blackcat_004.npz`
   → `val_weight` 仍在 14.3579 ± 0.05，且 timing 中 DE 段比 baseline 短
4. **未啟用 surrogate 時行為與目前完全相同**（向後相容）

## 不要做的事

- ❌ 不要把 surrogate 變成必要相依（sklearn / xgboost 都是 optional import）
- ❌ 不要動 DE 的核心參數（popsize、maxiter、mutation、recombination）
- ❌ 不要把 surrogate prediction 直接當目標函數（只用來給 warm start）

## Git

三個 commit：
1. `feat: 新增 utils/surrogate.py（MassSurrogate GP/XGBoost backend）`
2. `feat: optimizer 支援 surrogate warm start + scripts/collect_surrogate_data.py`
3. `test: 新增 test_surrogate.py + 文件更新`

## ⚠️ 範圍警告

這是大任務（6h+）。新依賴 sklearn/xgboost 必須加進 `pyproject.toml` 的
optional dependency group `surrogate`，預設不安裝。
