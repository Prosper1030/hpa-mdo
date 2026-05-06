# Sidecar After Phase 7.1 Repair

These sidecar rows use a diagnostic in-memory repaired airfoil database. The production archive is unchanged. Rows containing a candidate that only cleared actual-sidecar query quality are explicitly labeled not mission-grade for conservative reporting.

| policy_id | policy_name | assignment | status | e_CDi | target_vs_avl_rms | target_vs_avl_outer_delta | profile_cd | CD0_total_est | mission_drag_budget_band | min_stall_margin | max_station_utilization | sidecar_source_quality_from_repaired_db |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A | performance candidate Policy A/D | root:dae11\|mid1:dae11\|mid2:clarkysm\|tip:clarkysm | ok | 0.985693064 | 0.0512991721 | 0.111664536 | 0.0109945289 | 0.0148844085 | target | 1.4291479 | 0.904673484 | not_mission_grade_sidecar |
| C | conservative baseline Policy C/E | root:cst_root_nsga2_g05_child_0019_00cc4dca\|mid1:cst_mid1_nsga2_g06_child_0001_a86879e2\|mid2:clarkysm\|tip:clarkysm | ok | 0.985598464 | 0.0440886932 | 0.0901669948 | 0.0113983551 | 0.0152882346 | target | 3.05110821 | 0.82461217 | mission_grade_sidecar |
| B | CST-only prior assignment with repaired tip record | root:cst_root_nsga2_g05_child_0019_00cc4dca\|mid1:cst_mid1_nsga2_g06_child_0001_a86879e2\|mid2:cst_mid2_nsga2_g04_child_0024_0b55bfc3\|tip:cst_tip_nsga2_g02_child_0085_cb99bc9c | ok | 0.957613347 | 0.0653036126 | 0.121131249 | 0.0121096113 | 0.0159994909 | target | 2.91694916 | 0.835086539 | diagnostic_actual_query_only_not_mission_grade_sidecar |
| E | no DAE prior assignment | root:cst_root_nsga2_g05_child_0019_00cc4dca\|mid1:cst_mid1_nsga2_g06_child_0001_a86879e2\|mid2:clarkysm\|tip:clarkysm | ok | 0.985598464 | 0.0440886932 | 0.0901669948 | 0.0113983551 | 0.0152882346 | target | 3.05110821 | 0.82461217 | mission_grade_sidecar |
| F | no ClarkY prior assignment | root:cst_root_nsga2_g05_child_0019_00cc4dca\|mid1:cst_mid1_nsga2_g06_child_0001_a86879e2\|mid2:dae31\|tip:dae41 | ok | 0.990374694 | 0.0399820462 | 0.0804985816 | 0.0109697282 | 0.0148596078 | target | 3.24444433 | 0.809218301 | not_mission_grade_sidecar |
| G | repaired CST no-ClarkY diagnostic best-local-Cd assignment | root:cst_root_nsga2_g03_child_0090_3408e0ca\|mid1:cst_mid1_nsga2_g06_child_0001_a86879e2\|mid2:cst_mid2_seedless_sobol_0619_a07c5c7e\|tip:cst_tip_nsga2_g02_child_0085_cb99bc9c | ok | 0.981453963 | 0.0562330119 | 0.0879520665 | 0.0114858229 | 0.0153757025 | target | 2.209464 | 0.851871345 | diagnostic_actual_query_only_not_mission_grade_sidecar |
| H | repaired CST alternate tip/mid2 diagnostic assignment | root:cst_root_nsga2_g05_child_0019_00cc4dca\|mid1:cst_mid1_nsga2_g06_child_0001_a86879e2\|mid2:cst_mid2_nsga2_g04_child_0012_72b8e600\|tip:cst_tip_nsga2_g06_child_0101_f4c46cf4 | ok | 0.991546075 | 0.0424921117 | 0.0856816387 | 0.0129693459 | 0.0168592255 | target | 2.52567982 | 0.841683911 | mission_grade_sidecar |

## Repaired-CST Comparison

- G repaired CST no-ClarkY diagnostic best-local-Cd assignment: profile_cd=0.0114858229, CD0=0.0153757025, e_CDi=0.981453963, profile_cd_delta_vs_A=0.000491294, profile_cd_delta_vs_C=8.74678e-05
- H repaired CST alternate tip/mid2 diagnostic assignment: profile_cd=0.0129693459, CD0=0.0168592255, e_CDi=0.991546075, profile_cd_delta_vs_A=0.001974817, profile_cd_delta_vs_C=0.0015709908

- G is the closest repaired-CST diagnostic to Policy C on profile drag, but it is still above Policy A and slightly above Policy C, and it remains actual-query-only because the tip repair did not clear full raw continuity.
- H improves e_CDi and target matching relative to A/C, but its profile Cd and CD0 estimate are much worse, so it is not a mission-drag improvement.

Best profile Cd among rerun rows remains `F` with profile_cd `0.0109697282`; among repaired-CST diagnostics, `G` is closest to Policy C but does not beat A or C on profile drag.
