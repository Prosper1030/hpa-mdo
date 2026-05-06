# Policy Comparison After DAE11 Gap-Fill

DAE11-only gap-fill source: `output/airfoil_db/full_polar_archive/phase6_dae11_quality_rescue/dae11_gapfill_polar.csv`. Merged audit-only database: `output/airfoil_db/full_polar_archive/phase6_dae11_quality_rescue/dae11_gapfilled_airfoil_database.json`.

DAE11 source quality after gap-fill: `full_polar_candidate_not_mission_grade`. Upgrade allowed: `False`.

| case | assignment | quality | e_CDi | rms | outer_delta | profile_cd | CD0_total | stall_margin | max_util | band |
|---|---|---|---|---|---|---|---|---|---|---|
| Policy A unrestricted | root:dae11\|mid1:dae11\|mid2:clarkysm\|tip:clarkysm | not_mission_grade_sidecar | 0.985693 | 0.051299 | 0.111665 | 0.010991 | 0.014881 | 1.39054 | 0.903768 | target |
| Policy C mission-grade-only | root:cst_root_nsga2_g05_child_0019_00cc4dca\|mid1:cst_mid1_nsga2_g06_child_0001_a86879e2\|mid2:clarkysm\|tip:clarkysm | mission_grade_sidecar | 0.985598 | 0.044089 | 0.090167 | 0.011398 | 0.015288 | 3.051108 | 0.824612 | target |
| DAE11 forced root/mid1 ClarkY outer | root:dae11\|mid1:dae11\|mid2:clarkysm\|tip:clarkysm | not_mission_grade_sidecar | 0.985693 | 0.051299 | 0.111665 | 0.010991 | 0.014881 | 1.39054 | 0.903768 | target |
| CST root/mid1 ClarkY outer | root:cst_root_nsga2_g05_child_0019_00cc4dca\|mid1:cst_mid1_nsga2_g06_child_0001_a86879e2\|mid2:clarkysm\|tip:clarkysm | mission_grade_sidecar | 0.985598 | 0.044089 | 0.090167 | 0.011398 | 0.015288 | 3.051108 | 0.824612 | target |

Policy C excludes DAE11 unless the DAE11 gap-fill actually earns `full_polar_mission_grade_candidate`. In this run DAE11 remains `full_polar_candidate_not_mission_grade` because `insufficient_safe_clmax_margin`.
