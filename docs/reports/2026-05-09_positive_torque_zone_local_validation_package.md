# Positive Torque-Zone Local FEM / Coupon Validation Package

Verdict: `positive_zone_ready_for_local_FEM_and_coupon_definition_not_margin_pass`
FEM margin status: `not_run`. No FEM margin is claimed.

## Selected Closure Basis

- Rib / rear-spar basis: `eps_balsa_cap_hybrid_10mm` / `bounded_65pct_screening`.
- Bounded physical twist: `2.070316` deg.
- Direct spar-pair stress-test: `3.449294` deg; status `above_bound_conservative_stress_test`.
- Final CG / rebalance: `0.75` m / `0.079276` m.

## Positive Zone

- Active ribs: R067 / R068 / R069.
- Active bays: B066 / B067 / B068 / B069.
- Boundary ribs for local model: R066 / R067 / R068 / R069 / R070.
- Critical station: `R068` at y=`2.327757` m.

## Critical Load Row

- Main lift Fz: `21.202169` N.
- Kernel torque My: `-12.715548` N*m.
- Local torque couple main/rear Fz: `-23.839355` / `23.839355` N.
- Local total main/rear Fz: `-4.222466` / `23.552825` N.

## Load Path

- `aero_lift_owner`: Final closure spanload supplies vertical lift. The current kernel places lift on the main spar line; the local model applies it at main collar/rib web entry points as a conservative load-owner basis.
- `aero_torque_owner`: Span-axis aerodynamic torque is converted from kernel My into a main/rear vertical force couple at each collar: F=M/d.
- `rib_cap_shear_transfer`: Balsa/cap faces transfer rib web shear between skin, main collar, rear collar, and cap strip. EPS is shape support only.
- `bond_collar_tube_wall`: Adhesive and collar transfer shear/peel/bearing into main and rear spar tubes; tube walls must clear bearing, local crush, and ovalization.

## Coupon Matrix

- `C01_eps_balsa_cap_shear_transfer`: EPS+balsa cap shear transfer (in-plane shear / diagonal shear); status `not_tested`.
- `C02_main_spar_bond_shear`: rib-to-main-spar bond shear (lap/shear with local collar load introduction); status `not_tested`.
- `C03_rear_spar_bond_shear`: rib-to-rear-spar bond shear (lap/shear with torque-couple load direction); status `not_tested`.
- `C04_bond_peel`: peel (peel / mixed-mode opening); status `not_tested`.
- `C05_collar_bearing`: collar bearing (bearing/compression through collar tab); status `not_tested`.
- `C06_tube_wall_crush_ovalization`: local tube wall crushing / ovalization (radial crush plus torque-couple vertical load); status `not_tested`.
- `C07_skin_sag_shape_keeping_panel`: 0.30 m bay skin sag / shape keeping (pressure/handling load panel deflection); status `not_tested`.

## Missing Data

- `adhesive_shear_allowable_pa`: supplier_or_coupon_missing; required for rib-to-spar bond shear.
- `adhesive_peel_allowable_pa`: supplier_or_coupon_missing; required for bond peel / mixed-mode opening.
- `bondline_width_thickness_fillet`: geometry_missing; required for bond shear/peel stress extraction.
- `collar_material_thickness_contact_width`: geometry_and_allowable_missing; required for collar bearing and tab load transfer.
- `spar_tube_od_wall_material`: supplier_or_design_missing; required for collar bearing and local tube wall crush/ovalization.
- `balsa_cap_face_properties`: supplier_or_coupon_missing; required for EPS+balsa cap shear transfer.
- `eps_core_properties`: supplier_missing_for_shape_only_role; required for shape support and process repeatability.
- `skin_material_thickness_attachment`: design_missing; required for 0.30 m bay skin sag / shape keeping.

## Artifacts

- `station_manifest_csv`: `/Volumes/Samsung SSD/hpa-mdo/output/current_pathfinder_positive_torque_zone_validation/positive_zone_station_manifest.csv`
- `bay_manifest_csv`: `/Volumes/Samsung SSD/hpa-mdo/output/current_pathfinder_positive_torque_zone_validation/positive_zone_bay_manifest.csv`
- `load_decomposition_csv`: `/Volumes/Samsung SSD/hpa-mdo/output/current_pathfinder_positive_torque_zone_validation/positive_zone_load_decomposition.csv`
- `coupon_matrix_csv`: `/Volumes/Samsung SSD/hpa-mdo/output/current_pathfinder_positive_torque_zone_validation/positive_zone_coupon_matrix.csv`
- `missing_data_register_csv`: `/Volumes/Samsung SSD/hpa-mdo/output/current_pathfinder_positive_torque_zone_validation/positive_zone_missing_data_register.csv`
- `apdl_skeleton`: `/Volumes/Samsung SSD/hpa-mdo/output/current_pathfinder_positive_torque_zone_validation/positive_zone_local_fem_skeleton.mac`
- `package_json`: `/Volumes/Samsung SSD/hpa-mdo/output/current_pathfinder_positive_torque_zone_validation/positive_zone_local_validation_package.json`

## Next Blocker

supplier/coupon allowables and collar/tube-wall detail are still missing; do not export a FEM/APDL margin package until these values replace guarded placeholders

## Claim Boundary

This package validates the local load path for the already selected screening-closed hybrid rib basis. It does not retune full-wing twist and does not certify hardware.
