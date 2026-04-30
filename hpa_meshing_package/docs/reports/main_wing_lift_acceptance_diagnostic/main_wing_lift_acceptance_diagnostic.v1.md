# Main Wing Lift Acceptance Diagnostic v1

This report reads existing solver-smoke artifacts only; it does not execute SU2.

- diagnostic_status: `lift_deficit_observed`
- hpa_standard_velocity_mps: `6.5`
- minimum_acceptable_cl: `1.0`
- production_default_changed: `False`

## Selected Solver Report

- `report_path`: `/Volumes/Samsung SSD/hpa-mdo/hpa_meshing_package/docs/reports/main_wing_openvsp_reference_solver_smoke_probe_iter80/main_wing_real_solver_smoke_probe.v1.json`
- `reference_policy`: `openvsp_geometry_derived`
- `runtime_max_iterations`: `80`
- `final_iteration`: `79`
- `convergence_gate_status`: `fail`
- `convergence_comparability_level`: `not_comparable`
- `coefficient_stability_status`: `pass`
- `final_coefficients`: `{"cl": 0.263161913, "cd": 0.02496911575, "cm": -0.2096803732, "cm_axis": "CMy"}`
- `su2_handoff_path`: `/Volumes/Samsung SSD/hpa-mdo/hpa_meshing_package/docs/reports/main_wing_openvsp_reference_su2_handoff_probe/artifacts/su2_handoff.json`
- `su2_handoff_path_source`: `committed_openvsp_reference_su2_handoff_probe`
- `solver_report_su2_handoff_path`: `/Volumes/Samsung SSD/hpa-mdo/hpa_meshing_package/.tmp/runs/main_wing_openvsp_reference_su2_handoff_probe_iter80/artifacts/su2/alpha_0_real_main_wing_openvsp_reference_probe/su2_handoff.json`

## Panel Reference

- `panel_reference_status`: `panel_reference_available`
- `alpha_deg`: `0`
- `cltot`: `1.28765`
- `cdtot`: `0.0450681`
- `velocity_mps`: `6.5`
- `lift_acceptance_status`: `pass`

## Flow And Reference

- `velocity_mps`: `6.5`
- `density_kgpm3`: `1.225`
- `alpha_deg`: `0`
- `flow_conditions_source_label`: `hpa_standard_6p5_mps`
- `ref_area_m2`: `35.175`
- `ref_length_m`: `1.0425`
- `reference_geometry_status`: `warn`
- `declared_vs_openvsp_area_relative_error`: `0.0149254`

## Lift Metrics

- `cl`: `0.263162`
- `minimum_acceptable_cl_exclusive`: `1`
- `dynamic_pressure_pa`: `25.8781`
- `reference_area_m2`: `35.175`
- `observed_lift_n`: `239.547`
- `lift_at_minimum_acceptable_cl_n`: `910.263`
- `observed_cl_to_minimum_ratio`: `0.263162`
- `cl_shortfall_to_minimum`: `0.736838`

## Lift Gap Diagnostics

- `selected_su2_cl`: `0.263162`
- `vspaero_panel_cl`: `1.28765`
- `minimum_acceptable_cl`: `1`
- `cl_delta_panel_minus_su2`: `1.02448`
- `panel_to_su2_cl_ratio`: `4.89298`
- `panel_reference_passes_cl_gate`: `True`
- `su2_smoke_passes_cl_gate`: `False`
- `panel_vs_su2_status`: `panel_supports_expected_lift_su2_low`

## Root Cause Candidates

- `su2_route_lift_deficit_not_explained_by_operating_alpha_alone`: `high`
- `solver_not_converged`: `high`
- `mesh_quality_or_dual_control_volume_pathology`: `high`
- `reference_area_normalization`: `low`

## Engineering Flags

- `main_wing_cl_below_expected_lift`
- `alpha_zero_operating_lift_not_demonstrated`
- `solver_not_converged`
- `reference_geometry_warn`
- `mesh_quality_warning_present`
- `reference_area_delta_too_small_to_explain_lift_deficit`
- `vspaero_panel_cl_gt_one_while_su2_low`
- `panel_to_su2_cl_ratio_above_four`

## Engineering Assessment

- This diagnostic reads existing solver-smoke artifacts only and does not execute SU2.
- Main-wing convergence acceptance at the HPA standard flow requires CL > 1.0.
- The selected current-route solver smoke ends at CL=0.263162, which is below the required main-wing lift margin.
- The selected SU2 handoff is an alpha=0 case, so it is a route smoke point, not proof that the operational trim/angle condition can carry the aircraft.
- The declared-vs-OpenVSP reference-area delta is only warn-level; by itself it is far too small to explain a CL below 1.
- Mesh-quality warnings remain relevant for convergence and coefficient trust, but the low-lift finding should first be separated from alpha/trim provenance.
- Because the VSPAERO panel baseline is already above CL=1 at the same nominal alpha=0 condition, alpha=0 alone is not a satisfactory explanation for the current SU2 CL deficit.
- The panel/SU2 CL ratio is about 4.89x, so force-marker ownership, boundary conditions, mesh quality, and solver state should be checked before spending a larger run as a convergence test.

## Next Actions

- `run_bounded_main_wing_alpha_trim_sanity_probe_without_changing_default`
- `extract_openvsp_main_wing_incidence_twist_camber_provenance`
- `audit_su2_force_markers_bc_and_reference_against_vspaero_panel`
- `inspect_main_wing_mesh_quality_before_larger_solver_budget`
- `resolve_reference_moment_origin_before_final_force_claims`

## Limitations

- This diagnostic cannot identify a converged lift curve without a bounded alpha or trim sweep.
- A low alpha=0 CL does not prove the aircraft cannot trim; it proves this route point cannot be accepted as converged main-wing evidence.
- Reference and mesh-quality warnings still need separate closure before CFD promotion.
