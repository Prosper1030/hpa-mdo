# Main Wing Station-Seam Side-Aware Metadata Repair Probe v1

This report tests bounded in-memory OCCT metadata repair against the side-aware station-seam candidate without writing repaired geometry.

- metadata_repair_status: `side_aware_station_metadata_repair_not_recovered`
- side_aware_brep_validation_probe_path: `docs/reports/main_wing_station_seam_side_aware_brep_validation_probe/main_wing_station_seam_side_aware_brep_validation_probe.v1.json`
- pcurve_residual_diagnostic_path: `docs/reports/main_wing_station_seam_side_aware_pcurve_residual_diagnostic/main_wing_station_seam_side_aware_pcurve_residual_diagnostic.v1.json`
- candidate_step_path: `/Volumes/Samsung SSD/hpa-mdo/hpa_meshing_package/docs/reports/main_wing_station_seam_side_aware_parametrization_probe/side_aware_profile_parametrization_single_rule/candidate_raw_dump.stp`
- production_default_changed: `False`

## Residual Context

- `diagnostic_status`: `side_aware_station_pcurve_residuals_below_tolerance_but_shape_analysis_flags_fail`
- `edge_face_residual_count`: `12`
- `sampled_edge_face_count`: `12`
- `max_sample_distance_m`: `0.0`
- `max_sample_distance_over_edge_tolerance`: `0.0`
- `shape_analysis_flag_failure_count`: `12`
- `residual_exceeds_edge_tolerance_count`: `0`
- `unbounded_pcurve_domain_count`: `12`
- `pcurve_missing_count`: `0`

## SameParameter Attempt Summary

- `attempt_count`: `5`
- `tolerances_evaluated`: `[1e-07, 1e-06, 1e-05, 0.0001, 0.001]`
- `recovered_attempt_count`: `0`
- `first_recovered_tolerance`: `-`

## ShapeFix Attempt Summary

- `attempt_count`: `25`
- `tolerances_evaluated`: `[1e-07, 1e-06, 1e-05, 0.0001, 0.001]`
- `recovered_attempt_count`: `0`
- `first_recovered_tolerance`: `-`
- `operations_evaluated`: `["fix_reversed_2d_then_same_parameter", "fix_same_parameter_edge", "fix_same_parameter_edge_face", "fix_vertex_tolerance_then_same_parameter", "remove_add_pcurve_then_same_parameter"]`
- `first_recovered_operation`: `-`

## Target Edges

- `{"curve_id": 7, "edge_index": 7, "face_ids": [2, 3]}`
- `{"curve_id": 28, "edge_index": 28, "face_ids": [9, 10]}`
- `{"curve_id": 36, "edge_index": 36, "face_ids": [12, 13]}`
- `{"curve_id": 50, "edge_index": 50, "face_ids": [19, 20]}`
- `{"curve_id": 55, "edge_index": 55, "face_ids": [22, 23]}`
- `{"curve_id": 62, "edge_index": 62, "face_ids": [29, 30]}`

## Engineering Findings

- `side_aware_station_metadata_repair_evaluated`
- `side_aware_station_target_pcurves_are_present`
- `side_aware_breplib_same_parameter_not_recovered`
- `side_aware_shape_fix_not_recovered`
- `side_aware_sampled_residual_zero_but_metadata_repair_not_recovered`
- `side_aware_export_pcurve_rebuild_needed`

## Blocking Reasons

- `side_aware_station_metadata_repair_not_recovered`
- `side_aware_candidate_mesh_handoff_not_run`

## Next Actions

- `prototype_side_aware_station_pcurve_rewrite_or_export_metadata_builder`
- `avoid_more_generic_same_parameter_shape_fix_sweeps`
- `do_not_advance_to_solver_budget_until_station_metadata_gate_changes`

## Limitations

- This probe evaluates bounded in-memory OCCT metadata repair only and writes no repaired STEP.
- It does not change production defaults or promote the side-aware candidate to mesh handoff.
- It does not run Gmsh volume mesh generation, SU2_CFD, CL acceptance, or convergence checks.
- Recovery requires target station-edge PCurve, same-parameter, curve-3D-with-PCurve, and vertex-tolerance checks to pass.
- A low sampled PCurve residual is recorded as context only; it is not a mesh-readiness pass.
