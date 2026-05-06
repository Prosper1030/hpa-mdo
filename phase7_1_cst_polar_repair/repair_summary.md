# Phase 7.1 CST Focused Polar Repair

## Scope

This is a diagnostic repair run only. It does not change production ranking, hard gates, broad CST/NSGA results, or the original full-polar archive labels. The original archive quality and repaired diagnostic quality are kept separate.

- User-listed top repair candidates run: `5`
- Focused XFOIL/JXFoil queries: `82`
- Raw focused polar points preserved: `11898`
- Classification counts: `{'repaired_to_full_polar_candidate': 4, 'repaired_to_actual_sidecar_query_grade_only': 1}`

## Repair Results

| airfoil_id | zone | original_jump_count | patched_raw_jump_count | patched_prestall_jump_count | patched_design_prestall_jump_count | actual_sidecar_query_quality_repaired | mean_cd | cd_p90 | stall_margin_cl | repaired_archive_source_quality | classification |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| cst_mid2_seedless_sobol_0619_a07c5c7e | mid2 | 6 | 0 | 0 | 0 | repaired_actual_sidecar_query_grade | 0.0102461566 | 0.0103895848 | 0.163223655 | diagnostic_repaired_full_polar_candidate | repaired_to_full_polar_candidate |
| cst_tip_nsga2_g02_child_0085_cb99bc9c | tip | 8 | 2 | 0 | 0 | repaired_actual_sidecar_query_grade | 0.0106929567 | 0.0117153793 | 0.360651855 | diagnostic_actual_sidecar_query_grade_only | repaired_to_actual_sidecar_query_grade_only |
| cst_root_nsga2_g03_child_0090_3408e0ca | root | 1 | 0 | 0 | 0 | repaired_actual_sidecar_query_grade | 0.0107951685 | 0.011206673 | 0.240241775 | diagnostic_repaired_full_polar_candidate | repaired_to_full_polar_candidate |
| cst_tip_nsga2_g06_child_0101_f4c46cf4 | tip | 7 | 0 | 0 | 0 | repaired_actual_sidecar_query_grade | 0.01110923 | 0.0123285689 | 0.318093788 | diagnostic_repaired_full_polar_candidate | repaired_to_full_polar_candidate |
| cst_mid2_nsga2_g04_child_0012_72b8e600 | mid2 | 7 | 0 | 0 | 0 | repaired_actual_sidecar_query_grade | 0.011937109 | 0.0135224912 | 0.112738234 | diagnostic_repaired_full_polar_candidate | repaired_to_full_polar_candidate |

## Engineering Read

The focused sweeps replace only local discontinuity groups in a diagnostic patched table. If a candidate clears the actual query branch but still has raw high-alpha discontinuity, it is not promoted to a full archive mission-grade record here.
