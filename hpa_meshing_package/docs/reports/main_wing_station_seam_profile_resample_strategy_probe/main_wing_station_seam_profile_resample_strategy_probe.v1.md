# Main Wing Station Seam Profile Resample Strategy Probe v1

- status: `profile_resample_candidate_materialized_needs_brep_validation`
- production_default_changed: `False`
- materialization_requested: `True`
- rebuild_csm_path: `/Volumes/Samsung SSD/hpa-mdo/hpa_meshing_package/docs/reports/main_wing_real_mesh_handoff_probe/artifacts/provider_geometry/artifacts/geometry_validation/artifacts/providers/esp_rebuilt/esp_runtime/rebuild.csm`
- source_profile_point_counts: `[57, 57, 59, 59, 59, 59, 59, 59, 59, 57, 57]`
- target_profile_point_count: `59`
- target_station_y_m: `[-10.5, 13.5]`

## Candidate

- candidate: `uniform_profile_resample_single_rule`
- rule_count: `1`
- materialization_status: `materialized`
- body_count: `1`
- volume_count: `1`
- surface_count: `32`
- span_y_bounds_preserved: `True`
- target_station_face_counts: `-10.5:0, 13.5:0`

## Engineering Findings

- `station_seam_profile_resample_strategy_probe_captured`
- `source_profile_point_count_mismatch_observed`
- `candidate_profile_point_counts_uniformized`
- `uniform_profile_candidate_no_target_cap_faces_detected`
- `uniform_profile_candidate_single_volume_full_span_observed`

## Blocking Reasons

- `candidate_needs_station_brep_pcurve_validation_before_mesh_handoff`

## Next Actions

- `run_station_seam_brep_hotspot_probe_on_profile_resample_candidate`
- `compare_profile_resample_candidate_mesh_handoff_without_promoting_default`

## Limitations

- This report resamples section profiles in a candidate OpenCSM source only; it does not change the provider default.
- A clean single-volume candidate still needs station BRep/PCurve, mesh handoff, SU2, solver, and convergence gates.
- Profile resampling can perturb airfoil fidelity and must be evaluated before route promotion.
