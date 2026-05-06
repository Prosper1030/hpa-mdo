# Actual Sidecar Envelope Regrade

## Scope

This is a report-only regrade. It does not change aircraft ranking, production sidecar ranking, objective functions, penalties, or hard gates. The actual AVL sidecar envelopes were rerun for the already studied assignments A-E at the archived cruise condition `6.600000 m/s`; no CST/NSGA search was rerun.

`archive_source_quality` is the record-level label from the full-polar archive. `actual_sidecar_query_quality` is a separate query-level label using the actual AVL sidecar Re/Cl work points. Envelope-dependent archive failures such as `insufficient_safe_clmax_margin` are allowed to clear if the actual sidecar envelope has enough margin. Non-envelope defects such as `discontinuous_cd` remain blockers.

## Policy Comparison

| Policy | Assignment | e_CDi | RMS | outer delta | profile Cd | CD0 est | stall margin | util | archive quality | actual quality |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|---|
| A unrestricted | root:dae11\|mid1:dae11\|mid2:clarkysm\|tip:clarkysm | 0.985693 | 0.051299 | 0.111665 | 0.010995 | 0.014884 | 1.429148 | 0.904673 | archive_not_mission_grade_sidecar | actual_sidecar_query_grade_sidecar |
| B CST-only | root:cst_root_nsga2_g05_child_0019_00cc4dca\|mid1:cst_mid1_nsga2_g06_child_0001_a86879e2\|mid2:cst_mid2_nsga2_g04_child_0024_0b55bfc3\|tip:cst_tip_nsga2_g02_child_0085_cb99bc9c | 0.957613 | 0.065304 | 0.121131 | 0.012108 | 0.015998 | 2.916949 | 0.835087 | archive_not_mission_grade_sidecar | actual_sidecar_query_not_mission_grade_sidecar |
| C full-polar archive mission-grade only | root:cst_root_nsga2_g05_child_0019_00cc4dca\|mid1:cst_mid1_nsga2_g06_child_0001_a86879e2\|mid2:clarkysm\|tip:clarkysm | 0.985598 | 0.044089 | 0.090167 | 0.011398 | 0.015288 | 3.051108 | 0.824612 | archive_mission_grade_sidecar | actual_sidecar_query_grade_sidecar |
| D actual-sidecar-query-grade only | root:dae11\|mid1:dae11\|mid2:clarkysm\|tip:clarkysm | 0.985693 | 0.051299 | 0.111665 | 0.010995 | 0.014884 | 1.429148 | 0.904673 | archive_not_mission_grade_sidecar | actual_sidecar_query_grade_sidecar |
| E no DAE | root:cst_root_nsga2_g05_child_0019_00cc4dca\|mid1:cst_mid1_nsga2_g06_child_0001_a86879e2\|mid2:clarkysm\|tip:clarkysm | 0.985598 | 0.044089 | 0.090167 | 0.011398 | 0.015288 | 3.051108 | 0.824612 | archive_mission_grade_sidecar | actual_sidecar_query_grade_sidecar |
| F no ClarkY | root:cst_root_nsga2_g05_child_0019_00cc4dca\|mid1:cst_mid1_nsga2_g06_child_0001_a86879e2\|mid2:dae31\|tip:dae41 | 0.990375 | 0.039982 | 0.080499 | 0.010970 | 0.014860 | 3.244444 | 0.809218 | archive_not_mission_grade_sidecar | actual_sidecar_query_not_mission_grade_sidecar |

## Direct Answers

- Policy A becomes acceptable under actual-sidecar-envelope query grading: root DAE11 margin `0.159054`, mid1 DAE11 margin `0.141624`. Its archive label remains not mission-grade because `archive_source_quality` is still `full_polar_candidate_not_mission_grade`.
- DAE11 is safe at the actual Policy A sidecar Cl demand: root/mid1 actual Cl max are `1.326623` / `1.344053`, below DAE11 safe_clmax `1.485677`.
- CST candidates mostly do not downgrade from the actual envelope itself. Actual query pass count is `65/155` CST policy-zone checks. The CST failures are dominated by record-level `discontinuous_cd`, not by actual Re/Cl coverage.
- The one clean coverage-style recommendation from this regrade is DAE31 at the tip: it remains archive mission-grade, but the actual tip query includes lower-Cl work points outside the available polar branch, so it is not actual-sidecar-query grade until that tip envelope is gap-filled and rechecked.
- Policy C is still the cleanest conservative baseline because it is both archive mission-grade and actual-sidecar-query grade, with CST root/mid1 and ClarkY outer sections.
- If `actual_sidecar_query_quality` is the required quality label for the studied shortlist, the best assignment is Policy D's selected row: `root:dae11|mid1:dae11|mid2:clarkysm|tip:clarkysm`. That is the prior Policy A geometry/assignment, now actual-query-grade, with profile Cd `0.010995`.

## Engineering Read

The actual sidecar envelope confirms the previous suspicion: the original archive envelope was conservative for DAE11 at root/mid1. Under the actual AVL sidecar loading, DAE11 has positive safe-Cl margin. That is useful, but it does not automatically make Policy A the cleanest engineering baseline, because it still relies on a record that failed the archive grading contract.

For CST, the actual envelope does not rescue the tip CST family if the blocker is `discontinuous_cd`; a smaller local Cl demand cannot repair a polar smoothness defect. The one targeted gap-fill candidate from this run is DAE31 at the tip, where the issue is actual-query Cl coverage rather than a record-level data-quality defect. For the discontinuous CST/DAE41 cases, the right next step is either targeted polar repair or a documented policy decision that actual-query grading may override envelope-only failures but not full-polar data-quality failures.
