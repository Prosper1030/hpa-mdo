# Main Wing Station Seam Side-Aware PCurve Residual Diagnostic v1

This report samples 3D edge curves against their PCurves on owner faces for the side-aware candidate STEP.

- diagnostic_status: `side_aware_station_pcurve_residuals_below_tolerance_but_shape_analysis_flags_fail`
- side_aware_brep_validation_probe_path: `docs/reports/main_wing_station_seam_side_aware_brep_validation_probe/main_wing_station_seam_side_aware_brep_validation_probe.v1.json`
- candidate_step_path: `docs/reports/main_wing_station_seam_side_aware_parametrization_probe/side_aware_profile_parametrization_single_rule/candidate_raw_dump.stp`
- target_station_y_m: `[-10.5, 13.5]`
- sample_count: `23`
- production_default_changed: `False`

## Residual Summary

- `edge_face_residual_count`: `12`
- `sampled_edge_face_count`: `12`
- `shape_analysis_flag_failure_count`: `12`
- `pcurve_missing_count`: `0`
- `sample_error_count`: `0`
- `residual_exceeds_edge_tolerance_count`: `0`
- `unbounded_pcurve_domain_count`: `12`
- `max_sample_distance_m`: `0.0`
- `max_sample_distance_over_edge_tolerance`: `0.0`

## Edge Face Residuals

