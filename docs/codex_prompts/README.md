# Codex Prompts 索引

本目錄保存發給 Codex 5.4 (Extreme High) 執行的「自包含」任務描述。
所有 prompt 都遵守以下規則：

1. **必要的數學、檔案路徑、驗收標準全部寫死在 prompt 內**
   Codex 不需要先 grep 或 read 才知道要做什麼
2. **明確列出「不要做的事」**，避免 Codex 自由發揮 refactor
3. **附 git commit 訊息範本**

## 待執行任務（依優先序）

### Phase I — Milestone 2 Phase 2（Physics hardening 收尾）

| 順序 | 檔案 | 預估工時 | 前置條件 |
|-----|------|---------|---------|
| F6 | `F6_thickness_smoothness.md` | 1–2 h | 無（可立即開始） |
| F8 | `F8_torsion_shear_buckling.md` | 3–4 h | F6 已 push；若 F6 後 buckling margin 仍大（< -0.3）可延後到 M4 |

### Phase I — Milestone 3（MDO Integration）

| 順序 | 檔案 | 預估工時 | 前置條件 |
|-----|------|---------|---------|
| M3a | `M3a_fsi_production_pipeline.md` | 4–6 h | M2 Phase 2 完成 |
| M3b | `M3b_multi_load_case_example.md` | 3–4 h | 無（可與 M3a 平行） |
| M3c | `M3c_step_deformed_shape.md` | 2–3 h | M3a 已 push |

**並行性**：F6 可立即開始。M3a 與 M3b 可平行。M3c 等 M3a。F8 視 F6 結果決定。

## 已完成

### Milestone 1 系列
- `cleanup_low_priority_warnings.md` ✅ `0ec4576` / `bfdb0c3` / `a307361`
- `enforce_buckling_in_scipy_path.md` ✅ `e6acd35` / `35b0517`
- `verify_slsqp_speedup.md` ✅ `7a6ffc6`
- `benchmark_openmdao_vs_scipy.md` ✅ `7a6ffc6`
- `openmdao_check_partials_test.md` ✅ `4b54dd9`
- `multi_load_case_optimization.md` ✅ `adf5adc` / `57df543` / `3db3a2f`
- `example_output_snapshots.md` ✅ `9c21265`

### Code Review Missions（Antigravity Opus review → M2–M6）
- `M2_trivial_hygiene_pack.md` ✅ G_STANDARD 常數、重複 log 刪除、buckling_index 補齊
- `M3_api_dry_refactor.md` ✅ API 共用 helpers 抽出
- `M4_fsi_problem_reuse.md` ✅ FSI SparOptimizer 重用
- `M5_golden_value_regression.md` ✅ Golden regression test
- `M6_oas_structural_split.md` ✅ God-file 分檔

### Mission B（Optimizer Path Integrity）
- Phase B0: measurement (cache aliasing, check_totals, SLSQP diagnostic, openmdao smoke)
- Phase B1: cache fix `111fced`, auto feasibility `ae75ff8`, counters `d939a62`
- Phase B2: production → `method="auto"` `c9b22aa`, SLSQP rejection warning `d13c600`

### Physics Findings（F-series）
- F1 (VM parallel-axis) ✅
- F2 (Buckling parallel-axis) ✅
- F3 (Monotonic taper) ✅
- F4 (Iz_equiv) ✅
- F5 (Main spar dominance) ✅ Mission M
- F9 (Warping knockdown 0.5) ✅ `9fbee5a`
- F13 (Compressive strength) ✅ `577eff8`

## 給 Claude 的協作備忘

當使用者要派新任務時：
1. 先讀 `docs/GRAND_BLUEPRINT.md` 看總藍圖位置
2. 讀 `docs/codex_tasks.md` 看當前進度
3. 在這裡寫一個 self-contained `<task_name>.md`
4. 把 prompt 內容直接貼回對話讓使用者複製
5. 任務完成後把對應的 .md 移到「已完成」清單
