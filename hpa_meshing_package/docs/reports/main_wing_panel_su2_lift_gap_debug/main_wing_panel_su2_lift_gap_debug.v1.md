# Main Wing Panel/SU2 Lift Gap Debug v1

This report reads existing artifacts only; it does not execute SU2.

- debug_status: `gap_confirmed_debug_ready`
- hpa_standard_velocity_mps: `6.5`
- minimum_acceptable_cl: `1.0`
- production_default_changed: `False`

## Flow Reference Alignment

- `status`: `pass`
- `panel_sref_m2`: `35.175`
- `su2_ref_area_m2`: `35.175`
- `ref_area_relative_delta`: `0`
- `panel_cref_m`: `1.0425`
- `su2_ref_length_m`: `1.0425`
- `ref_length_relative_delta`: `0`
- `panel_velocity_mps`: `6.5`
- `su2_velocity_mps`: `6.5`
- `velocity_relative_delta`: `0`
- `panel_density_kgpm3`: `1.225`
- `su2_density_kgpm3`: `1.225`
- `density_relative_delta`: `0`
- `force_marker_flow_reference_status`: `pass`
- `force_marker_flow_reference_observed`: `{"velocity_mps": 6.5, "cfg_velocity_x_mps": 6.5, "ref_area_m2": 35.175, "cfg_ref_area_m2": 35.175, "ref_length_m": 1.0425, "cfg_ref_length_m": 1.0425, "wall_boundary_condition": "euler", "solver": "INC_NAVIER_STOKES"}`

## Panel Reference Decomposition

- `alpha_deg`: `0`
- `clo`: `-0.00274765`
- `clo_component_label`: `viscous_or_other_surface_integration_component`
- `cli`: `1.29039`
- `cli_component_label`: `inviscid_surface_integration_component`
- `cltot`: `1.28765`
- `cdtot`: `0.0450681`
- `cfztot`: `1.28765`
- `clwtot`: `1.28997`
- `cliw`: `1.29272`
- `cliw_component_label`: `wake_free_stream_induced_component`
- `source_semantics`: `OpenVSP VSPAERO source writes CLtot=CLi+CLo and labels CLi as inviscid, CLo as viscous, and CLiw/CLwtot as wake/free-stream induced output.`
- `inviscid_lift_fraction_of_cltot`: `1.00213`
- `interpretation`: `panel_lift_dominated_by_inviscid_component`

## SU2 Force Breakdown

- `forces_breakdown_status`: `available`
- `surface_names`: `["main_wing"]`
- `forces_breakdown_cl`: `0.263162`
- `selected_su2_cl`: `0.263162`
- `vspaero_panel_cl`: `1.28765`
- `panel_to_force_breakdown_cl_ratio`: `4.89298`
- `force_breakdown_marker_owned`: `True`
- `force_breakdown_matches_history_cl`: `True`
- `history_cl_delta_abs`: `8.7e-08`

## Boundary And Mesh

- `boundary.solver`: `INC_NAVIER_STOKES`
- `boundary.wall_boundary_condition`: `euler`
- `boundary.engineering_flags`: `["main_wing_solver_wall_bc_is_euler_smoke_not_viscous", "main_wing_reference_geometry_warn"]`
- `mesh.max_cv_face_area_aspect_ratio`: `377.909`
- `mesh.max_cv_sub_volume_ratio`: `13256.1`
- `mesh.mesh_quality_pathology_present`: `True`

## Engineering Findings

- `panel_su2_lift_gap_confirmed`
- `reference_normalization_not_primary_cause`
- `panel_lift_dominated_by_inviscid_component`
- `force_marker_ownership_not_primary_cause`
- `su2_force_breakdown_confirms_main_wing_low_cl`
- `su2_wall_bc_is_euler_smoke`
- `mesh_quality_pathology_present`
- `solver_not_converged`

## Primary Hypotheses

- `panel_su2_lifting_surface_semantics_or_geometry_mismatch`: `high`
- `mesh_quality_or_dual_control_volume_pathology`: `high`
- `solver_state_not_converged`: `medium`
- `reference_normalization_unlikely_primary_cause`: `low`

## Next Actions

- `compare_openvsp_panel_geometry_against_su2_mesh_normals_incidence_and_lifting_surface_semantics`
- `inspect_thin_sheet_wall_bc_against_vspaero_degengeom_lifting_surface_assumption`
- `localize_main_wing_su2_mesh_quality_hotspots_before_iteration_sweep`
- `defer_convergence_claim_until_source_backed_iteration_budget`

## Limitations

- This report ranks debug hypotheses from existing artifacts; it is not a CFD convergence result.
- VSPAERO panel evidence is a lower-order sanity baseline, not high-fidelity CFD truth.
- Do not describe the VSPAERO CLi column as a wake-induced term; source evidence labels it as inviscid.
- Solver execution remains separate from convergence.
