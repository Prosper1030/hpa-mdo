# Codex 任務：驗證 P3#13 解析偏導對 SLSQP 段的加速效果

## 背景

P3#13 已完成（commits `fe41ee9`、`729068f`），`DualSparPropertiesComp` 改為解析
對角稀疏 Jacobian。但實測 DE 段反而 +4.3%（523s vs baseline 502s），這是預期：

> **DE 是 gradient-free**，從不呼叫 `compute_partials()`，所以解析偏導對 DE 完全
> 沒影響。+4.3% 屬於單次跑的雜訊。

真正應該變快的是 **SLSQP 局部精修段**，因為 SLSQP 每次 line search 都會呼叫
`compute_partials`，complex-step 對 12 個設計變數需要 13× forward solve，
analytic 只要 1×。

## 任務

寫一個 read-only 驗證腳本 `scripts/verify_slsqp_timing.py`，跑兩次優化並對比
`OptimizationResult.timing_s` dict 的 SLSQP 段時間。

### 1. 腳本內容

```python
"""驗證解析偏導對 SLSQP 段的加速效果（read-only timing benchmark）。"""
from __future__ import annotations
import json
import time
from pathlib import Path

from hpa_mdo.core.config import load_config
from hpa_mdo.structure.optimizer import SparOptimizer
from hpa_mdo.aero.load_mapper import LoadMapper
# ... 跟 examples/blackcat_004_optimize.py 一樣的 setup

def run_once(label: str) -> dict:
    cfg = load_config(Path("configs/blackcat_004.yaml"))
    # ... build problem, run optimize()
    result = optimizer.optimize()
    return {
        "label": label,
        "mass": result.total_mass_full_kg,
        "timing": dict(result.timing_s),
    }

if __name__ == "__main__":
    out = []
    for i in range(2):
        out.append(run_once(f"run_{i}"))
    print(json.dumps(out, indent=2))
    # 輸出 SLSQP 段平均時間
```

### 2. 比較方式

由於 baseline 是 P3#13 之前的版本，這個任務不需要實際 revert。改為：
**只跑兩次新版本，記錄 timing dict**，讓使用者人眼比對 SLSQP 段是否在
合理範圍內（< 30 s 屬正常；若 > 100 s 代表 partials 沒生效）。

可選擇性加入：暫時把 `DualSparPropertiesComp.declare_partials` 改回
`method="cs"`（單次測試後立刻 git restore），跑一次拿 baseline，再 restore
回 analytic 版本跑一次。**不要 commit 這個暫時改動。**

### 3. 驗收

- 腳本能成功跑完兩次，輸出 JSON
- README 或 `docs/codex_tasks.md` 加註實測 SLSQP 段時間（cs vs analytic）
- 若 analytic SLSQP 沒明顯加速（< 2× speedup），開新 issue 調查
  `declare_partials` 的 sparsity pattern 是否被 OpenMDAO 正確識別
  （可能需要明確設定 `dependent=True`）

## 不要做的事

- ❌ 不要 commit 任何暫時 revert
- ❌ 不要動 `compute_partials()` 內的數學
- ❌ 不要把腳本放進 `tests/`（這是 benchmark 不是單元測試）

## Git

單一 commit：`chore: 新增 SLSQP 計時驗證腳本（P3#13 後續驗證）`
