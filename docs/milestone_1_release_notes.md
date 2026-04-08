# Milestone 1 Release Notes — 線性多工況最佳化（Cruise + Pull-up）

> 日期：2026-04-08
> 狀態：✅ 已交付
> 涵蓋：P4#17 多工況、P1#7 全模型 `check_totals`、C1–C3 清道夫、H1–H2 效能、STEP 匯出

---

## 1. 動機

在 Milestone 1 之前，HPA-MDO 框架雖然已具備完整的單工況結構最佳化能力
（VSPAero → LoadMapper → OpenMDAO FEM → DE+SLSQP），但仍存在三個工程上不可接受的限制：

1. **單一工況**：只能對單一巡航狀態最佳化，無法同時保證 cruise 與 pull-up（陣風 / 急轉）
   兩個關鍵載荷下的結構安全。
2. **梯度可信度未驗證**：P3#13 雖已寫入 `DualSparPropertiesComp` 解析偏導，但從未對
   **整個求解器** 做過 `check_totals`；只要任何一個元件有偏導 bug，driver 收斂的解
   就是錯的。
3. **存在多個 silent failure 路徑**：FEM 求解失敗會回傳零位移、ANSYS 匯出讀的不是
   最佳化後的幾何、壁厚 clipping 在兩個地方有不一致的上限——這些都是會把錯誤結果
   悄悄送到下游的隱形地雷。

Milestone 1 的目標就是把這三件事一次性處理完，建立一個**梯度可信、多工況可擴張、
不會 silent fail** 的求解平台。

---

## 2. 系統拓撲（Architecture Topology）

### 2.1 整體資料流

```
configs/blackcat_004.yaml
        │
        ▼
   HPAConfig (Pydantic)
        │
        ├── flight.cases: List[LoadCaseConfig]   ← 新增
        │     ├── cruise   (aero_scale=1.0, nz=1.0)
        │     └── pullup   (aero_scale=1.5, nz=1.5)
        │
        ▼
   structural_load_cases() ──→ legacy fallback: 把舊的單工況包成 name="default"
        │
        ▼
┌──────────────────────────────────────────────────────────────────┐
│  HPAStructuralGroup (OpenMDAO Group)                             │
│                                                                  │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────┐    │
│  │ seg_mapper   │───▶│ spar_props   │───▶│ mass             │    │
│  │ (12 DV)      │    │ (EI / GJ /   │    │ (objective)      │    │
│  │              │    │  A / I / J)  │    │                  │    │
│  └──────────────┘    └───────┬──────┘    └──────────────────┘    │
│                              │                                   │
│              ┌───────────────┼───────────────┐                   │
│              │               │               │                   │
│              ▼               ▼               ▼                   │
│   ┌──────────────────┐  ┌──────────────────┐                     │
│   │ case_cruise      │  │ case_pullup      │   ← 多工況拓撲      │
│   │  ext_loads       │  │  ext_loads       │                     │
│   │  fem             │  │  fem             │                     │
│   │  stress          │  │  stress          │                     │
│   │  failure ≤ 0     │  │  failure ≤ 0     │                     │
│   │  buckling ≤ 0    │  │  buckling ≤ 0    │                     │
│   │  twist ≤ θ_max   │  │  twist ≤ θ_max   │                     │
│   │  tip_defl ≤ δ    │  │  tip_defl ≤ δ    │                     │
│   └──────────────────┘  └──────────────────┘                     │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
        │
        ▼
   ScipyOptimizeDriver (gradient-based, 走 compute_partials)
   或
   _ScipyBlackBoxEvaluator + DE+SLSQP (gradient-free, 走 compute)
```

### 2.2 共用骨幹 vs 各工況分支

Milestone 1 拓撲設計的核心是**「結構屬性共用、工況分支獨立」**：

| 子系統 | 共用 / 分支 | 理由 |
|--------|-------------|------|
| `seg_mapper`     | 共用 | 設計變數只有一組（main_t/r、rear_t/r） |
| `spar_props`     | 共用 | EI / GJ / 質量分佈是幾何屬性，與載荷無關 |
| `mass`           | 共用 | 目標函數是單一質量，不分工況 |
| `ext_loads`      | **分支** | 每個 case 有自己的 `aero_scale` 與 `nz`（重力倍數） |
| `fem`            | **分支** | 不同載荷 → 不同位移場 |
| `stress / failure` | **分支** | 由各 case 的位移計算 |
| `buckling`       | **分支** | bending 載荷不同 → 屈曲安全係數不同 |
| `twist / tip_defl` | **分支** | 變形量是工況相依的 |

這個拓撲在 `HPAStructuralGroup.setup()` 內由 `case_entries` 數量決定：
- **單工況**：保留 legacy 平鋪元件名稱（`struct.failure`, `struct.buckling`, …），
  維持與舊 example 與舊 API 完全相容。
