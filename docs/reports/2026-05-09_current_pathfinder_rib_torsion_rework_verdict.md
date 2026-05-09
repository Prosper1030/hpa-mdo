# Current Pathfinder Rib / Torsion Rework Verdict

Candidate: `current_avl_compromise_conservative_closed`
Verdict: `candidate_ready_for_local_FEM_and_coupon_before_FEM_package`
FEM/APDL package ready: `False`
Gate blockers: `['closure_rerun_not_package_ready', 'closure_rerun_elastic_twist_exceeds_bound', 'closure_rerun_bounded_twist_exceeds_bound', 'direct_spar_pair_stress_test_still_above_bound', 'missing_transition_or_control_station_contract', 'skin_sag_unknown_requires_test', 'bond_collar_spar_contact_needs_data', 'torque_critical_local_fem_required', 'hybrid_effective_gj_is_projection_only_not_closure_rerun']`

## Baseline Blocker

- Baseline rib/rear-spar: `balsa_sheet_3mm` / `bounded_50pct_screening`.
- Baseline direct / bounded twist: `5.413494` deg / `3.256324` deg.
- Screening bound: `3.000000` deg.
- Torque-critical y: `2.328` m; dominant source `aerodynamic_torque_only`.

## Selected Next Candidate

- Family / rear-spar participation: `eps_balsa_cap_hybrid_10mm` / `bounded_65pct_screening`.
- Effective GJ ratio vs balsa selected: `2.032971`.
- Projected direct / bounded twist: `2.662909` deg / `1.601756` deg.
- Rib mass: `5.365` kg, delta vs baseline `2.335` kg.
- CG status: `final_cg_screening_row_remains_available_with_rebalance`; required forward rebalance `0.079276` m on `56.0` kg.
- This is a local FEM/coupon candidate, not a FEM/APDL package pass.

## Closure Rerun Boundary

- Rerun status: `rerun_supplied`.
- Rerun verdict: `needs_aeroelastic_geometry_or_stiffness_rework`.
- Bounded twist status: `still_high`.
- Direct stress-test status: `still_above_screening_bound`.

## Detail Blockers

- Missing contract items: `['transport_joint', 'control_station', 'airfoil_transition', 'twist_transition']`.
- Skin sag statuses: `['unknown_requires_test', 'unknown_requires_test_torque_zone']`.
- Bond/collar statuses: `['needs_data', 'needs_data_torque_or_mandatory_zone']`.
- Local FEM torque-critical y: `2.328` m.
- Reinforcement zones: `[{'bay_ids': ['B066', 'B067', 'B068', 'B069'], 'recommended_action': 'Run local rib-spar-bond/collar FEM and include this as a hybrid reinforcement zone in the next stiffness sweep.', 'station_ids': ['R067', 'R068', 'R069'], 'y_end_m': 2.627757, 'y_start_m': 2.027757, 'zone_id': 'positive_torque_critical_hybrid_reinforcement_zone'}, {'bay_ids': ['B050', 'B051', 'B052', 'B053'], 'recommended_action': 'Run local rib-spar-bond/collar FEM and include this as a hybrid reinforcement zone in the next stiffness sweep.', 'station_ids': ['R051', 'R052', 'R053'], 'y_end_m': -2.027757, 'y_start_m': -2.627757, 'zone_id': 'negative_torque_critical_hybrid_reinforcement_zone'}]`.

## Required Before FEM/APDL Package

- hybrid rib cap/face/collar geometry at y≈2.328 m torque-critical zone
- rib-to-main/rear-spar bondline and collar/contact geometry
- tube-wall local bearing/crush/peel allowables or local FEM
- skin sag coupon/panel evidence for 0.30 m bays
- transport/control/airfoil/twist transition station manifest
- closure rerun with the selected effective stiffness model wired in

## Artifacts

- candidate trade CSV: `/Volumes/Samsung SSD/hpa-mdo/output/current_pathfinder_rib_torsion_rework_verdict/candidate_trade.csv`
- local FEM/coupon requirements: `/Volumes/Samsung SSD/hpa-mdo/output/current_pathfinder_rib_torsion_rework_verdict/local_fem_coupon_requirements.json`
- summary JSON: `/Volumes/Samsung SSD/hpa-mdo/output/current_pathfinder_rib_torsion_rework_verdict/rib_torsion_rework_verdict.json`

## Engineering Read

The next useful candidate is eps_balsa_cap_hybrid_10mm with bounded_65pct_screening. It projects direct and bounded twist below 3 deg with mass/CG carried, but it is not FEM/APDL-loadcase ready because the hybrid stiffness is projection-only and materialized bond/collar/skin sag/transition/local FEM data are still open: ['missing_transition_or_control_station_contract', 'skin_sag_unknown_requires_test', 'bond_collar_spar_contact_needs_data', 'torque_critical_local_fem_required']. Closure rerun status is rerun_supplied.
