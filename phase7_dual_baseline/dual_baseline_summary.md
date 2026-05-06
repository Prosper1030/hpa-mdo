# Phase 7 Dual Baseline Summary

This report keeps the two quality labels separate. `archive_source_quality` remains the conservative full-polar archive label; `actual_sidecar_query_quality` is the query-level label at the actual AVL sidecar Re/Cl work points. No ranking, objective, penalty, or hard gate is changed here.

## Baselines

| baseline_role | policy_id | assignment | e_CDi | target_vs_avl_rms | target_vs_avl_outer_delta | profile_cd | CD0_total_est | mission_drag_budget_band | min_stall_margin | max_station_utilization | archive_source_quality | actual_sidecar_query_quality |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| performance_candidate | A | root:dae11\|mid1:dae11\|mid2:clarkysm\|tip:clarkysm | 0.985693064 | 0.0512991721 | 0.111664536 | 0.0109945289 | 0.0148844085 | target | 1.4291479 | 0.904673484 | archive_not_mission_grade_sidecar | actual_sidecar_query_grade_sidecar |
| conservative_baseline | C | root:cst_root_nsga2_g05_child_0019_00cc4dca\|mid1:cst_mid1_nsga2_g06_child_0001_a86879e2\|mid2:clarkysm\|tip:clarkysm | 0.985598464 | 0.0440886932 | 0.0901669948 | 0.0113983551 | 0.0152882346 | target | 3.05110821 | 0.82461217 | archive_mission_grade_sidecar | actual_sidecar_query_grade_sidecar |

## Decision Read

- Conservative baseline for reports: Policy C / E, using CST root/mid1 and ClarkY mid2/tip. It is the cleanest report baseline because it passes both archive mission-grade and actual-sidecar query-grade labels.
- Performance candidate to keep: Policy A / D, using DAE11 root/mid1 and ClarkY mid2/tip. It has lower profile Cd and CD0 estimate, and it passes actual-sidecar query grading.
- The archive caveat on Policy A is real but conservative: DAE11 failed the archive envelope because the archive demanded root/mid1 Cl up to about 1.56, while the actual Policy A sidecar demand is lower and leaves positive safe-Cl margin.
- DAE11 should not be described as a bad airfoil. The right wording is archive-caveated, actual-sidecar acceptable for this operating point.

## A Versus C

| metric | policy_A_value | policy_C_value | A_minus_C | A_minus_C_percent_of_C | engineering_direction |
| --- | --- | --- | --- | --- | --- |
| e_CDi | 0.985693064 | 0.985598464 | 9.46e-05 | 0.00959822924 | A_better |
| target_vs_avl_rms | 0.0512991721 | 0.0440886932 | 0.0072104789 | 16.3544854 | C_better |
| target_vs_avl_outer_delta | 0.111664536 | 0.0901669948 | 0.0214975412 | 23.8419183 | C_better |
| profile_cd | 0.0109945289 | 0.0113983551 | -0.0004038262 | -3.54284628 | A_better |
| CD0_total_est | 0.0148844085 | 0.0152882346 | -0.0004038261 | -2.64141747 | A_better |
| min_stall_margin | 1.4291479 | 3.05110821 | -1.62196031 | -53.1597111 | C_better |
| max_station_utilization | 0.904673484 | 0.82461217 | 0.080061314 | 9.70896585 | C_better |
