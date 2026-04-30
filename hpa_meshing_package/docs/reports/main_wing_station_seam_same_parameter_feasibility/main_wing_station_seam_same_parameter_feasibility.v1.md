# Main Wing Station Seam Same-Parameter Feasibility v1

This report tests whether an in-memory OCCT same-parameter pass can recover the station seam pcurve checks.

- feasibility_status: `same_parameter_repair_not_recovered`
- brep_hotspot_probe_path: `/Volumes/Samsung SSD/hpa-mdo/hpa_meshing_package/docs/reports/main_wing_station_seam_brep_hotspot_probe/main_wing_station_seam_brep_hotspot_probe.v1.json`
- normalized_step_path: `/Volumes/Samsung SSD/hpa-mdo/hpa_meshing_package/docs/reports/main_wing_real_mesh_handoff_probe/artifacts/provider_geometry/artifacts/geometry_validation/artifacts/providers/esp_rebuilt/esp_runtime/normalized.stp`
- production_default_changed: `False`

## Baseline Summary

- `target_edge_count`: `2`
- `all_target_pcurves_present`: `True`
- `all_same_parameter_checks_pass`: `False`
- `all_curve3d_with_pcurve_checks_pass`: `False`
- `all_vertex_tolerance_checks_pass`: `False`

## Attempt Summary

- `attempt_count`: `5`
- `tolerances_evaluated`: `[1e-07, 1e-06, 1e-05, 0.0001, 0.001]`
- `recovered_attempt_count`: `0`
- `first_recovered_tolerance`: `-`

## Target Edges

- `{"curve_id": 36, "edge_index": 36, "face_ids": [12, 13]}`
- `{"curve_id": 50, "edge_index": 50, "face_ids": [19, 20]}`

## API Semantics

- `check_same_parameter`: `OCP ShapeAnalysis_Edge.CheckSameParameter returns False when 3D-curve to pcurve deviation exceeds edge tolerance.`
- `breplib_same_parameter_scope`: `BRepLib.SameParameter is evaluated in memory only in this report.`

## Baseline Checks

- `{"curve_id": 36, "edge_index": 36, "face_ids": [12, 13], "edge_found": true, "edge_tolerance": 1e-07, "same_parameter_flag": true, "same_range_flag": true, "face_checks": [{"face_id": 12, "face_found": true, "has_pcurve": true, "check_same_parameter": false, "check_curve3d_with_pcurve": false, "check_vertex_tolerance": false}, {"face_id": 13, "face_found": true, "has_pcurve": true, "check_same_parameter": false, "check_curve3d_with_pcurve": false, "check_vertex_tolerance": false}]}`
- `{"curve_id": 50, "edge_index": 50, "face_ids": [19, 20], "edge_found": true, "edge_tolerance": 1e-07, "same_parameter_flag": true, "same_range_flag": true, "face_checks": [{"face_id": 19, "face_found": true, "has_pcurve": true, "check_same_parameter": false, "check_curve3d_with_pcurve": false, "check_vertex_tolerance": false}, {"face_id": 20, "face_found": true, "has_pcurve": true, "check_same_parameter": false, "check_curve3d_with_pcurve": false, "check_vertex_tolerance": false}]}`

## Repair Attempts