- **多工況**：每個 case 包成 `StructuralLoadCaseGroup` 子群組，命名為 `case_<name>`，
  約束以 `struct.case_cruise.failure / struct.case_pullup.failure …` 註冊到 driver。

> 設計哲學：**共用一組設計變數、共用一份結構屬性、用最少的計算重複，
> 在多工況之間取**「最壞工況包絡」**作為可行域。**

### 2.3 工況輸入協定

`build_structural_problem(cfg, aircraft, aero_loads, materials_db)` 的 `aero_loads`
參數現在接受兩種型式：

1. **Legacy**：mapped-load dict（`{"lift_per_span": ..., ...}`），配合 `cfg.flight.cases = []`
   會自動包成單工況 `name="default"`，使用 `cfg.safety.aerodynamic_load_factor`
   與舊有 `cfg.wing.max_*` 約束。
2. **多工況**：`{case_name: mapped_loads}`，必須與 `cfg.flight.cases` 的名稱集合完全
   一致；缺漏或多餘 case 名稱會直接丟錯（fail-fast）。

`_normalise_load_case_inputs()` 是這層協定的單一入口，所有後續程式都吃它的標準輸出
`{name: (LoadCaseConfig, mapped_loads)}`。

### 2.4 安全係數的「不重複乘」原則

Milestone 1 之前的 M1 bug：`aerodynamic_load_factor` 被同時套在 `LoadMapper` 與
`ExternalLoadsComp`，導致載荷被乘了兩次。Milestone 1 把這條規則正規化：

- `LoadCaseConfig.aero_scale`：由 `ExternalLoadsComp` 在組裝外載時套用，**唯一**位置
- `LoadCaseConfig.nz`（gravity scale）：由 `ExternalLoadsComp` 在組裝重力載時套用
- `cfg.safety.material_safety_factor`：由 `failure` 元件在計算 `σ/σ_allow` 時套用，
  **與 aero scale 完全分離**

這條原則由 CLAUDE.md 鐵律 #4 強制執行，並由 `test_multi_load_case.py` + 新增的
`test_spatial_beam_fem.py` 守住回歸。

---

## 3. 梯度安全（Gradient Safety）

### 3.1 全模型 `check_totals`

P1#7 升級為「**整條 driver 路徑端到端**驗證」，而不只是元件級 `check_partials`：

- `tests/test_partials.py::test_check_totals_full_structural_model`
  - 對 `mass / failure / buckling / twist / tip_defl` 全部 outputs vs
    全部 design vars 做 `prob.check_totals(method="cs")`
  - tol：`atol=1e-5, rtol=1e-5`
- `tests/test_partials.py::test_check_totals_multi_case_structural_model`
  - cruise + pullup 兩個 case 同時跑 check_totals
  - 確保「分支拓撲」沒有破壞鏈式法則

通過這兩個測試 = 對 driver 來說，整個模型看起來就是一個解析可微的函數。
這是 Milestone 1 最關鍵的「品質印章」：之後任何元件 refactor 只要 check_totals
仍然通過，就保證最佳化器看到的梯度是對的。

### 3.2 為 check_totals 鋪路的修補

通過全模型 check_totals 不是免費午餐，過程中發現並修了這些梯度污染源：

| Commit | 修補內容 |
|--------|---------|
| `b336135` | 雙翼梁 warping 扭轉折減係數從硬編碼搬進 config（避免 cs 觸發 type promotion） |
| `ad4f37b` | 移除 FEM 內 `float()` 強制 cast，改成 dtype-aware；矩陣乘法改用 numpy 原生運算避免 complex 訊息丟失 |
| `7ebcdf5` | 清除 NumPy scalar deprecation 與 FEM matmul `RuntimeWarning`（DE 邊界 divide-by-zero） |

這些修補對「正常 forward run」完全透明，但它們是 complex-step 微分能正確傳播的
必要條件。

### 3.3 解析偏導的真正受益者

在 P3#13 完成解析偏導後，benchmark（commit `7a6ffc6`）證明 scipy DE+SLSQP 路徑
**不會**呼叫 `compute_partials`，因為它把 OpenMDAO 當黑盒 evaluator 用。
真正吃到解析偏導好處的是：

1. `prob.check_totals()` —— 從幾秒級降到毫秒級
2. `ScipyOptimizeDriver` 的 SLSQP / COBYLA gradient-based 路徑
3. 未來若接 IPOPT / SNOPT

scipy 黑盒路徑現在被清楚定位為「robust fallback / global search」，
不再被誤認為是 partials 的成效驗證對象。

---

## 4. 清道夫行動 — C 級致命技術債

