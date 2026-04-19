# Track V — AVL Spanwise Ownership Realignment Report

> 文件性質：Track V 最小必要驗證報告
> 任務日期：2026-04-19
> 任務目標：把 `candidate_avl_spanwise` 收回成「舊 AVL-first 流程 + spanwise lift ownership」，不要再順手改掉 gate / recovery / load-state ownership。

## 1. 結論

- 這次修正有把最明顯的 drift 收回來：
  - `candidate_avl_spanwise` 不再由 campaign 端硬性加上 `--no-ground-clearance-recovery`
  - direct inverse design 端也不再禁止 `candidate_avl_spanwise` 開啟 recovery
  - recovery ladder 現在會沿用同一份 outer-loop 已選好的 AVL spanwise artifact，而不是因為少傳 artifact 直接失效
  - contract / artifact 現在明確寫出：`selected_cruise_aoa_deg` 與 candidate load-state owner 仍然是 outer-loop AVL trim / gates，不是 `candidate_avl_spanwise` 自己新定義
- full-gate smoke 沒有再出現「新 mode 偷偷繞過 gate」的情況：
  - `legacy_refresh` 與 repaired `candidate_avl_spanwise` 在同一組 seed 下都被 `trim_aoa_exceeds_limit` 擋住，結構 follow-on 都沒有被放行
- 在同一組 fixed structural seed 下，repaired `candidate_avl_spanwise` 沒有把 mass 推到之前那種明顯不合理的級別：
  - `legacy_refresh`：`21.740001 kg`
  - repaired `candidate_avl_spanwise`：`21.740001 kg`
- 但兩條路徑的 clearance / feasibility 仍然有明顯差異：
  - `legacy_refresh`：`jig_ground_clearance_min_m = -0.026532`，`overall_feasible = false`
  - repaired `candidate_avl_spanwise`：`jig_ground_clearance_min_m = +0.033523`，`overall_feasible = true`
- 所以 Track V 可以算是完成「ownership / gate / recovery realignment」，但還不能把 `legacy_refresh` 與 repaired `candidate_avl_spanwise` 視為完全等價；這正是 Track W 要回答的事。

## 2. AVL Manual 對照

已對照 `docs/Manual/avl_doc.txt`：

- `FT` = total forces
- `FN` = surface forces
- `FS` = strip forces
- manual 也明講：每次 calculation 後，individual `surfaces`, `strips`, `elements` 可用 `FN / FS / FE` 顯示
- `FS` 輸出的力與矩方向是 stability axes `x,y,z`

這次實作沿用的就是 `FS strip forces`，而不是誤把 `FT` / `FN` 當展向 strip 載荷。  
目前 `src/hpa_mdo/aero/avl_spanwise.py` 讀的是 `.fs` table 裡的 strip rows，並只取目標 surface 的正半翼 strips；這和 manual 的 surface / strip 語義是一致的。

## 3. 這次改了什麼

- `scripts/dihedral_sweep_campaign.py`
  - 不再替 `candidate_avl_spanwise` 自動補 `--no-ground-clearance-recovery`
  - 建 candidate AVL artifact 時，明確寫入：
    - `selected_cruise_aoa_source = outer_loop_avl_trim`
    - `selected_load_state_owner = outer_loop_avl_trim_and_gates`
- `scripts/direct_dual_beam_inverse_design.py`
  - 移除 `candidate_avl_spanwise` 一律禁止 recovery 的 guard
  - recovery ladder 重新呼叫 `_resolve_outer_loop_candidate_aero(...)` 時，會把同一份 `candidate_avl_spanwise_loads_json` 傳下去
  - candidate AVL contract 現在明確說明：
    - outer-loop AVL trim / gates 才是 selected AoA / load-state owner
    - `candidate_avl_spanwise` 只負責把這個已選好的 candidate state 的 spanwise lift distribution 餵進結構
  - 若當前 structural run 的 knobs 與 artifact 原始 requested knobs 不同，contract notes 會標註這是 recovery 對同一份 outer-loop artifact 的沿用，而不是新的 AoA/load-state baseline
- `src/hpa_mdo/aero/avl_spanwise.py`
  - artifact schema 新增 selected AoA source / load-state owner metadata
- `tests/test_avl_spanwise.py`
  - 補 artifact roundtrip metadata 檢查
- `tests/test_inverse_design.py`
  - 補 candidate AVL contract ownership 檢查
  - 補 recovery reuse note 檢查
  - 改成驗證 campaign 不會再硬塞 `--no-ground-clearance-recovery`

