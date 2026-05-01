# Main Wing Station Seam Export Metadata Source Audit v1

- status: `export_metadata_generation_source_boundary_captured`
- production_default_changed: `False`
- opcode_variant_probe_path: `/Volumes/Samsung SSD/hpa-mdo/hpa_meshing_package/docs/reports/main_wing_station_seam_side_aware_export_opcode_variant_probe/main_wing_station_seam_side_aware_export_opcode_variant_probe.v1.json`
- current_negative_controls: `{"opcode_variant_status": "side_aware_export_opcode_variant_not_recovered", "variant_count": 2, "materialized_variant_count": 2, "validated_variant_count": 1, "recovered_variant_count": 0, "surface_count_guard_skipped_count": 1, "best_station_edge_check_count": 10, "engineering_findings": ["side_aware_export_opcode_variant_probe_evaluated", "upper_lower_spline_split_still_pcurve_suspect", "upper_lower_spline_split_surface_count_52", "all_linseg_surface_count_explosion_observed", "all_linseg_surface_count_582", "simple_opcode_variants_do_not_recover_station_pcurve_gate"]}`

## Source Boundary

- hpa_mdo_controls: `["section_coordinates", "sketch_opcode_policy", "rule_grouping", "dump_invocation"]`
- external_controls: `["opencsm_rule_loft_surface_construction", "opencsm_rule_loft_pcurve_metadata", "egads_step_export_metadata", "occt_shape_analysis_semantics_after_step_import"]`
- post_export_hpa_mdo_diagnostics: `["same_parameter_shape_fix_sweeps", "bounded_existing_pcurve_rewrite_attempts", "projected_or_sampled_pcurve_negative_controls"]`

## Engineering Findings

- `export_metadata_source_boundary_audit_captured`
- `provider_export_uses_opencsm_rule_then_dump`
- `side_aware_candidate_export_is_csm_script_level_control`
- `hpa_mdo_csm_generation_has_no_explicit_pcurve_metadata_api`
- `report_local_opcode_variants_do_not_recover_metadata_gate`

## Blocking Reasons

- `export_pcurve_metadata_generation_not_owned_by_hpa_mdo`
- `side_aware_candidate_mesh_handoff_not_run`

## Next Actions

- `inspect_opencsm_egads_step_export_metadata_controls_or_add_owned_occ_export_path`
- `avoid_more_simple_csm_opcode_sweeps`
- `keep_mesh_handoff_blocked_until_station_metadata_gate_passes`

## Limitations

- This audit reads source and reports only; it does not mutate provider defaults.
- It does not run serveCSM, Gmsh, SU2_CFD, or convergence gates.
- It separates hpa-mdo CSM-script controls from OpenCSM/EGADS/OCCT metadata generation.
- CL acceptance remains a solver/convergence gate, not a source-audit output.
