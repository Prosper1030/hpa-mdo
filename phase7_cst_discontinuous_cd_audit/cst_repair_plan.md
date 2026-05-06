# CST Discontinuous-Cd Repair Plan

## Scope

This is a proposed sidecar diagnostic only. It should not change main ranking, production gates, or global `archive_source_quality` labels until the repaired raw polar evidence is reviewed.

## First Repair Targets

| repair_rank | airfoil_id | zone | mean_cd | cd_p90 | stall_margin_cl | main_design_branch_risk | cause_category | trigger_region |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | cst_mid2_seedless_sobol_0619_a07c5c7e | mid2 | 0.0101166645 | 0.0101166645 | 0.160340493 | medium_near_cl_but_not_clear_main_branch | likely_sparse_alpha_grid_or_branch_issue_near_design_cl | Re=400000, clean, alpha 14.00->17.50, Cl 0.835->1.100, Cd 0.0596->0.2267 |
| 2 | cst_tip_nsga2_g02_child_0085_cb99bc9c | tip | 0.010431642 | 0.011039501 | 0.342613319 | medium_near_cl_but_not_clear_main_branch | likely_sparse_alpha_grid_or_branch_issue_near_design_cl | Re=125000, clean, alpha 12.50->14.50, Cl 0.765->0.968, Cd 0.0465->0.1845 |
| 3 | cst_root_nsga2_g03_child_0090_3408e0ca | root | 0.0108705077 | 0.011101079 | 0.240241304 | medium_near_cl_but_not_clear_main_branch | likely_XFOIL_branch_post_stall_issue | Re=100000, clean, alpha 17.50->18.00, Cl 1.623->1.262, Cd 0.1087->0.1946 |
| 4 | cst_tip_nsga2_g06_child_0101_f4c46cf4 | tip | 0.0113148217 | 0.0119798137 | 0.31809353 | medium_near_cl_but_not_clear_main_branch | likely_sparse_alpha_grid_or_branch_issue_near_design_cl | Re=345815, clean, alpha 11.50->15.00, Cl 0.813->1.033, Cd 0.0283->0.1624 |
| 5 | cst_mid2_nsga2_g04_child_0012_72b8e600 | mid2 | 0.0113842216 | 0.0113842216 | 0.115460181 | medium_near_cl_but_not_clear_main_branch | likely_sparse_alpha_grid_or_branch_issue_near_design_cl | Re=300000, clean, alpha 14.50->16.50, Cl 0.781->1.093, Cd 0.0716->0.1959 |
| 6 | cst_tip_nsga2_g04_child_0096_6230567a | tip | 0.0116385903 | 0.0123134342 | 0.513890984 | low_far_from_design_cl | likely_sparse_alpha_grid_issue | Re=258201, clean, alpha 15.00->16.00, Cl 1.274->0.999, Cd 0.1020->0.2077 |
| 7 | cst_tip_nsga2_g05_child_0026_28eb9a70 | tip | 0.0119766838 | 0.012839884 | 0.292275704 | medium_near_cl_but_not_clear_main_branch | likely_sparse_alpha_grid_or_branch_issue_near_design_cl | Re=300000, clean, alpha 15.00->17.50, Cl 0.704->1.012, Cd 0.0713->0.2156 |

## Targeted Repair Procedure

1. Rerun only the listed CST candidates, not the full CST/NSGA search.
2. For each candidate, rerun the triggering Re and roughness mode plus one neighboring Re on each side if available.
3. Use a finer alpha grid: `0.25 deg` through the full local region, and `0.10 deg` around the detected jump if affordable.
4. Preserve clean and rough sweeps separately. If only clean trips the jump, do not infer rough failure; if rough trips it, isolate forced-transition behavior.
5. Keep raw points, nonconvergence warnings, branch labels, and post-stall points. Do not silently smooth or delete bad points.
6. Build a prestall-branch query table for actual-sidecar work points and compare it against the unfiltered full sweep.
7. Upgrade any label only after the repaired polar passes finite-Cd, branch continuity near design Cl, coverage, and roughness checks.

## What Not To Do Yet

- Do not rerun broad NSGA before the top CST polar evidence is repaired or rejected.
- Do not convert `actual_sidecar_query_quality` into a hard gate from this report alone.
- Do not globally relabel existing archive records; write repaired records as separate diagnostic artifacts first.