- `{"station_y_m": -10.5, "candidate_step_curve_tag": 7, "candidate_step_edge_index": 7, "candidate_step_face_tag": 2, "edge_found": true, "face_found": true, "pcurve_present": true, "shape_analysis_curve3d_with_pcurve": false, "shape_analysis_same_parameter": false, "shape_analysis_vertex_tolerance": false, "edge_tolerance_m": 1e-07, "first_vertex_tolerance_m": 1e-07, "last_vertex_tolerance_m": 1e-07, "max_vertex_tolerance_m": 1e-07, "curve3d_type": "Geom_BSplineCurve", "pcurve_type": "Geom2d_Line", "edge_range": [0.0, 1.0], "pcurve_edge_range": [0.0, 1.0], "curve3d_first_parameter": 0.0, "curve3d_last_parameter": 1.0, "pcurve_first_parameter": -2e+100, "pcurve_last_parameter": 2e+100, "sample_count": 23, "max_sample_distance_m": 0.0, "mean_sample_distance_m": 0.0, "start_sample_distance_m": 0.0, "end_sample_distance_m": 0.0, "max_sample_distance_over_edge_tolerance": 0.0}`
- `{"station_y_m": -10.5, "candidate_step_curve_tag": 7, "candidate_step_edge_index": 7, "candidate_step_face_tag": 3, "edge_found": true, "face_found": true, "pcurve_present": true, "shape_analysis_curve3d_with_pcurve": false, "shape_analysis_same_parameter": false, "shape_analysis_vertex_tolerance": false, "edge_tolerance_m": 1e-07, "first_vertex_tolerance_m": 1e-07, "last_vertex_tolerance_m": 1e-07, "max_vertex_tolerance_m": 1e-07, "curve3d_type": "Geom_BSplineCurve", "pcurve_type": "Geom2d_Line", "edge_range": [0.0, 1.0], "pcurve_edge_range": [0.0, 1.0], "curve3d_first_parameter": 0.0, "curve3d_last_parameter": 1.0, "pcurve_first_parameter": -2e+100, "pcurve_last_parameter": 2e+100, "sample_count": 23, "max_sample_distance_m": 0.0, "mean_sample_distance_m": 0.0, "start_sample_distance_m": 0.0, "end_sample_distance_m": 0.0, "max_sample_distance_over_edge_tolerance": 0.0}`
- `{"station_y_m": 13.5, "candidate_step_curve_tag": 28, "candidate_step_edge_index": 28, "candidate_step_face_tag": 9, "edge_found": true, "face_found": true, "pcurve_present": true, "shape_analysis_curve3d_with_pcurve": false, "shape_analysis_same_parameter": false, "shape_analysis_vertex_tolerance": false, "edge_tolerance_m": 1e-07, "first_vertex_tolerance_m": 1e-07, "last_vertex_tolerance_m": 1e-07, "max_vertex_tolerance_m": 1e-07, "curve3d_type": "Geom_BSplineCurve", "pcurve_type": "Geom2d_Line", "edge_range": [0.0, 1.0], "pcurve_edge_range": [0.0, 1.0], "curve3d_first_parameter": 0.0, "curve3d_last_parameter": 1.0, "pcurve_first_parameter": -2e+100, "pcurve_last_parameter": 2e+100, "sample_count": 23, "max_sample_distance_m": 0.0, "mean_sample_distance_m": 0.0, "start_sample_distance_m": 0.0, "end_sample_distance_m": 0.0, "max_sample_distance_over_edge_tolerance": 0.0}`
- `{"station_y_m": 13.5, "candidate_step_curve_tag": 28, "candidate_step_edge_index": 28, "candidate_step_face_tag": 10, "edge_found": true, "face_found": true, "pcurve_present": true, "shape_analysis_curve3d_with_pcurve": false, "shape_analysis_same_parameter": false, "shape_analysis_vertex_tolerance": false, "edge_tolerance_m": 1e-07, "first_vertex_tolerance_m": 1e-07, "last_vertex_tolerance_m": 1e-07, "max_vertex_tolerance_m": 1e-07, "curve3d_type": "Geom_BSplineCurve", "pcurve_type": "Geom2d_Line", "edge_range": [0.0, 1.0], "pcurve_edge_range": [0.0, 1.0], "curve3d_first_parameter": 0.0, "curve3d_last_parameter": 1.0, "pcurve_first_parameter": -2e+100, "pcurve_last_parameter": 2e+100, "sample_count": 23, "max_sample_distance_m": 0.0, "mean_sample_distance_m": 0.0, "start_sample_distance_m": 0.0, "end_sample_distance_m": 0.0, "max_sample_distance_over_edge_tolerance": 0.0}`
- `{"station_y_m": -10.5, "candidate_step_curve_tag": 36, "candidate_step_edge_index": 36, "candidate_step_face_tag": 12, "edge_found": true, "face_found": true, "pcurve_present": true, "shape_analysis_curve3d_with_pcurve": false, "shape_analysis_same_parameter": false, "shape_analysis_vertex_tolerance": false, "edge_tolerance_m": 1e-07, "first_vertex_tolerance_m": 1e-07, "last_vertex_tolerance_m": 1e-07, "max_vertex_tolerance_m": 1e-07, "curve3d_type": "Geom_BSplineCurve", "pcurve_type": "Geom2d_Line", "edge_range": [0.0, 1.0], "pcurve_edge_range": [0.0, 1.0], "curve3d_first_parameter": 0.0, "curve3d_last_parameter": 1.0, "pcurve_first_parameter": -2e+100, "pcurve_last_parameter": 2e+100, "sample_count": 23, "max_sample_distance_m": 0.0, "mean_sample_distance_m": 0.0, "start_sample_distance_m": 0.0, "end_sample_distance_m": 0.0, "max_sample_distance_over_edge_tolerance": 0.0}`
- `{"station_y_m": -10.5, "candidate_step_curve_tag": 36, "candidate_step_edge_index": 36, "candidate_step_face_tag": 13, "edge_found": true, "face_found": true, "pcurve_present": true, "shape_analysis_curve3d_with_pcurve": false, "shape_analysis_same_parameter": false, "shape_analysis_vertex_tolerance": false, "edge_tolerance_m": 1e-07, "first_vertex_tolerance_m": 1e-07, "last_vertex_tolerance_m": 1e-07, "max_vertex_tolerance_m": 1e-07, "curve3d_type": "Geom_BSplineCurve", "pcurve_type": "Geom2d_Line", "edge_range": [0.0, 1.0], "pcurve_edge_range": [0.0, 1.0], "curve3d_first_parameter": 0.0, "curve3d_last_parameter": 1.0, "pcurve_first_parameter": -2e+100, "pcurve_last_parameter": 2e+100, "sample_count": 23, "max_sample_distance_m": 0.0, "mean_sample_distance_m": 0.0, "start_sample_distance_m": 0.0, "end_sample_distance_m": 0.0, "max_sample_distance_over_edge_tolerance": 0.0}`
- `{"station_y_m": 13.5, "candidate_step_curve_tag": 50, "candidate_step_edge_index": 50, "candidate_step_face_tag": 19, "edge_found": true, "face_found": true, "pcurve_present": true, "shape_analysis_curve3d_with_pcurve": false, "shape_analysis_same_parameter": false, "shape_analysis_vertex_tolerance": false, "edge_tolerance_m": 1e-07, "first_vertex_tolerance_m": 1e-07, "last_vertex_tolerance_m": 1e-07, "max_vertex_tolerance_m": 1e-07, "curve3d_type": "Geom_BSplineCurve", "pcurve_type": "Geom2d_Line", "edge_range": [0.0, 1.0], "pcurve_edge_range": [0.0, 1.0], "curve3d_first_parameter": 0.0, "curve3d_last_parameter": 1.0, "pcurve_first_parameter": -2e+100, "pcurve_last_parameter": 2e+100, "sample_count": 23, "max_sample_distance_m": 0.0, "mean_sample_distance_m": 0.0, "start_sample_distance_m": 0.0, "end_sample_distance_m": 0.0, "max_sample_distance_over_edge_tolerance": 0.0}`
- `{"station_y_m": 13.5, "candidate_step_curve_tag": 50, "candidate_step_edge_index": 50, "candidate_step_face_tag": 20, "edge_found": true, "face_found": true, "pcurve_present": true, "shape_analysis_curve3d_with_pcurve": false, "shape_analysis_same_parameter": false, "shape_analysis_vertex_tolerance": false, "edge_tolerance_m": 1e-07, "first_vertex_tolerance_m": 1e-07, "last_vertex_tolerance_m": 1e-07, "max_vertex_tolerance_m": 1e-07, "curve3d_type": "Geom_BSplineCurve", "pcurve_type": "Geom2d_Line", "edge_range": [0.0, 1.0], "pcurve_edge_range": [0.0, 1.0], "curve3d_first_parameter": 0.0, "curve3d_last_parameter": 1.0, "pcurve_first_parameter": -2e+100, "pcurve_last_parameter": 2e+100, "sample_count": 23, "max_sample_distance_m": 0.0, "mean_sample_distance_m": 0.0, "start_sample_distance_m": 0.0, "end_sample_distance_m": 0.0, "max_sample_distance_over_edge_tolerance": 0.0}`
- `{"station_y_m": -10.5, "candidate_step_curve_tag": 55, "candidate_step_edge_index": 55, "candidate_step_face_tag": 22, "edge_found": true, "face_found": true, "pcurve_present": true, "shape_analysis_curve3d_with_pcurve": false, "shape_analysis_same_parameter": false, "shape_analysis_vertex_tolerance": false, "edge_tolerance_m": 1e-07, "first_vertex_tolerance_m": 1e-07, "last_vertex_tolerance_m": 1e-07, "max_vertex_tolerance_m": 1e-07, "curve3d_type": "Geom_BSplineCurve", "pcurve_type": "Geom2d_Line", "edge_range": [0.0, 1.0], "pcurve_edge_range": [0.0, 1.0], "curve3d_first_parameter": 0.0, "curve3d_last_parameter": 1.0, "pcurve_first_parameter": -2e+100, "pcurve_last_parameter": 2e+100, "sample_count": 23, "max_sample_distance_m": 0.0, "mean_sample_distance_m": 0.0, "start_sample_distance_m": 0.0, "end_sample_distance_m": 0.0, "max_sample_distance_over_edge_tolerance": 0.0}`
- `{"station_y_m": -10.5, "candidate_step_curve_tag": 55, "candidate_step_edge_index": 55, "candidate_step_face_tag": 23, "edge_found": true, "face_found": true, "pcurve_present": true, "shape_analysis_curve3d_with_pcurve": false, "shape_analysis_same_parameter": false, "shape_analysis_vertex_tolerance": false, "edge_tolerance_m": 1e-07, "first_vertex_tolerance_m": 1e-07, "last_vertex_tolerance_m": 1e-07, "max_vertex_tolerance_m": 1e-07, "curve3d_type": "Geom_BSplineCurve", "pcurve_type": "Geom2d_Line", "edge_range": [0.0, 1.0], "pcurve_edge_range": [0.0, 1.0], "curve3d_first_parameter": 0.0, "curve3d_last_parameter": 1.0, "pcurve_first_parameter": -2e+100, "pcurve_last_parameter": 2e+100, "sample_count": 23, "max_sample_distance_m": 0.0, "mean_sample_distance_m": 0.0, "start_sample_distance_m": 0.0, "end_sample_distance_m": 0.0, "max_sample_distance_over_edge_tolerance": 0.0}`
- `{"station_y_m": 13.5, "candidate_step_curve_tag": 62, "candidate_step_edge_index": 62, "candidate_step_face_tag": 29, "edge_found": true, "face_found": true, "pcurve_present": true, "shape_analysis_curve3d_with_pcurve": false, "shape_analysis_same_parameter": false, "shape_analysis_vertex_tolerance": false, "edge_tolerance_m": 1e-07, "first_vertex_tolerance_m": 1e-07, "last_vertex_tolerance_m": 1e-07, "max_vertex_tolerance_m": 1e-07, "curve3d_type": "Geom_BSplineCurve", "pcurve_type": "Geom2d_Line", "edge_range": [0.0, 1.0], "pcurve_edge_range": [0.0, 1.0], "curve3d_first_parameter": 0.0, "curve3d_last_parameter": 1.0, "pcurve_first_parameter": -2e+100, "pcurve_last_parameter": 2e+100, "sample_count": 23, "max_sample_distance_m": 0.0, "mean_sample_distance_m": 0.0, "start_sample_distance_m": 0.0, "end_sample_distance_m": 0.0, "max_sample_distance_over_edge_tolerance": 0.0}`
- `{"station_y_m": 13.5, "candidate_step_curve_tag": 62, "candidate_step_edge_index": 62, "candidate_step_face_tag": 30, "edge_found": true, "face_found": true, "pcurve_present": true, "shape_analysis_curve3d_with_pcurve": false, "shape_analysis_same_parameter": false, "shape_analysis_vertex_tolerance": false, "edge_tolerance_m": 1e-07, "first_vertex_tolerance_m": 1e-07, "last_vertex_tolerance_m": 1e-07, "max_vertex_tolerance_m": 1e-07, "curve3d_type": "Geom_BSplineCurve", "pcurve_type": "Geom2d_Line", "edge_range": [0.0, 1.0], "pcurve_edge_range": [0.0, 1.0], "curve3d_first_parameter": 0.0, "curve3d_last_parameter": 1.0, "pcurve_first_parameter": -2e+100, "pcurve_last_parameter": 2e+100, "sample_count": 23, "max_sample_distance_m": 0.0, "mean_sample_distance_m": 0.0, "start_sample_distance_m": 0.0, "end_sample_distance_m": 0.0, "max_sample_distance_over_edge_tolerance": 0.0}`

