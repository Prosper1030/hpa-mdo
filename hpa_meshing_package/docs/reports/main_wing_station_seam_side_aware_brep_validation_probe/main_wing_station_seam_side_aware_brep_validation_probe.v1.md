# Main Wing Station Seam Side-Aware BRep Validation Probe v1

This report validates station-y BRep/PCurve checks on the side-aware candidate STEP without replaying old curve or surface tags.

- probe_status: `side_aware_candidate_station_brep_edges_suspect`
- side_aware_parametrization_probe_path: `docs/reports/main_wing_station_seam_side_aware_parametrization_probe/main_wing_station_seam_side_aware_parametrization_probe.v1.json`
- candidate_step_path: `docs/reports/main_wing_station_seam_side_aware_parametrization_probe/side_aware_profile_parametrization_single_rule/candidate_raw_dump.stp`
- target_station_y_m: `[-10.5, 13.5]`
- station_tolerance_m: `0.0001`
- production_default_changed: `False`
- upstream_validation_schema: `main_wing_station_seam_profile_resample_brep_validation_probe.v1`

## Target Selection

- `{"selection_mode": "station_y_geometry_on_candidate_step", "source_fixture_tags_replayed": false, "station_tolerance_m": 0.0001, "target_station_y_m": [-10.5, 13.5], "imported_entity_count": 1, "volume_count": 1, "surface_count": 32, "model_bbox": [-0.004617172251426, -16.5000001, -0.06803684311580001, 1.302329369, 16.5000001, 0.8352291747389999], "selected_curve_tags": [7, 28, 36, 50, 55, 62], "selected_surface_tags": [2, 3, 9, 10, 12, 13, 19, 20, 22, 23, 29, 30], "station_edge_groups": [{"station_y_m": -10.5, "candidate_curve_tags": [36, 55, 7], "owner_surface_tags": [2, 3, 12, 13, 22, 23], "curve_count": 3, "curve_records": [{"candidate_curve_tag": 36, "length_3d_m": 2.136130527696136, "owner_surface_tags": [12, 13], "bbox": {"x_min": 0.05722226769792526, "y_min": -10.5000001, "z_min": 0.28585353045399997, "x_max": 1.0864346068600002, "y_max": -10.4999999, "z_max": 0.463075787146}}, {"candidate_curve_tag": 55, "length_3d_m": 0.011309738135821127, "owner_surface_tags": [22, 23], "bbox": {"x_min": 1.08643440686, "y_min": -10.5000001, "z_min": 0.283554501375, "x_max": 1.0961382614200001, "y_max": -10.4999999, "z_max": 0.289364113125}}, {"candidate_curve_tag": 7, "length_3d_m": 0.010151388133646745, "owner_surface_tags": [2, 3], "bbox": {"x_min": 1.0862504355, "y_min": -10.5000001, "z_min": 0.283554501375, "x_max": 1.0961382614200001, "y_max": -10.4999999, "z_max": 0.285853730454}}]}, {"station_y_m": 13.5, "candidate_curve_tags": [50, 62, 28], "owner_surface_tags": [9, 10, 19, 20, 29, 30], "curve_count": 3, "curve_records": [{"candidate_curve_tag": 50, "length_3d_m": 1.6616134883216807, "owner_surface_tags": [19, 20], "bbox": {"x_min": 0.11774495961260713, "y_min": 13.4999999, "z_min": 0.5085566457220001, "x_max": 0.919486528622, "y_max": 13.5000001, "z_max": 0.644281074969}}, {"candidate_curve_tag": 62, "length_3d_m": 0.030410893329204353, "owner_surface_tags": [29, 30], "bbox": {"x_min": 0.9194863286220001, "y_min": 13.4999999, "z_min": 0.501434463583, "x_max": 0.947083385548, "y_max": 13.5000001, "z_max": 0.514211044952}}, {"candidate_curve_tag": 28, "length_3d_m": 0.028928371604672883, "owner_surface_tags": [9, 10], "bbox": {"x_min": 0.919045261137, "y_min": 13.4999999, "z_min": 0.501434463583, "x_max": 0.947083385548, "y_max": 13.5000001, "z_max": 0.508556845722}}]}]}`

## Hotspot Summary

- `collector_status`: `captured`
- `hotspot_status`: `captured`
- `shape_valid_default`: `True`
- `shape_valid_exact`: `True`
- `scale_to_output_units`: `1.0`
- `selected_curve_tags`: `[7, 28, 36, 50, 55, 62]`
- `selected_surface_tags`: `[2, 3, 9, 10, 12, 13, 19, 20, 22, 23, 29, 30]`
- `station_edge_check_count`: `6`
- `face_check_count`: `12`

