# Task Prompt: Track R Multi-Seed Rib Smoke Signal Hunt

你現在要在 `/Volumes/Samsung SSD/hpa-mdo` 做一個**真實 run / review 任務**。

## 先讀

1. `CURRENT_MAINLINE.md`
2. `project_state.yaml`
3. `docs/TARGET_STANDARD_GAP_MAP.md`
4. `docs/TARGET_STANDARD_PROGRAM_PLAN.md`
5. `docs/RIB_INTEGRATION_PLAN.md`
6. `docs/task_packs/current_parallel_work/reports/rib_campaign_smoke_report.md`
7. `scripts/direct_dual_beam_inverse_design.py`
8. `scripts/direct_dual_beam_inverse_design_feasibility_sweep.py`

## 任務目標

用**小型多 seed rerun-aero smoke**，把目前的 rib smoke 狀態從「單點 `SUSPICIOUS`」再往前推一層。

你要回答的核心問題是：

`rib_zonewise=limited_zonewise`

相對於

`rib_zonewise=off`

在 `candidate_rerun_vspaero` 路徑下，能不能找到至少一組**不是 sentinel fallback** 的可比 selected-case。

## 最低要求

- 只能用 `candidate_rerun_vspaero`
- 至少測 `2 到 4` 個有訊號的代表性 seeds
- 每個 seed 都要比：
  - `rib_zonewise=off`
  - `rib_zonewise=limited_zonewise`
- 優先用 `direct_dual_beam_inverse_design_feasibility_sweep.py`
- 不要一開始就開很大的 grid；優先做小型但可比較的 replay

## seed 選擇原則

- 可以參考已存在的 archive / diagnostics / active wall diagnostics
- 優先挑：
  - 之前接近 feasible 的 seed
  - 不是明顯死點的 seed
  - 能代表不同幾何邊界趨勢的 `2 到 4` 組
- 不需要做大搜尋；目的是拿到**可比訊號**，不是求最終最優解

## 你要輸出的報告

請把結果寫回：

`docs/task_packs/current_parallel_work/reports/rib_campaign_smoke_report.md`

報告至少包含：

1. 你實際跑了哪些命令
2. 這次選了哪些 seeds，為什麼
3. 哪些 seed 成功跑到 `candidate_rerun_vspaero`
4. 哪些 seed 仍然是 sentinel fallback
5. 至少一張 `off` vs `limited_zonewise` 的比較表
6. 下列欄位的 selected-case 比較：
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
7. 最終判斷，只能三選一：
   - `SANE`
   - `SUSPICIOUS`
   - `BLOCKED`
8. 你認為下一步應該是：
   - 進 `Track M` 做 tuning
   - 進 `Track N` 做 finalist spot-check
   - 或維持現狀再補更多 smoke

## 執行原則

- 先用最小可代表的 search budget，不要暴力擴張
- 可以接受約 `10 到 30 分鐘` 級別 runtime，但不要無限制放大
- 不要在這一包裡改 code；這一包是 run / review，不是 patch 任務
- 如果遇到新 blocker，可以寫 `BLOCKED`，但要清楚寫出 blocker 是什麼
- 不要把 `legacy_refresh` 冒充成 `candidate_rerun_vspaero`
- 如果所有 seeds 都還是 sentinel fallback，也要如實寫 `SUSPICIOUS` 或 `BLOCKED`，不要硬湊結論

## 推薦 write scope

- `docs/task_packs/current_parallel_work/reports/rib_campaign_smoke_report.md`

## 不要做

- 不要改 `scripts/**`
- 不要改 `src/**`
- 不要改 `CURRENT_MAINLINE.md`
- 不要改 `docs/GRAND_BLUEPRINT.md`
- 不要改 `configs/blackcat_004.yaml`
