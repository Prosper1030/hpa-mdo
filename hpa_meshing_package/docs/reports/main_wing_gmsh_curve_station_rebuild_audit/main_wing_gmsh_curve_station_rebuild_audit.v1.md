# Main Wing Gmsh Curve Station Rebuild Audit v1

This report compares Gmsh candidate curve length against VSP3 section profile scale only.

- curve_station_rebuild_status: `curve_tags_match_vsp3_section_profile_scale`
- gmsh_defect_entity_trace_path: `/Volumes/Samsung SSD/hpa-mdo/hpa_meshing_package/docs/reports/main_wing_gmsh_defect_entity_trace/main_wing_gmsh_defect_entity_trace.v1.json`
- source_vsp3_path: `/Volumes/Samsung SSD/hpa-mdo/hpa_meshing_package/docs/reports/main_wing_real_mesh_handoff_probe/artifacts/real_mesh_probe/artifacts/providers/esp_rebuilt/esp_runtime/main_wing.vsp3`
- relative_length_tolerance: `0.05`
- production_default_changed: `False`

## Match Summary

- `curve_match_count`: `2`
- `matched_curve_tags`: `[36, 50]`
- `all_within_tolerance`: `True`
- `max_abs_relative_length_delta`: `0.0223049`

## Curve Matches

- `{"curve_tag": 36, "defect_station_y_m": -10.5, "source_section_index": 3, "station_chord_m": 1.0399999999999998, "observed_curve_length_m": 2.1362404645138326, "vsp3_normalized_profile_perimeter": 2.0747792637040368, "expected_curve_length_m": 2.157770434252198, "relative_length_delta": -0.009977877811560048, "within_tolerance": true, "candidate_curve": {"tag": 36, "length": 2.1362404645138326, "owner_surface_tags": [12, 13], "bbox": {"x_min": 0.05732893904509555, "y_min": -10.50000009866688, "z_min": 0.28585353041770695, "x_max": 1.0864346067220623, "y_max": -10.499999898666882, "z_max": 0.4629404481756138}}, "vsp3_profile": {"source_section_index": 3, "upper_point_count": 49, "lower_point_count": 49, "normalized_profile_perimeter": 2.0747792637040368}}`
- `{"curve_tag": 50, "defect_station_y_m": 13.5, "source_section_index": 4, "station_chord_m": 0.83, "observed_curve_length_m": 1.6836563472151995, "vsp3_normalized_profile_perimeter": 2.0747792637040368, "expected_curve_length_m": 1.7220667888743504, "relative_length_delta": -0.022304850141299286, "within_tolerance": true, "candidate_curve": {"tag": 50, "length": 1.6836563472151995, "owner_surface_tags": [19, 20], "bbox": {"x_min": 0.11803793541093971, "y_min": 13.49999989828599, "z_min": 0.5050673922348748, "x_max": 0.9331111579345286, "y_max": 13.50000009828599, "z_max": 0.6446557874935075}}, "vsp3_profile": {"source_section_index": 4, "upper_point_count": 49, "lower_point_count": 49, "normalized_profile_perimeter": 2.0747792637040368}}`

## Engineering Findings

- `curve_tags_match_vsp3_section_profile_scale`
- `curve_tags_are_station_airfoil_loop_candidates`

## Blocking Reasons

- none

## Next Actions

- `build_minimal_openvsp_section_station_topology_fixture`
- `decide_station_seam_repair_before_solver_iteration_budget`
- `preserve_curve_36_50_as_real_route_blocker_evidence`

## Limitations

- This audit compares Gmsh curve length to VSP3 airfoil-profile scale only; it does not project mesh nodes back to OpenVSP parameters.
- A profile-scale match supports station-loop provenance, but it is still route-risk evidence rather than a geometry repair.
- No SU2 solver execution or convergence assessment is performed by this report.