## 4. 驗證

### 4.1 最小必要測試

執行：

```bash
./.venv/bin/pytest tests/test_avl_spanwise.py -q
./.venv/bin/pytest tests/test_inverse_design.py -q -k 'candidate_avl_spanwise or ground_clearance_recovery or aero_source_mode'
```

結果：

- `tests/test_avl_spanwise.py`: `3 passed`
- `tests/test_inverse_design.py -k ...`: `6 passed`

### 4.2 真實 full-gate smoke

固定：

- `target_shape_z_scale = 4.0`
- `dihedral_exponent = 2.2`
- `rib_zonewise_mode = off`
- fixed structural seed：
  - `main_plateau_grid = 1.0`
  - `main_taper_fill_grid = 0.999999500019976`
  - `rear_radius_grid = 0.9999997444012075`
  - `rear_outboard_grid = 1.0`
  - `wall_thickness_grid = 0.04630959736295326`

比較：

- `/tmp/track_v_smoke_legacy`
- `/tmp/track_v_smoke_candidate_fullgate`

結果：

- `legacy_refresh`
  - `aero_status = stable`
  - `aero_performance_reason = trim_aoa_exceeds_limit`
  - `structure_status = skipped`
- repaired `candidate_avl_spanwise`
  - `aero_status = stable`
  - `aero_performance_reason = trim_aoa_exceeds_limit`
  - `structure_status = skipped`

判讀：

- repaired `candidate_avl_spanwise` 沒有再靠新 mode 偷跑結構路徑
- 這包成功不是建立在 `--skip-aero-gates`

### 4.3 同 seed 結構 compare

說明：

- 為了建立 candidate AVL artifact，我另外跑了一個 debug-only 單點：
  - `/tmp/track_v_smoke_candidate_debug`
  - 這一步用了 `--skip-aero-gates`
  - **用途只有產 artifact 與做 bounded structural compare，不是這包的成功標準**

artifact：

- `/tmp/track_v_smoke_candidate_debug/mult_4p000/candidate_avl_spanwise/candidate_avl_spanwise_loads.json`

接著直接比較：

- `legacy_refresh`
  - output: `/tmp/track_v_direct_legacy`
- repaired `candidate_avl_spanwise`
  - output: `/tmp/track_v_direct_candidate_avl`

結果摘要：

| path | `overall_feasible` | `total_structural_mass_kg` | `jig_ground_clearance_min_m` | recovery |
| --- | --- | ---: | ---: | --- |
| `legacy_refresh` | `false` | `21.740001` | `-0.026532` | `enabled=true`, `triggered=true` |
| repaired `candidate_avl_spanwise` | `true` | `21.740001` | `0.033523` | `enabled=true`, `triggered=false` |

額外觀察：

- `legacy_refresh` 的 recovery 沒有被新 code 影響，仍然是 `enabled=true`
- repaired `candidate_avl_spanwise` 的 summary 也明確顯示 `ground_clearance_recovery.enabled=true`
- 這次 `candidate_avl_spanwise` baseline 已經過線，所以沒有觸發 recovery；但 recovery 沒有被禁用
- `candidate_avl_spanwise` contract JSON 內已明確寫出：
  - `Selected cruise AoA is inherited from the outer-loop AVL trim result`
  - `Outer-loop AVL trim / aero gates remain the candidate load-state owner`

## 5. 風險與未完成處

- 還沒做真正的 Track W side-by-side compare，所以現在只能說：
  - ownership / gate / recovery drift 已修回來
  - 但 repaired `candidate_avl_spanwise` 和 `legacy_refresh` 在結構結果上仍然不等價
- 這次沒有跑一個「candidate AVL baseline 本身會觸發 recovery」的真實 smoke case；那一段目前主要由 targeted tests 保住
- full-gate smoke 在這組 seed 仍然被 `trim_aoa_exceeds_limit` 擋住，所以這包沒有聲稱 repaired AVL path 已經成為新的 full-gate winner，只是證明它不再偷偷繞過 gate

## 6. 建議下一步

- 直接進 `Track W`
- 用同一組 seed 做：
  - `legacy_refresh`
  - repaired `candidate_avl_spanwise`
  - 如有需要再加 `candidate_rerun_vspaero`
- 目標不是再修 plumbing，而是回答：
  - repaired `candidate_avl_spanwise` 現在能不能被描述成「舊 AVL-first flow + spanwise lift ownership」
  - 如果還不能，差異到底是 AoA/load-state ownership 的遺毒，還是 spanwise load distribution 本身就真的改變了結構 verdict
