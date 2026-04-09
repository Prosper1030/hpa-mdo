# M5 — Golden Value Regression Test（Black Cat 004 端到端基準快照）

## 背景

目前 52+ 個測試覆蓋了單元行為與 check_totals，但**沒有任何一個測試會在 physics
不知不覺改變時跳出來抓**。例如：

- 某天有人不小心把 KS aggregation ρ 從 100 改成 50，stress KS 變得保守，
  baseline 質量從 14.36 → 16.5 kg ——所有單元測試都還會過，因為個別元件沒壞
- 某天升級 numpy / scipy，DE 種子行為微變，最佳解漂移
- 某天有人改 buckling knockdown 0.65 → 0.55 ——只有 baseline mass 會反映出差異

Antigravity Opus review 把這個歸類為「missing test coverage gap」，我同意。

> 前提：本任務必須等 Codex 目前的 **main spar dominance** 任務完成並 push 之後再開工。
> 因為 main spar dominance 會改變最佳解，等它穩定後再寫 baseline 才有意義。

## 目標

寫一個 `@pytest.mark.slow` 標記的 end-to-end regression test，
跑一次 `blackcat_004.yaml` 的完整最佳化，與寫死在測試檔內的 baseline 比對。

差距超過容忍度時 fail，並在錯誤訊息裡明示「physics 改變了，如果是預期變動請更新
baseline 並在 commit message 寫明原因」。

## 設計約束

**容忍度設計**（這是這個 mission 最敏感的決定）：

- DE 是 stochastic，即使固定 `seed=42`，不同 OS / numpy 版本可能 cause ~1% 漂移
- 主梁 / 副梁段壁厚對 DE 種子很敏感，個別段差 30% 是合理的隨機性
- 但**總質量**對隨機性不敏感（容忍度應該收緊到 ~2%）
- **約束滿足度**完全不能漂（failure ≤ 0、buckling ≤ 0、tip_defl ≤ max）

| 量 | 容忍度 | 理由 |
|----|--------|------|
| `total_mass_full_kg` | ±2% (絕對 ±0.30 kg) | 對 DE 隨機性不敏感 |
| `failure_index` | `<= 0.01` | 約束滿足，不容漂 |
| `buckling_index` | `<= 0.01` | 約束滿足，不容漂 |
| `tip_deflection_m / max_tip_deflection_m` | `<= 1.02` | 容忍 SLSQP 微小越界 |
| `twist_max_deg` | `<= max_tip_twist_deg + 0.05°` | 約束滿足 |
| 個別段壁厚 | **不檢查** | DE 種子敏感，無意義 |
| 個別段 OD | **不檢查** | 同上 |

**禁止**：
- 不要 assert 個別段壁厚 / OD（會因 DE 種子變化天天 false positive）
- 不要在這個測試裡跑 plot / STEP 匯出（測試只驗證數值）
- 不要動 `examples/blackcat_004_optimize.py`
- 不要在這個 PR 修任何 production 程式碼
- 不要把測試標成「快」——這是 slow test，要 30+ 分鐘

## 要做的事

### Step 1：先跑一次當前 baseline 拿真值

```bash
.venv/bin/python examples/blackcat_004_optimize.py 2>&1 | tee /tmp/m5_baseline.log
cat output/blackcat_004/optimization_summary.txt
```

把以下 5 個數值記下來：

- `total_mass_full_kg`
- `failure_index`
- `buckling_index`
- `tip_deflection_m`
- `twist_max_deg`

這 5 個數會寫進測試檔當作 baseline 常數。

### Step 2：寫測試 `tests/test_golden_blackcat_004.py`

