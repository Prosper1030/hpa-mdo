# Track R — Repaired-Shortlist Rib Smoke Replay

> 目標：在 post-fix refreshed canonical repaired AVL-first shortlist 上，重新回答 rib ranking 到底有沒有真實訊號。

## 先讀

1. `CURRENT_MAINLINE.md`
2. `project_state.yaml`
3. `docs/TARGET_STANDARD_GAP_MAP.md`
4. `docs/TARGET_STANDARD_PROGRAM_PLAN.md`
5. `docs/RIB_INTEGRATION_PLAN.md`
6. `docs/task_packs/current_parallel_work/reports/avl_postfix_shortlist_refresh_report.md`
7. `docs/task_packs/current_parallel_work/reports/rib_campaign_smoke_report.md`
8. `scripts/direct_dual_beam_inverse_design.py`
9. `scripts/direct_dual_beam_inverse_design_feasibility_sweep.py`

## 任務目標

不要再用舊的 suspicious baseline seeds。
請用 **post-fix refreshed canonical repaired shortlist seeds**，重新做一輪小型 rib smoke。

你要回答的核心問題是：

`rib_zonewise=limited_zonewise`

相對於

`rib_zonewise=off`

在 repaired shortlist 上，能不能找到至少一組**不是 sentinel fallback** 的可比 selected-case。

## 最低要求

- 優先用 post-fix shortlist 明確推薦的 `2 到 4` 個 seeds
- 每個 seed 都要比：
  - `rib_zonewise=off`
  - `rib_zonewise=limited_zonewise`
- 先用 AVL-first repaired shortlist 做挑選，再用 `candidate_rerun_vspaero` 做 confirm-level compare
- 不要擴成大搜尋；這一包是 repaired-shortlist smoke，不是新一輪 coarse sweep

## 你要輸出的報告

請把結果寫回：

`docs/task_packs/current_parallel_work/reports/rib_campaign_smoke_report.md`

報告至少包含：

1. 你實際跑了哪些命令
2. 這次實際採用了哪幾個 post-fix shortlist seeds
3. 每個 seed 的：
   - `rib_zonewise=off` 結果
   - `rib_zonewise=limited_zonewise` 結果
4. 至少一張 `off` vs `limited_zonewise` 的比較表
5. selected-case 至少要比較：
   - `objective_value_kg`
   - `total_structural_mass_kg`
   - `jig_ground_clearance_min_m`
   - `target_shape_error_max_m`
   - `loaded_shape_main_z_error_max_m`
   - `rib_design.design_key`
   - `rib_design.effective_warping_knockdown`
   - `rib_design.unique_family_count`
   - `rib_design.family_switch_count`
   - `rib_design.objective_penalty_kg`
6. 最終判斷，只能三選一：
   - `SANE`
   - `SUSPICIOUS`
   - `BLOCKED`
7. 你認為下一步應該是：
   - 進 `Track M` 做 tuning
   - 進 `Track N` 做 finalist spot-check
   - 或先停在目前結果

## 執行原則

- 先用最小可代表的 search budget，不要暴力擴張
- 可以接受約 `10 到 30 分鐘` 級別 runtime，但不要無限制放大
- 不要在這一包裡改 code；這一包是 run / review，不是 patch 任務
- 如果遇到新 blocker，可以寫 `BLOCKED`，但要清楚寫出 blocker 是什麼
- 不要把 `legacy_refresh` 冒充成 repaired shortlist 或 `candidate_rerun_vspaero`
- 如果所有 seeds 都還是 sentinel fallback，也要如實寫 `SUSPICIOUS` 或 `BLOCKED`

## 推薦 write scope

- `docs/task_packs/current_parallel_work/reports/rib_campaign_smoke_report.md`

## 不要做

- 不要改 `scripts/**`
- 不要改 `src/**`
- 不要改 `CURRENT_MAINLINE.md`
- 不要改 `docs/GRAND_BLUEPRINT.md`
- 不要改 `configs/blackcat_004.yaml`
