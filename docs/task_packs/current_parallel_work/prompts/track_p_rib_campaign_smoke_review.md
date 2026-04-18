# Task Prompt: Track P Rib Campaign Smoke Review

你現在要在 `/Volumes/Samsung SSD/hpa-mdo` 做一個**真實 run / report 任務**。

## 先讀

1. `CURRENT_MAINLINE.md`
2. `project_state.yaml`
3. `docs/TARGET_STANDARD_GAP_MAP.md`
4. `docs/TARGET_STANDARD_PROGRAM_PLAN.md`
5. `docs/RIB_INTEGRATION_PLAN.md`
6. `scripts/direct_dual_beam_inverse_design.py`
7. `scripts/direct_dual_beam_inverse_design_feasibility_sweep.py`
8. `scripts/dihedral_sweep_campaign.py`

## 任務目標

用**真實 smoke campaign** 檢查目前這套 rib candidate contract 是否工程合理。

你要回答的核心問題不是「code 有沒有 compile」，而是：

`rib_zonewise=limited_zonewise`

相對於

`rib_zonewise=off`

在真實 rerun-aero 路徑下，winner ranking 是不是 `sane`。

## 最低要求

- 優先使用 `candidate_rerun_vspaero`
- 至少做一組 `off` vs `limited_zonewise` 的可比 smoke
- 優先用 `direct_dual_beam_inverse_design_feasibility_sweep.py`
- 如果時間與工具鏈允許，可再補一個更小型的 `dihedral_sweep_campaign.py` 對照

## 你要輸出的報告

請把結果寫到：

`docs/task_packs/current_parallel_work/reports/rib_campaign_smoke_report.md`

報告至少包含：

1. 你實際跑了哪些命令
2. 是否真的跑到 `candidate_rerun_vspaero`
3. `off` vs `limited_zonewise` 的比較表
4. 下列欄位的 winner / selected-case 比較：
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
5. 你的總結判斷，只能三選一：
   - `SANE`
   - `SUSPICIOUS`
   - `BLOCKED`
6. 你認為下一步應該是：
   - 調 penalty / surrogate
   - 做 finalist local spot-check
   - 或先維持現狀

## 執行原則

- 先用最小可代表的 search budget，不要一開始就跑很大
- 可以接受 10 到 30 分鐘級別的 runtime，但不要無限制擴張
- 不要在同一包裡順手改 code；這一包是 run / review，不是 patch 任務
- 如果被工具鏈卡住，可以寫 `BLOCKED`，但要清楚寫出 blocker 是什麼
- 不要把 `legacy_refresh` 的結果假裝成 `candidate_rerun_vspaero`

## 推薦 write scope

- `docs/task_packs/current_parallel_work/reports/rib_campaign_smoke_report.md`

## 不要做

- 不要改 `scripts/**`
- 不要改 `src/**`
- 不要改 `CURRENT_MAINLINE.md`
- 不要改 `docs/GRAND_BLUEPRINT.md`
- 不要改 `configs/blackcat_004.yaml`