| 級別 | 問題 | 修補位置 | Commit |
|------|------|---------|--------|
| C1 | FEM 求解失敗時 silent fallback 回零位移 | `oas_structural.py: _run_fem_safe` 改為 raise `AnalysisError` | `ca0853e` |
| M1 | `aerodynamic_load_factor` 被 LoadMapper 與 ExternalLoadsComp 兩處重複乘 | `ExternalLoadsComp` 內由 `LoadCaseConfig.aero_scale` 統一套用 | `ca0853e` |
| C2 | 壁厚 clipping 在 `optimizer.py` 與 `oas_structural.py` 兩處不一致（0.95R vs 0.8R） | 統一收斂到 `cfg.solver.max_thickness_to_radius_ratio = 0.8`，並改為 OpenMDAO `ExecComp` 約束 `t ≤ η·R` | `ddc1a69` |
| C3 | ANSYS 匯出（BDF / MAC / CSV）讀的是初始 radius 而非最佳化後 `main_r_seg` | `ansys_export.py` 改從 `seg_mapper` 取值 | `ddc1a69` |

C1 是這四個裡最危險的：它會讓最佳化器收斂到「FEM 從來沒解出來」的虛假最優解。
修完之後，任何 FEM 失敗（負特徵值、條件數爆炸、自由 DOF 殘差超標）都會丟例外，
被外層 `_eval` 捕捉並轉成 `val_weight: 99999` 標記為 infeasible。

---

## 5. 效能瓶頸（H 級）

| 級別 | 問題 | 修補 | Commit |
|------|------|------|--------|
| H1 | DE 黑盒 evaluator 的 cache 是無上限 dict，長 DE 跑會把記憶體吃爆 | `_ScipyBlackBoxEvaluator` 改用有上限的 LRU `OrderedDict`，size 由 `cfg.solver.scipy_eval_cache_size = 2048` 控制 | `fbaa928` |
| H2 | DE workers 從 `-1`（自動 = CPU 數）改為由 `cfg.solver.de_max_workers = 4` 封頂 | 避免 8C/16T 機器上 DE × OpenMDAO setup 爆記憶體 | `fbaa928` |

伴隨 H1/H2 引入的 `cfg.solver` 新欄位（全部由 YAML 控制，符合鐵律 #1）：

```yaml
solver:
  max_wall_thickness_m: 0.015
  min_radius_m: 0.010
  max_radius_m: 0.060
  max_thickness_to_radius_ratio: 0.8     # C2 統一上限
  fem_max_matrix_entry: 1.0e12           # FEM 數值健康守門員
  fem_max_disp_entry:   1.0e2
  fem_bc_penalty:       1.0e15
  scipy_eval_cache_size: 2048            # H1
  de_max_workers:       4                # H2
```

---

## 6. 工具化交付

- **STEP 檔匯出**（`3157d78`）：`examples/blackcat_004_optimize.py` 完跑後輸出 STEP，
  供 CAD inspection / 與機械團隊對接用。
- **範例輸出快照自動同步**（`9c21265`）：optimization summary、beam_analysis.png、
  spar_geometry.png 自動寫進 `docs/examples/`，作為文件級 baseline。
- **API 測試 mock 化**（`f38b324`）：把 `SparOptimizer` 在 API tests 內 mock 掉，
  Mac mini 上 `pytest -m "not slow"` 測試時間從 5+ 分鐘降到 ~30 秒。

---

## 7. 已知限制與下一階段

**Milestone 1 沒做的事**（保留給 Milestone 2 / 3）：

1. **多工況 + gradient-based**：目前多工況走的仍是 DE+SLSQP 黑盒路徑。
   要讓 driver 路徑（吃 partials）跑多工況，需要再驗證一次 multi-case `check_totals`
   在 `ScipyOptimizeDriver` 內的端到端行為。
2. **Surrogate model warm start**（P4#18）：尚未開工。
3. **動載荷 / FSI 雙向耦合在多工況下的支援**：目前 FSI 仍只跑單工況。
4. **STEP 匯出的多工況變體**：目前只匯出一個最佳幾何，沒有「per-case 變形後幾何」。

**Milestone 2 候選範圍**（順序待裁示）：
- P4#18 surrogate warm start
- multi-case 在 OpenMDAO driver 路徑的端到端驗證
- 動載荷 / 顫振分析整合

---

## 8. Quality Gate（Milestone 1 出貨檢核）

- ✅ `pytest -m "not slow"` 全綠
- ✅ `tests/test_partials.py` 兩個 check_totals 都通過
- ✅ `tests/test_multi_load_case.py` cruise + pullup 完整跑通
- ✅ `tests/test_ansys_export.py` 驗證匯出與 OpenMDAO 內部模型一致
- ✅ `tests/test_spatial_beam_fem.py` FEM 失敗 raise `AnalysisError` 行為測試
- ✅ `examples/blackcat_004_optimize.py` 端到端可跑，產出 `val_weight` 行
- ✅ 鐵律 1–8 全部遵守（無硬編碼物理常數、安全係數分離、OpenMDAO-only 結構求解、
  繁中高階文件、英文 log/code/.txt）

— 林禹安 ✕ Claude ✕ Codex 共同交付
