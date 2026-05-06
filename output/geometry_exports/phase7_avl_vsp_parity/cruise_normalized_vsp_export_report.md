# Cruise Normalized VSP Export Report

Uniform incidence offsets were calibrated so AVL at solver alpha=0 reaches the mission CL_req. Relative twist, loaded z, chord, and airfoil assignment were preserved.

## policy_A_performance_candidate

- Added incidence: `4.633102 deg`
- AVL alpha=0 CL after offset: `1.168570`
- VSPAERO alpha=0 CL after offset: `1.120566`
- VSPAERO-derived offset for exact VSPAERO CL_req would be: `5.110168 deg`
- Offset delta VSPAERO-calibrated minus AVL-calibrated: `0.477065 deg`
- VSP3: `/Volumes/Samsung SSD/hpa-mdo/output/geometry_exports/phase7_avl_vsp_parity/cruise_normalized/policy_A_performance_candidate/policy_A_performance_candidate_cruise_normalized.vsp3`
- AVL: `/Volumes/Samsung SSD/hpa-mdo/output/geometry_exports/phase7_avl_vsp_parity/cruise_normalized/policy_A_performance_candidate/policy_A_performance_candidate_cruise_normalized.avl`

## policy_C_conservative_baseline

- Added incidence: `4.225158 deg`
- AVL alpha=0 CL after offset: `1.168760`
- VSPAERO alpha=0 CL after offset: `1.093316`
- VSPAERO-derived offset for exact VSPAERO CL_req would be: `4.974091 deg`
- Offset delta VSPAERO-calibrated minus AVL-calibrated: `0.748933 deg`
- VSP3: `/Volumes/Samsung SSD/hpa-mdo/output/geometry_exports/phase7_avl_vsp_parity/cruise_normalized/policy_C_conservative_baseline/policy_C_conservative_baseline_cruise_normalized.vsp3`
- AVL: `/Volumes/Samsung SSD/hpa-mdo/output/geometry_exports/phase7_avl_vsp_parity/cruise_normalized/policy_C_conservative_baseline/policy_C_conservative_baseline_cruise_normalized.avl`

## Note

These files are for manual cruise-alpha-zero inspection. They are not a new ranked geometry and do not replace the body-axis AVL parity exports. If the inspection target is VSPAERO-only alpha=0 rather than AVL alpha=0, use the VSPAERO-derived offset listed above as a follow-up variant.
