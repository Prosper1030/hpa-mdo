# Main Wing Station Seam Side-Aware Projected PCurve Builder Probe v1

- status: `side_aware_station_projected_pcurve_builder_partial`
- production_default_changed: `False`
- candidate_step_path: `/Volumes/Samsung SSD/hpa-mdo/hpa_meshing_package/docs/reports/main_wing_station_seam_side_aware_parametrization_probe/side_aware_profile_parametrization_single_rule/candidate_raw_dump.stp`
- target_edge_count: `6`
- strategies: `geomprojlib_curve2d_update_edge_then_same_parameter, sampled_surface_project_interpolate_update_edge_then_same_parameter, sampled_surface_project_approx_update_edge_then_same_parameter`
- projected_pcurve_built_face_count: `36`
- endpoint_orientation_pass_face_count: `36`
- best_passed_face_count: `0`
- max_projection_distance_m: `1.8343894894033213e-15`

## Engineering Findings

- `side_aware_projected_pcurve_builder_evaluated`
- `upstream_bounded_pcurve_builder_not_recovered`
- `projected_or_sampled_pcurves_materialized_in_memory`
- `projected_endpoint_orientation_gate_passed`
- `projected_sampled_geometry_residuals_within_projection_tolerance`
- `shape_analysis_gate_still_fails_after_projected_or_sampled_pcurves`
- `same_parameter_flags_are_not_shape_analysis_truth_source`

## Blocking Reasons

- `side_aware_station_projected_pcurve_builder_not_recovered`
- `side_aware_candidate_mesh_handoff_not_run`

## Next Actions

- `move_repair_upstream_to_section_parametrization_or_export_pcurve_generation`
- `do_not_advance_to_mesh_until_shape_analysis_gate_passes`
- `use_projected_pcurve_probe_as_negative_control_for_future_export_changes`

## Limitations

- This probe edits topology metadata in memory only; it does not export a repaired STEP.
- A projected or sampled PCurve is not accepted unless the full ShapeAnalysis gate passes.
- SameParameter/SameRange flags are recorded as diagnostics only, not as pass criteria.
