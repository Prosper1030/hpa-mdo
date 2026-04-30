# Main Wing Station Seam Export Source Audit v1

This report ties the station-seam blocker back to the generated OpenCSM export source.

- audit_status: `single_rule_internal_station_export_source_confirmed`
- shape_fix_feasibility_path: `/Volumes/Samsung SSD/hpa-mdo/hpa_meshing_package/docs/reports/main_wing_station_seam_shape_fix_feasibility/main_wing_station_seam_shape_fix_feasibility.v1.json`
- topology_fixture_path: `/Volumes/Samsung SSD/hpa-mdo/hpa_meshing_package/docs/reports/main_wing_openvsp_section_station_topology_fixture/main_wing_openvsp_section_station_topology_fixture.v1.json`
- rebuild_csm_path: `/Volumes/Samsung SSD/hpa-mdo/hpa_meshing_package/docs/reports/main_wing_real_mesh_handoff_probe/artifacts/provider_geometry/artifacts/geometry_validation/artifacts/providers/esp_rebuilt/esp_runtime/rebuild.csm`
- production_default_changed: `False`

## CSM Summary

- `rule_count`: `1`
- `sketch_section_count`: `11`
- `dump_count`: `1`
- `union_count`: `0`
- `single_rule_multi_section_loft`: `True`
- `station_y_values_m`: `[-16.5, -13.5, -10.5, -7.5, -4.5, 0.0, 4.5, 7.5, 10.5, 13.5, 16.5]`

## Target Station Mappings

- `{"defect_station_y_m": -10.5, "candidate_curve_tags": [36], "owner_surface_entity_tags": [12, 13], "fixture_source_section_index": 3, "csm_section_index": 2, "csm_station_role": "internal_station", "lineage_rule_section_index": 2, "lineage_source_section_index": 3, "lineage_mirrored": true, "lineage_side": "left_span"}`
- `{"defect_station_y_m": 13.5, "candidate_curve_tags": [50], "owner_surface_entity_tags": [19, 20], "fixture_source_section_index": 4, "csm_section_index": 9, "csm_station_role": "internal_station", "lineage_rule_section_index": 9, "lineage_source_section_index": 4, "lineage_mirrored": false, "lineage_side": "right_span"}`

## Export Strategy Candidates

- `{"candidate": "station_pcurve_or_export_rebuild", "priority": "high", "scope": "provider_or_export_strategy_probe", "rationale": "Generic post-export OCCT edge repair did not recover the station checks, so the next probe should change how station seams are generated or exported."}`
- `{"candidate": "split_bay_rule_loft_probe", "priority": "medium", "scope": "report_only_candidate_before_production_default", "rationale": "Build span bays as separate rule loft candidates and inspect station ownership/PCurves before considering any Gmsh policy.", "risk": "may introduce duplicate internal caps or multiple solids"}`
- `{"candidate": "avoid_more_generic_occt_edge_fix_sweeps", "priority": "high", "scope": "negative_result_guardrail", "rationale": "BRepLib.SameParameter and ShapeFix_Edge operation sweeps already returned zero recovered target station checks."}`

## Engineering Findings

- `station_seam_export_source_audit_captured`
- `opencsm_export_uses_single_rule_loft_over_multiple_sections`
- `station_defects_map_to_internal_rule_sections`
- `generic_occt_edge_fix_sweeps_exhausted_without_recovery`
- `export_strategy_probe_is_next_geometry_gate`

## Blocking Reasons

- `station_single_rule_internal_export_source_requires_strategy_probe`

## Next Actions

- `prototype_station_seam_export_strategy_before_solver_budget`
- `compare_split_bay_or_pcurve_rebuild_candidate_against_station_fixture`

## Limitations

- This report reads existing OpenCSM/STEP lineage artifacts only.
- It does not run serveCSM, Gmsh, SU2_CFD, or convergence gates.
- Export strategy candidates are diagnostic proposals, not production defaults.
