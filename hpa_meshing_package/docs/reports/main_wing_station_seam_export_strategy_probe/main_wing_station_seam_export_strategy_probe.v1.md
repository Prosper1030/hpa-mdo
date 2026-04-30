# Main Wing Station Seam Export Strategy Probe v1

This report prototypes station-seam export strategies without changing production defaults.

- probe_status: `export_strategy_candidate_materialized_but_topology_risk`
- export_source_audit_path: `/Volumes/Samsung SSD/hpa-mdo/hpa_meshing_package/docs/reports/main_wing_station_seam_export_source_audit/main_wing_station_seam_export_source_audit.v1.json`
- rebuild_csm_path: `/Volumes/Samsung SSD/hpa-mdo/hpa_meshing_package/docs/reports/main_wing_real_mesh_handoff_probe/artifacts/provider_geometry/artifacts/geometry_validation/artifacts/providers/esp_rebuilt/esp_runtime/rebuild.csm`
- materialization_requested: `True`
- production_default_changed: `False`
- target_rule_section_indices: `[2, 9]`

## Candidate Reports

### split_at_defect_sections_no_union

- apply_union: `False`
- rule_count: `3`
- all_targets_exported_as_rule_boundaries: `True`
- target_boundary_duplication_count: `2`
- span_y_bounds_preserved: `True`
- materialization_status: `materialized`
- returncode: `0`
- csm_path: `/Volumes/Samsung SSD/hpa-mdo/hpa_meshing_package/docs/reports/main_wing_station_seam_export_strategy_probe/artifacts/split_at_defect_sections_no_union/candidate.csm`
- step_path: `/Volumes/Samsung SSD/hpa-mdo/hpa_meshing_package/docs/reports/main_wing_station_seam_export_strategy_probe/artifacts/split_at_defect_sections_no_union/candidate_raw_dump.stp`
- topology_body_count: `3`
- topology_volume_count: `3`
- topology_surface_count: `36`
- topology_bbox_y: `[-16.5000001, 16.5000001]`

### split_at_defect_sections_union

- apply_union: `True`
- rule_count: `3`
- all_targets_exported_as_rule_boundaries: `True`
- target_boundary_duplication_count: `2`
- span_y_bounds_preserved: `False`
- materialization_status: `materialized`
- returncode: `0`
- csm_path: `/Volumes/Samsung SSD/hpa-mdo/hpa_meshing_package/docs/reports/main_wing_station_seam_export_strategy_probe/artifacts/split_at_defect_sections_union/candidate.csm`
- step_path: `/Volumes/Samsung SSD/hpa-mdo/hpa_meshing_package/docs/reports/main_wing_station_seam_export_strategy_probe/artifacts/split_at_defect_sections_union/candidate_raw_dump.stp`
- topology_body_count: `1`
- topology_volume_count: `1`
- topology_surface_count: `34`
- topology_bbox_y: `[-16.500000290419646, 13.500000290419644]`

## Engineering Findings

- `station_seam_export_strategy_probe_captured`
- `split_candidate_moves_target_stations_to_rule_boundaries`
- `split_candidate_duplicates_station_boundaries`
- `split_at_defect_sections_no_union_materialized_with_topology_risk`
- `split_at_defect_sections_union_materialized_but_span_bounds_not_preserved`
- `split_at_defect_sections_union_materialized_with_topology_risk`

## Blocking Reasons

- `split_candidate_topology_not_single_volume_or_has_duplicate_cap_risk`
- `split_candidate_does_not_preserve_full_span_bounds`
- `split_candidate_duplicates_target_station_sections`

## Next Actions

- `inspect_split_candidate_internal_caps_before_mesh_handoff`
- `try_pcurve_rebuild_strategy_if_split_candidate_keeps_duplicate_caps`

## Limitations

- This probe writes candidate export sources only under its report directory.
- It does not change esp_rebuilt, Gmsh, SU2, or production defaults.
- A materialized split candidate is not a CFD-ready geometry until BRep, mesh handoff, marker ownership, and solver gates pass.