## Station Edge Checks

- `{"station_y_m": -10.5, "candidate_step_curve_tag": 7, "candidate_step_edge_index": 7, "owner_surface_tags": [2, 3], "ancestor_face_ids": [2, 3], "gmsh_length_3d_m": 0.010151388133646745, "edge_length_3d_m": 0.010151388133646745, "length_relative_delta": 0.0, "match_score": 0.0, "pcurve_presence_complete": true, "curve3d_with_pcurve_consistent": false, "same_parameter_by_face_ok": false, "vertex_tolerance_by_face_ok": false, "pcurve_range_matches_edge_range": true, "pcurve_checks_complete": false, "same_parameter_flag": true, "same_range_flag": true, "brep_valid_default": true, "brep_valid_exact": true}`
- `{"station_y_m": 13.5, "candidate_step_curve_tag": 28, "candidate_step_edge_index": 28, "owner_surface_tags": [9, 10], "ancestor_face_ids": [9, 10], "gmsh_length_3d_m": 0.028928371604672883, "edge_length_3d_m": 0.028928371604672883, "length_relative_delta": 0.0, "match_score": 0.0, "pcurve_presence_complete": true, "curve3d_with_pcurve_consistent": false, "same_parameter_by_face_ok": false, "vertex_tolerance_by_face_ok": false, "pcurve_range_matches_edge_range": true, "pcurve_checks_complete": false, "same_parameter_flag": true, "same_range_flag": true, "brep_valid_default": true, "brep_valid_exact": true}`
- `{"station_y_m": -10.5, "candidate_step_curve_tag": 36, "candidate_step_edge_index": 36, "owner_surface_tags": [12, 13], "ancestor_face_ids": [12, 13], "gmsh_length_3d_m": 2.136130527696136, "edge_length_3d_m": 2.136130527696136, "length_relative_delta": 0.0, "match_score": 0.0, "pcurve_presence_complete": true, "curve3d_with_pcurve_consistent": false, "same_parameter_by_face_ok": false, "vertex_tolerance_by_face_ok": false, "pcurve_range_matches_edge_range": true, "pcurve_checks_complete": false, "same_parameter_flag": true, "same_range_flag": true, "brep_valid_default": true, "brep_valid_exact": true}`
- `{"station_y_m": 13.5, "candidate_step_curve_tag": 50, "candidate_step_edge_index": 50, "owner_surface_tags": [19, 20], "ancestor_face_ids": [19, 20], "gmsh_length_3d_m": 1.6616134883216807, "edge_length_3d_m": 1.6616134883216807, "length_relative_delta": 0.0, "match_score": 0.0, "pcurve_presence_complete": true, "curve3d_with_pcurve_consistent": false, "same_parameter_by_face_ok": false, "vertex_tolerance_by_face_ok": false, "pcurve_range_matches_edge_range": true, "pcurve_checks_complete": false, "same_parameter_flag": true, "same_range_flag": true, "brep_valid_default": true, "brep_valid_exact": true}`
- `{"station_y_m": -10.5, "candidate_step_curve_tag": 55, "candidate_step_edge_index": 55, "owner_surface_tags": [22, 23], "ancestor_face_ids": [22, 23], "gmsh_length_3d_m": 0.011309738135821127, "edge_length_3d_m": 0.011309738135821127, "length_relative_delta": 0.0, "match_score": 0.0, "pcurve_presence_complete": true, "curve3d_with_pcurve_consistent": false, "same_parameter_by_face_ok": false, "vertex_tolerance_by_face_ok": false, "pcurve_range_matches_edge_range": true, "pcurve_checks_complete": false, "same_parameter_flag": true, "same_range_flag": true, "brep_valid_default": true, "brep_valid_exact": true}`
- `{"station_y_m": 13.5, "candidate_step_curve_tag": 62, "candidate_step_edge_index": 62, "owner_surface_tags": [29, 30], "ancestor_face_ids": [29, 30], "gmsh_length_3d_m": 0.030410893329204353, "edge_length_3d_m": 0.030410893329204353, "length_relative_delta": 0.0, "match_score": 0.0, "pcurve_presence_complete": true, "curve3d_with_pcurve_consistent": false, "same_parameter_by_face_ok": false, "vertex_tolerance_by_face_ok": false, "pcurve_range_matches_edge_range": true, "pcurve_checks_complete": false, "same_parameter_flag": true, "same_range_flag": true, "brep_valid_default": true, "brep_valid_exact": true}`