```python
"""End-to-end regression: Black Cat 004 baseline mass and constraints.

This test runs the full optimization pipeline (config → VSPAero parse →
LoadMapper → SparOptimizer.optimize) on the canonical blackcat_004.yaml
and asserts the result matches a frozen baseline within engineering
tolerance.

It exists to catch silent physics regressions that unit tests cannot:
KS aggregation parameters changing, dependency upgrades shifting DE
behavior, knockdown factor edits, etc.

When this test fails:
1. If the change is intentional and the new mass is engineering-correct,
   update the BASELINE_* constants below and add a one-line note in the
   commit message explaining what changed and why.
2. If the change is unintentional, find and revert the offending edit.

Marked @pytest.mark.slow — runs the full DE+SLSQP loop (~9 minutes on
Mac mini M2). Skipped by default; run with `pytest -m slow`.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from hpa_mdo.aero.load_mapper import LoadMapper
from hpa_mdo.aero.vsp_aero import VSPAeroParser
from hpa_mdo.core.aircraft import Aircraft
from hpa_mdo.core.config import load_config
from hpa_mdo.core.materials import MaterialDB
from hpa_mdo.structure.optimizer import SparOptimizer


REPO_ROOT = Path(__file__).resolve().parents[1]


# ── Frozen baseline (Milestone 1 + main spar dominance) ──
# Generated: <DATE>
# Last updated by: <COMMIT SHA / mission name>
# Run on: macOS / Python 3.10 / numpy <VER> / scipy <VER>
BASELINE_TOTAL_MASS_KG = 14.36   # ← Codex: 用 Step 1 跑出來的真值取代
BASELINE_TOTAL_MASS_TOL_KG = 0.30  # ±2%

# Constraints that must hold (these are physics, not stochastic)
MAX_FAILURE_INDEX = 0.01
MAX_BUCKLING_INDEX = 0.01
MAX_TIP_DEFLECTION_RATIO = 1.02  # tolerate 2% over max (SLSQP boundary slop)
MAX_TWIST_MARGIN_DEG = 0.05      # tolerate 0.05° over max twist


@pytest.mark.slow
def test_blackcat_004_baseline_mass_and_constraints():
    cfg = load_config(REPO_ROOT / "configs" / "blackcat_004.yaml")
    aircraft = Aircraft.from_config(cfg)
    mat_db = MaterialDB()

    parser = VSPAeroParser(cfg.io.vsp_lod)
    aero_cases = parser.parse()
    assert len(aero_cases) > 0, "VSPAero parser returned no cases"
    aero = aero_cases[0]

    mapper = LoadMapper()
    mapped = mapper.map_loads(
        aero,
        aircraft.wing.y,
        actual_velocity=cfg.flight.velocity,
        actual_density=cfg.flight.air_density,
    )

    optimizer = SparOptimizer(cfg, aircraft, mapped, mat_db)
    result = optimizer.optimize(method="scipy")

    # ── Mass: ±2% of frozen baseline ──
    mass_delta = abs(result.total_mass_full_kg - BASELINE_TOTAL_MASS_KG)
    assert mass_delta <= BASELINE_TOTAL_MASS_TOL_KG, (
        f"\nBlack Cat 004 baseline mass regression detected:\n"
        f"  Current : {result.total_mass_full_kg:.4f} kg\n"
        f"  Baseline: {BASELINE_TOTAL_MASS_KG:.4f} kg\n"
        f"  Delta   : {mass_delta:.4f} kg (tolerance ±{BASELINE_TOTAL_MASS_TOL_KG:.2f} kg)\n"
        f"\n"
        f"If this change is intentional (e.g. you changed a knockdown\n"
        f"factor, KS rho, or load case), update BASELINE_TOTAL_MASS_KG\n"
        f"in this file and document the rationale in your commit message.\n"
        f"If unintentional, find the recent commit that broke physics."
    )

    # ── Constraints: hard physical limits ──
    assert result.failure_index <= MAX_FAILURE_INDEX, (
        f"failure_index = {result.failure_index:.4f} > {MAX_FAILURE_INDEX} "
        f"(stress constraint violated)"
    )
    assert result.buckling_index <= MAX_BUCKLING_INDEX, (
        f"buckling_index = {result.buckling_index:.4f} > {MAX_BUCKLING_INDEX} "
        f"(shell buckling constraint violated)"
    )

    if cfg.wing.max_tip_deflection_m is not None:
        max_defl = cfg.wing.max_tip_deflection_m
        ratio = result.tip_deflection_m / max_defl
        assert ratio <= MAX_TIP_DEFLECTION_RATIO, (
            f"tip_deflection = {result.tip_deflection_m*1000:.0f} mm "
            f"({ratio*100:.1f}% of {max_defl*1000:.0f} mm max), "
            f"exceeds {MAX_TIP_DEFLECTION_RATIO*100:.0f}% tolerance"
        )

    twist_limit = cfg.wing.max_tip_twist_deg + MAX_TWIST_MARGIN_DEG
    assert result.twist_max_deg <= twist_limit, (
        f"twist_max = {result.twist_max_deg:.3f} deg > {twist_limit:.3f} deg "
        f"(twist constraint violated, including {MAX_TWIST_MARGIN_DEG} deg slop)"
    )

    # ── Sanity: DV vector exists and is sane sized ──
    assert result.main_t_seg_mm is not None
    assert result.main_r_seg_mm is not None
    n_seg = len(cfg.spar_segment_lengths(cfg.main_spar))
    assert len(result.main_t_seg_mm) == n_seg
    assert len(result.main_r_seg_mm) == n_seg

    # All thicknesses positive and within physical bounds
    assert np.all(result.main_t_seg_mm > 0.5)  # > 0.5 mm
    assert np.all(result.main_t_seg_mm < 15.0)  # < 15 mm
    assert np.all(result.main_r_seg_mm > 5.0)   # > 5 mm radius (10 mm OD)
    assert np.all(result.main_r_seg_mm < 65.0)  # < 65 mm radius (130 mm OD)
```

