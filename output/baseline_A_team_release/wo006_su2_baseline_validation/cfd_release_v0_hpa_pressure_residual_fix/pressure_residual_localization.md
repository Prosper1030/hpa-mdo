# WO-006 Fine pressure residual localization

case: `output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0_hpa_solver_campaign_repair/fine_current_setup/openfoam_cases/fine/fullwing_artificial_tip_symmetry`
time: `2000`

## Reconstructed pressure CD

- `airfoil_upper`: CDp=-0.01402263, CLp=0.84432883, faces=37440
- `airfoil_lower`: CDp=0.03692039, CLp=0.31604370, faces=37440
- `te_wall`: CDp=0.00005225, CLp=-0.00000479, faces=1248
- `physical_tip_left`: CDp=0.00000000, CLp=0.00000000, faces=19520
- `physical_tip_right`: CDp=0.00000000, CLp=0.00000000, faces=19520
- `primary`: CDp=0.02289777, CLp=1.16037252, faces=74880
- `total_physical`: CDp=0.02295001, CLp=1.16036774, faces=76128
- `total_with_tips`: CDp=0.02295001, CLp=1.16036774, faces=115168

## Largest primary span bin

`eta=0.100-0.125` CDp=0.00114578, faces=1920

Outputs: `pressure_patch_summary.csv`, `pressure_spanwise_bins.csv`, `pressure_chordwise_bins.csv`, `pressure_region_exclusion_checks.csv`, `top_pressure_faces.csv`.