## Face Checks

- `{"candidate_step_face_tag": 2, "brep_valid_default": true, "brep_valid_exact": true, "wire_count": 1, "wire_order_all_ok": true, "wires_connected": true, "wires_closed": true, "wire_self_intersection_detected": false}`
- `{"candidate_step_face_tag": 3, "brep_valid_default": true, "brep_valid_exact": true, "wire_count": 1, "wire_order_all_ok": true, "wires_connected": true, "wires_closed": true, "wire_self_intersection_detected": false}`
- `{"candidate_step_face_tag": 9, "brep_valid_default": true, "brep_valid_exact": true, "wire_count": 1, "wire_order_all_ok": true, "wires_connected": true, "wires_closed": true, "wire_self_intersection_detected": false}`
- `{"candidate_step_face_tag": 10, "brep_valid_default": true, "brep_valid_exact": true, "wire_count": 1, "wire_order_all_ok": true, "wires_connected": true, "wires_closed": true, "wire_self_intersection_detected": false}`
- `{"candidate_step_face_tag": 12, "brep_valid_default": true, "brep_valid_exact": true, "wire_count": 1, "wire_order_all_ok": true, "wires_connected": true, "wires_closed": true, "wire_self_intersection_detected": false}`
- `{"candidate_step_face_tag": 13, "brep_valid_default": true, "brep_valid_exact": true, "wire_count": 1, "wire_order_all_ok": true, "wires_connected": true, "wires_closed": true, "wire_self_intersection_detected": false}`
- `{"candidate_step_face_tag": 19, "brep_valid_default": true, "brep_valid_exact": true, "wire_count": 1, "wire_order_all_ok": true, "wires_connected": true, "wires_closed": true, "wire_self_intersection_detected": false}`
- `{"candidate_step_face_tag": 20, "brep_valid_default": true, "brep_valid_exact": true, "wire_count": 1, "wire_order_all_ok": true, "wires_connected": true, "wires_closed": true, "wire_self_intersection_detected": false}`
- `{"candidate_step_face_tag": 22, "brep_valid_default": true, "brep_valid_exact": true, "wire_count": 1, "wire_order_all_ok": true, "wires_connected": true, "wires_closed": true, "wire_self_intersection_detected": false}`
- `{"candidate_step_face_tag": 23, "brep_valid_default": true, "brep_valid_exact": true, "wire_count": 1, "wire_order_all_ok": true, "wires_connected": true, "wires_closed": true, "wire_self_intersection_detected": false}`
- `{"candidate_step_face_tag": 29, "brep_valid_default": true, "brep_valid_exact": true, "wire_count": 1, "wire_order_all_ok": true, "wires_connected": true, "wires_closed": true, "wire_self_intersection_detected": false}`
- `{"candidate_step_face_tag": 30, "brep_valid_default": true, "brep_valid_exact": true, "wire_count": 1, "wire_order_all_ok": true, "wires_connected": true, "wires_closed": true, "wire_self_intersection_detected": false}`

## Engineering Findings

- `side_aware_candidate_brep_validation_report_captured`
- `side_aware_station_edges_geometrically_selected`
- `source_fixture_curve_surface_tags_not_replayed`
- `side_aware_station_edge_pcurves_are_present`
- `side_aware_station_edge_pcurve_consistency_checks_are_suspect`
- `side_aware_owner_faces_wires_are_closed_connected_and_ordered`
- `side_aware_candidate_still_not_mesh_ready`

## Blocking Reasons

- `side_aware_candidate_station_brep_pcurve_checks_suspect`
- `side_aware_candidate_mesh_handoff_not_run`

## Next Actions

- `repair_side_aware_candidate_pcurve_export_before_mesh_handoff`
- `inspect_side_aware_station_y_candidate_edges_in_occt`

## Limitations

- This probe validates the side-aware parametrization candidate STEP only; it does not change production defaults.
- Station targets are selected geometrically from candidate topology, not replayed from old fixture curve or surface tags.
- It reuses the shared station-y BRep collector; the side-aware schema prevents the artifact from being confused with the earlier uniform profile-resample candidate.
- It does not run Gmsh volume mesh generation, SU2_CFD, CL acceptance, or convergence checks.
- A side-aware candidate with valid gross topology is still not mesh-ready unless station-edge PCurve consistency passes.