### Step 3：跑測試確認當前 main 通過

```bash
.venv/bin/python -m pytest -v -m slow tests/test_golden_blackcat_004.py
```

如果 fail，**先檢查是不是 baseline 數字寫錯了**（拼字、單位），不要直接調寬容忍度。

如果調過 5 次都 fail，**停下來**回報，可能是 main spar dominance 之後的 baseline
不穩定，需要先排查最佳化收斂性，不是 test 問題。

### Step 4：把 BASELINE 數字 + 註解寫死

把 Step 1 拿到的真值填進 `BASELINE_TOTAL_MASS_KG` 等常數。
把標頭註解的 `<DATE>` / `<COMMIT SHA>` / `<VER>` 填上：

```python
# Generated: 2026-04-08
# Last updated by: <commit sha>（M5 golden value test 初始化）
# Run on: macOS / Python 3.10 / numpy 1.26 / scipy 1.13
```

可以用：
```bash
.venv/bin/python -c "import numpy, scipy; print(numpy.__version__, scipy.__version__)"
```

## 驗收標準

1. `pytest -v -m slow tests/test_golden_blackcat_004.py` 通過（不要跳過）
2. `pytest -m "not slow"` 全綠（確認沒打壞既有測試）
3. baseline 數字是 Step 1 真實量到的，**不是猜的**
4. 標頭註解完整：日期、commit sha、numpy/scipy 版本
5. 測試**不**檢查個別段壁厚 / OD（這些對 DE 種子敏感）
6. fail 時的錯誤訊息包含「如果是預期變動請更新 baseline 並在 commit message 說明原因」
7. test 函式單一，沒有副作用（不寫 plot、不寫 STEP、不動 output 目錄）
8. 程式碼註解 / docstring 全英文（鐵律 #8）

## 不要做的事

- 不要把這個 test 從 slow 解放出來（會把 CI 拖死）
- 不要新增其他 baseline 數字（DV 細節、個別段壁厚），只測 mass + 約束
- 不要動 `pytest.ini` / CI 設定
- 不要把 baseline 寫成 fixture 從 JSON 讀（直接寫死 module-level 常數最清楚）
- 不要在這個 mission 加 multi-load-case baseline（那是另一個 mission）
- 不要在這個 mission 加 H2 / HFS multi-config baseline，只做 blackcat_004

## Commit 訊息範本

```
test: 新增 Black Cat 004 端到端 baseline regression test（M5）

- tests/test_golden_blackcat_004.py：cold start 跑完整 DE+SLSQP，
  斷言 total_mass_full_kg 在 14.36 ± 0.30 kg、failure/buckling 約束滿足
- @pytest.mark.slow，預設跳過，需 pytest -m slow 顯式啟用
- 容忍度設計：mass ±2%，個別段壁厚不檢查（DE stochastic）
- 失敗訊息包含「若是預期變動請更新 baseline 並說明」指引
- baseline 來源：commit <SHA> 後的 main spar dominance + Milestone 1 結果
- 環境記錄：macOS / Python 3.10 / numpy <VER> / scipy <VER>
```

## 完成後

```
.venv/bin/python -m pytest -v -m slow tests/test_golden_blackcat_004.py
.venv/bin/python -m pytest -x -m "not slow"
git add -A tests/test_golden_blackcat_004.py docs/codex_prompts/M5_golden_value_regression.md
git commit -m "..."
git pull --rebase --autostash origin main
git push origin main
```
