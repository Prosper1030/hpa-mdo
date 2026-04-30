# Main Wing Station-Seam Side-Aware PCurve Metadata Builder Probe v1

This report tests in-memory PCurve metadata construction strategies on the side-aware station-seam candidate without writing repaired geometry.

- metadata_builder_status: `side_aware_station_pcurve_metadata_builder_partial`
- side_aware_brep_validation_probe_path: `docs/reports/main_wing_station_seam_side_aware_brep_validation_probe/main_wing_station_seam_side_aware_brep_validation_probe.v1.json`
- metadata_repair_probe_path: `docs/reports/main_wing_station_seam_side_aware_metadata_repair_probe/main_wing_station_seam_side_aware_metadata_repair_probe.v1.json`
- candidate_step_path: `/Volumes/Samsung SSD/hpa-mdo/hpa_meshing_package/docs/reports/main_wing_station_seam_side_aware_parametrization_probe/side_aware_profile_parametrization_single_rule/candidate_raw_dump.stp`
- production_default_changed: `False`

## Baseline Summary

- `target_edge_count`: `6`
- `target_face_count`: `12`
- `pcurve_present_face_count`: `12`
- `bounded_pcurve_face_count`: `0`
- `same_parameter_pass_face_count`: `0`
- `curve3d_with_pcurve_pass_face_count`: `0`
- `vertex_tolerance_pass_face_count`: `0`
- `passed_face_count`: `0`
- `check_error_count`: `0`
- `all_station_metadata_checks_pass`: `False`

## Strategy Attempt Summary

- `attempt_count`: `4`
- `strategies_evaluated`: `["bounded_existing_pcurve_update_edge", "bounded_existing_pcurve_update_edge_and_vertex_params", "bounded_existing_pcurve_replace", "bounded_existing_pcurve_replace_and_vertex_params"]`
- `recovered_attempt_count`: `0`
- `first_recovered_strategy`: `-`
- `best_bounded_face_count`: `12`
- `best_passed_face_count`: `0`
- `partial_progress_observed`: `True`
- `attempt_summaries`: `[{"strategy": "bounded_existing_pcurve_update_edge", "target_edge_count": 6, "target_face_count": 12, "pcurve_present_face_count": 12, "bounded_pcurve_face_count": 12, "same_parameter_pass_face_count": 0, "curve3d_with_pcurve_pass_face_count": 0, "vertex_tolerance_pass_face_count": 0, "passed_face_count": 0, "check_error_count": 0, "all_station_metadata_checks_pass": false}, {"strategy": "bounded_existing_pcurve_update_edge_and_vertex_params", "target_edge_count": 6, "target_face_count": 12, "pcurve_present_face_count": 12, "bounded_pcurve_face_count": 12, "same_parameter_pass_face_count": 0, "curve3d_with_pcurve_pass_face_count": 0, "vertex_tolerance_pass_face_count": 0, "passed_face_count": 0, "check_error_count": 0, "all_station_metadata_checks_pass": false}, {"strategy": "bounded_existing_pcurve_replace", "target_edge_count": 6, "target_face_count": 12, "pcurve_present_face_count": 12, "bounded_pcurve_face_count": 12, "same_parameter_pass_face_count": 0, "curve3d_with_pcurve_pass_face_count": 0, "vertex_tolerance_pass_face_count": 0, "passed_face_count": 0, "check_error_count": 0, "all_station_metadata_checks_pass": false}, {"strategy": "bounded_existing_pcurve_replace_and_vertex_params", "target_edge_count": 6, "target_face_count": 12, "pcurve_present_face_count": 12, "bounded_pcurve_face_count": 12, "same_parameter_pass_face_count": 0, "curve3d_with_pcurve_pass_face_count": 0, "vertex_tolerance_pass_face_count": 0, "passed_face_count": 0, "check_error_count": 0, "all_station_metadata_checks_pass": false}]`

## Target Edges

- `{"curve_id": 7, "edge_index": 7, "face_ids": [2, 3]}`
- `{"curve_id": 28, "edge_index": 28, "face_ids": [9, 10]}`
- `{"curve_id": 36, "edge_index": 36, "face_ids": [12, 13]}`
- `{"curve_id": 50, "edge_index": 50, "face_ids": [19, 20]}`
- `{"curve_id": 55, "edge_index": 55, "face_ids": [22, 23]}`
- `{"curve_id": 62, "edge_index": 62, "face_ids": [29, 30]}`

## Engineering Findings

- `side_aware_pcurve_metadata_builder_evaluated`
- `upstream_same_parameter_shape_fix_repair_not_recovered`
- `unbounded_existing_pcurve_domain_observed`
- `bounded_pcurve_domains_observed_without_station_metadata_recovery`
- `projected_or_sampled_pcurve_builder_still_needed`
- `no_target_edge_face_pair_passed_full_metadata_gate`

## Blocking Reasons

- `side_aware_station_pcurve_metadata_builder_not_recovered`
- `side_aware_candidate_mesh_handoff_not_run`

## Next Actions

- `prototype_projected_or_sampled_pcurve_builder_with_vertex_orientation_gate`
- `avoid_claiming_mesh_handoff_readiness_from_bounded_pcurve_domain_only`
- `do_not_advance_to_solver_budget_until_station_metadata_gate_passes`

## Limitations

- This probe evaluates in-memory PCurve metadata construction only and writes no repaired STEP.
- It does not change production defaults or promote the side-aware candidate to mesh handoff.
- Bounding an existing PCurve domain is recorded as partial progress only unless all ShapeAnalysis gates pass.
- SameParameter/SameRange flags are not treated as proof; ShapeAnalysis_Edge checks are the route gate.
- It does not run Gmsh volume meshing, SU2_CFD, CL acceptance, or convergence checks.
