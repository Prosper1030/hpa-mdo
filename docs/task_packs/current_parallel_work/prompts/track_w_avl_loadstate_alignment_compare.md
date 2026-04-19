# Track W — AVL / Legacy / Rerun Load-State Alignment Compare

> 目標：在 Track V 修完之後，用同一組 seeds 比較三條路徑，回答 repaired `candidate_avl_spanwise` 到底是不是「舊流程 + spanwise lift distribution」。

## 前提

這包 **一定要等 Track V 驗證通過後** 才能做。

## 這包要回答的問題

對同一組 seed，比較：

- `legacy_refresh`
- repaired `candidate_avl_spanwise`
- `candidate_rerun_vspaero`

你要回答：

1. repaired `candidate_avl_spanwise` 的 AoA / load-state ownership 是否還和舊流程一致？
2. 它只是多了 spanwise lift distribution，還是仍然偷偷換了一個新工況？
3. 它和 `candidate_rerun_vspaero` 的差異，是 confirm-level 差異，還是已經大到像另一個完全不同的 candidate state？

## 寫入範圍

你只能新增或修改：

- `docs/task_packs/current_parallel_work/reports/avl_loadstate_alignment_report.md`

不要改 code。

## 不要碰

- `README.md`
- `CURRENT_MAINLINE.md`
- `docs/GRAND_BLUEPRINT.md`
- `configs/blackcat_004.yaml`
- 任一 `scripts/*.py`
- 任一 `tests/*.py`

## 建議比較條件

至少跑一組共同 seed：

- `target_shape_z_scale = 4.0`
- `dihedral_exponent = 2.2`
- `rib_zonewise = off`

如果時間允許，再加：

- 一組較接近 clearance pass region 的 seed
- 一組較保守的 seed

## 每條路徑至少要記錄

- `selected_cruise_aoa_deg`
- `aero_source_mode`
- `load_source`
- `total structural mass`
- `jig ground clearance`
- `total half-span lift`
- `total |torque| half-span`
- `overall feasible / fail reason`
- 是否需要 `skip-aero-gates`

## 你最後要明確下判斷

報告最後一定要直接回答：

1. repaired `candidate_avl_spanwise` 現在是不是**可以被描述成**：
   - 「舊 AVL-first 外圈 + candidate-owned spanwise lift distribution」
2. 如果還不行，差在哪裡？
3. 接下來要不要直接進 `Track X`？

## 成功標準

- 有一份清楚的 side-by-side report
- 不是只貼 log，而是有明確判斷
- 能讓下一步知道：是直接重建 shortlist，還是還要回去補一個更小的修正包

