# Main Wing Station Seam Side-Aware Export Opcode Variant Probe v1

- status: `side_aware_export_opcode_variant_not_recovered`
- production_default_changed: `False`
- source_csm_path: `/Volumes/Samsung SSD/hpa-mdo/hpa_meshing_package/docs/reports/main_wing_real_mesh_handoff_probe/artifacts/provider_geometry/artifacts/geometry_validation/artifacts/providers/esp_rebuilt/esp_runtime/rebuild.csm`
- variants: `upper_lower_spline_split, all_linseg`
- materialize_variants: `True`
- variant_summary: `{"variant_count": 2, "materialized_variant_count": 2, "validated_variant_count": 1, "recovered_variant_count": 0, "surface_count_guard_skipped_count": 1, "best_station_edge_check_count": 10}`

## Engineering Findings

- `side_aware_export_opcode_variant_probe_evaluated`
- `upper_lower_spline_split_still_pcurve_suspect`
- `upper_lower_spline_split_surface_count_52`
- `all_linseg_surface_count_explosion_observed`
- `all_linseg_surface_count_582`
- `simple_opcode_variants_do_not_recover_station_pcurve_gate`

## Blocking Reasons

- `side_aware_export_opcode_variants_not_recovered`
- `side_aware_candidate_mesh_handoff_not_run`

## Next Actions

- `inspect_export_pcurve_metadata_generation_instead_of_simple_opcode_variants`
- `avoid_all_linseg_surface_count_explosion_as_product_candidate`
- `do_not_advance_to_mesh_until_station_brep_gate_passes`

## Limitations

- This probe changes only report-local CSM candidates; it does not change provider defaults.
- Opcode variants are upstream export diagnostics, not mesh handoff or solver evidence.
- High surface-count variants are guarded before BRep validation to avoid promoting faceted candidates.
