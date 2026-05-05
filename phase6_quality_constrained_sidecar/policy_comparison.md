# Phase 6 Quality-Constrained Sidecar Policy Comparison

Generated from `output/airfoil_db/overnight_cst_zone_search/phase6_cst_avl_sidecar/spanload_design_smoke_report.json` with full-polar database `output/airfoil_db/full_polar_archive/airfoil_database.json`.

No aircraft main ranking, rejection gate, or production sidecar code was changed. Policy A uses the current sidecar combination generator. Policies B-E use the same zone candidate score and evaluate the top two eligible candidates per zone, then select the best successful AVL rerun using the existing sidecar best-score ordering: profile Cd, target-vs-AVL RMS, negative e_CDi, then combination index.

## Policy Results

| policy | assignment | e_CDi | rms | outer_delta | profile_cd | CD0_total | stall_margin | max_util | band | quality |
|---|---|---|---|---|---|---|---|---|---|---|
| A | root:dae11\|mid1:dae11\|mid2:clarkysm\|tip:clarkysm | 0.985693 | 0.051299 | 0.111665 | 0.010995 | 0.014884 | 1.429148 | 0.904673 | target | not_mission_grade_sidecar |
| B | root:cst_root_nsga2_g05_child_0019_00cc4dca\|mid1:cst_mid1_nsga2_g06_child_0001_a86879e2\|mid2:cst_mid2_nsga2_g04_child_0024_0b55bfc3\|tip:cst_tip_nsga2_g02_child_0085_cb99bc9c | 0.957613 | 0.065304 | 0.121131 | 0.012108 | 0.015998 | 2.916949 | 0.835087 | target | not_mission_grade_sidecar |
| C | root:cst_root_nsga2_g05_child_0019_00cc4dca\|mid1:cst_mid1_nsga2_g06_child_0001_a86879e2\|mid2:clarkysm\|tip:clarkysm | 0.985598 | 0.044089 | 0.090167 | 0.011398 | 0.015288 | 3.051108 | 0.824612 | target | mission_grade_sidecar |
| D | root:cst_root_nsga2_g05_child_0019_00cc4dca\|mid1:cst_mid1_nsga2_g06_child_0001_a86879e2\|mid2:dae31\|tip:dae41 | 0.990375 | 0.039982 | 0.080499 | 0.01097 | 0.01486 | 3.244444 | 0.809218 | target | not_mission_grade_sidecar |
| E | root:cst_root_nsga2_g05_child_0019_00cc4dca\|mid1:cst_mid1_nsga2_g06_child_0001_a86879e2\|mid2:clarkysm\|tip:clarkysm | 0.985598 | 0.044089 | 0.090167 | 0.011398 | 0.015288 | 3.051108 | 0.824612 | target | mission_grade_sidecar |

## Per-Zone Seed/DAE Versus CST

`actual_cl` is AVL actual local Cl from the rerun input envelope. `delta_mean_cd` is best CST minus best seed/DAE; positive means CST is higher drag at the current sidecar work points.

| zone | actual_cl | selected | best_seed_dae | seed_dae_mean_cd | best_cst | cst_mean_cd | delta_mean_cd | reason |
|---|---|---|---|---|---|---|---|---|
| root | 1.527564 / p90 1.552016 | dae11 | dae11 | 0.011606 | cst_root_nsga2_g03_child_0051_fbaca644 | 0.013083 | 0.001476 | selected mean_cd lower by 0.001476; quality not_mission_grade_sidecar vs CST mission_grade_sidecar |
| mid1 | 1.483199 / p90 1.54926 | dae11 | dae11 | 0.0128 | cst_mid1_nsga2_g06_child_0001_a86879e2 | 0.013825 | 0.001025 | selected mean_cd lower by 0.001025; quality not_mission_grade_sidecar vs CST mission_grade_sidecar |
| mid2 | 0.670381 / p90 0.670381 | clarkysm | clarkysm | 0.007935 | cst_mid2_nsga2_g04_child_0024_0b55bfc3 | 0.009276 | 0.001341 | selected mean_cd lower by 0.001341 |
| tip | 0.404941 / p90 0.467074 | clarkysm | clarkysm | 0.008873 | cst_tip_nsga2_g02_child_0085_cb99bc9c | 0.009421 | 0.000549 | selected mean_cd lower by 0.000549; quality mission_grade_sidecar vs CST not_mission_grade_sidecar |

## Special Probe: Tip Forced To DAE31

- Assignment: `root:dae11|mid1:dae11|mid2:clarkysm|tip:dae31`
- Status: `ok`
- e_CDi: `0.932308`
- target_vs_avl_rms / outer_delta: `0.113611` / `0.252642`
- profile_cd / CD0_total_est: `0.01188` / `0.01577`
- min_stall_margin / max_station_utilization: `1.966966` / `0.8688`
- mission_drag_budget_band: `target`
- source_quality: `not_mission_grade_sidecar`

See `policy_comparison.csv` and `zone_seed_vs_cst_analysis.csv` for the full per-zone source-quality columns.