## Engineering Findings

- `side_aware_pcurve_residual_diagnostic_captured`
- `source_fixture_curve_surface_tags_not_replayed`
- `station_pcurve_residuals_sampled_on_candidate_step`
- `station_pcurve_sampled_geometric_residuals_within_edge_tolerance`
- `shape_analysis_flags_fail_despite_low_sampled_residual`
- `unbounded_line_pcurve_parameter_domain_observed`
- `side_aware_candidate_still_not_mesh_ready`

## Blocking Reasons

- `side_aware_station_shape_analysis_flags_still_block_mesh_handoff`
- `side_aware_candidate_mesh_handoff_not_run`

## Next Actions

- `test_side_aware_same_parameter_metadata_repair_before_mesh_handoff`
- `correlate_shape_analysis_flags_with_gmsh_volume_recovery_before_solver_budget`
- `avoid_solver_iteration_budget_until_station_metadata_gate_is_clean`

## Limitations

- This diagnostic samples existing side-aware candidate STEP PCurves; it does not change production defaults.
- Low sampled residual is diagnostic evidence only; it does not override failed ShapeAnalysis/SameParameter route gates.
- A sampled-clean PCurve residual report is not a CFD-ready or mesh-ready claim until BRep validation and mesh handoff pass.
- It does not run Gmsh volume meshing, SU2_CFD, CL acceptance, or convergence checks.
- Engineering acceptance still requires CL >= 1 under the HPA 6.5 m/s flow condition when solver evidence is evaluated.