- `{"tolerance": 1e-07, "recovered": false, "checks": [{"curve_id": 36, "edge_index": 36, "face_ids": [12, 13], "edge_found": true, "edge_tolerance": 1e-07, "same_parameter_flag": true, "same_range_flag": true, "face_checks": [{"face_id": 12, "face_found": true, "has_pcurve": true, "check_same_parameter": false, "check_curve3d_with_pcurve": false, "check_vertex_tolerance": false}, {"face_id": 13, "face_found": true, "has_pcurve": true, "check_same_parameter": false, "check_curve3d_with_pcurve": false, "check_vertex_tolerance": false}]}, {"curve_id": 50, "edge_index": 50, "face_ids": [19, 20], "edge_found": true, "edge_tolerance": 1e-07, "same_parameter_flag": true, "same_range_flag": true, "face_checks": [{"face_id": 19, "face_found": true, "has_pcurve": true, "check_same_parameter": false, "check_curve3d_with_pcurve": false, "check_vertex_tolerance": false}, {"face_id": 20, "face_found": true, "has_pcurve": true, "check_same_parameter": false, "check_curve3d_with_pcurve": false, "check_vertex_tolerance": false}]}]}`
- `{"tolerance": 1e-06, "recovered": false, "checks": [{"curve_id": 36, "edge_index": 36, "face_ids": [12, 13], "edge_found": true, "edge_tolerance": 1e-07, "same_parameter_flag": true, "same_range_flag": true, "face_checks": [{"face_id": 12, "face_found": true, "has_pcurve": true, "check_same_parameter": false, "check_curve3d_with_pcurve": false, "check_vertex_tolerance": false}, {"face_id": 13, "face_found": true, "has_pcurve": true, "check_same_parameter": false, "check_curve3d_with_pcurve": false, "check_vertex_tolerance": false}]}, {"curve_id": 50, "edge_index": 50, "face_ids": [19, 20], "edge_found": true, "edge_tolerance": 1e-07, "same_parameter_flag": true, "same_range_flag": true, "face_checks": [{"face_id": 19, "face_found": true, "has_pcurve": true, "check_same_parameter": false, "check_curve3d_with_pcurve": false, "check_vertex_tolerance": false}, {"face_id": 20, "face_found": true, "has_pcurve": true, "check_same_parameter": false, "check_curve3d_with_pcurve": false, "check_vertex_tolerance": false}]}]}`
- `{"tolerance": 1e-05, "recovered": false, "checks": [{"curve_id": 36, "edge_index": 36, "face_ids": [12, 13], "edge_found": true, "edge_tolerance": 1e-07, "same_parameter_flag": true, "same_range_flag": true, "face_checks": [{"face_id": 12, "face_found": true, "has_pcurve": true, "check_same_parameter": false, "check_curve3d_with_pcurve": false, "check_vertex_tolerance": false}, {"face_id": 13, "face_found": true, "has_pcurve": true, "check_same_parameter": false, "check_curve3d_with_pcurve": false, "check_vertex_tolerance": false}]}, {"curve_id": 50, "edge_index": 50, "face_ids": [19, 20], "edge_found": true, "edge_tolerance": 1e-07, "same_parameter_flag": true, "same_range_flag": true, "face_checks": [{"face_id": 19, "face_found": true, "has_pcurve": true, "check_same_parameter": false, "check_curve3d_with_pcurve": false, "check_vertex_tolerance": false}, {"face_id": 20, "face_found": true, "has_pcurve": true, "check_same_parameter": false, "check_curve3d_with_pcurve": false, "check_vertex_tolerance": false}]}]}`
- `{"tolerance": 0.0001, "recovered": false, "checks": [{"curve_id": 36, "edge_index": 36, "face_ids": [12, 13], "edge_found": true, "edge_tolerance": 1e-07, "same_parameter_flag": true, "same_range_flag": true, "face_checks": [{"face_id": 12, "face_found": true, "has_pcurve": true, "check_same_parameter": false, "check_curve3d_with_pcurve": false, "check_vertex_tolerance": false}, {"face_id": 13, "face_found": true, "has_pcurve": true, "check_same_parameter": false, "check_curve3d_with_pcurve": false, "check_vertex_tolerance": false}]}, {"curve_id": 50, "edge_index": 50, "face_ids": [19, 20], "edge_found": true, "edge_tolerance": 1e-07, "same_parameter_flag": true, "same_range_flag": true, "face_checks": [{"face_id": 19, "face_found": true, "has_pcurve": true, "check_same_parameter": false, "check_curve3d_with_pcurve": false, "check_vertex_tolerance": false}, {"face_id": 20, "face_found": true, "has_pcurve": true, "check_same_parameter": false, "check_curve3d_with_pcurve": false, "check_vertex_tolerance": false}]}]}`
- `{"tolerance": 0.001, "recovered": false, "checks": [{"curve_id": 36, "edge_index": 36, "face_ids": [12, 13], "edge_found": true, "edge_tolerance": 1e-07, "same_parameter_flag": true, "same_range_flag": true, "face_checks": [{"face_id": 12, "face_found": true, "has_pcurve": true, "check_same_parameter": false, "check_curve3d_with_pcurve": false, "check_vertex_tolerance": false}, {"face_id": 13, "face_found": true, "has_pcurve": true, "check_same_parameter": false, "check_curve3d_with_pcurve": false, "check_vertex_tolerance": false}]}, {"curve_id": 50, "edge_index": 50, "face_ids": [19, 20], "edge_found": true, "edge_tolerance": 1e-07, "same_parameter_flag": true, "same_range_flag": true, "face_checks": [{"face_id": 19, "face_found": true, "has_pcurve": true, "check_same_parameter": false, "check_curve3d_with_pcurve": false, "check_vertex_tolerance": false}, {"face_id": 20, "face_found": true, "has_pcurve": true, "check_same_parameter": false, "check_curve3d_with_pcurve": false, "check_vertex_tolerance": false}]}]}`

## Engineering Findings

- `station_same_parameter_feasibility_evaluated`
- `station_target_pcurves_present_before_repair`
- `station_same_parameter_checks_fail_before_repair`
- `breplib_same_parameter_did_not_recover_station_curve_checks`
- `same_parameter_tolerance_sweep_no_recovery`

## Blocking Reasons

- `station_same_parameter_repair_not_recovered`

## Next Actions

- `inspect_or_rebuild_station_pcurves_before_compound_meshing_policy`
- `avoid_solver_iteration_budget_until_station_topology_gate_changes`

## Limitations

- This report does not write a repaired STEP file and does not change production defaults.
- It does not run Gmsh, SU2_CFD, or any CL/convergence acceptance gate.
- A recovered same-parameter probe would only be a feasibility signal; it would still require real mesh and station fixture reruns.
