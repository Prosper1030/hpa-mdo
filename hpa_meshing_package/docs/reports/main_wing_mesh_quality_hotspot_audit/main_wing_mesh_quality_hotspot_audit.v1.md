# Main Wing Mesh Quality Hotspot Audit v1

This report reads existing mesh-quality artifacts only; it does not run Gmsh or SU2.

- hotspot_status: `mesh_quality_hotspots_localized`
- mesh_handoff_report_path: `/Volumes/Samsung SSD/hpa-mdo/hpa_meshing_package/docs/reports/main_wing_real_mesh_handoff_probe/main_wing_real_mesh_handoff_probe.v1.json`
- mesh_metadata_path: `/Volumes/Samsung SSD/hpa-mdo/hpa_meshing_package/docs/reports/main_wing_real_mesh_handoff_probe/artifacts/real_mesh_probe/artifacts/mesh/mesh_metadata.json`
- hotspot_patch_report_path: `/Volumes/Samsung SSD/hpa-mdo/hpa_meshing_package/docs/reports/main_wing_real_mesh_handoff_probe/artifacts/real_mesh_probe/artifacts/mesh/hotspot_patch_report.json`
- surface_patch_diagnostics_path: `/Volumes/Samsung SSD/hpa-mdo/hpa_meshing_package/docs/reports/main_wing_real_mesh_handoff_probe/artifacts/real_mesh_probe/artifacts/mesh/surface_patch_diagnostics.json`
- gmsh_defect_entity_trace_path: `/Volumes/Samsung SSD/hpa-mdo/hpa_meshing_package/docs/reports/main_wing_gmsh_defect_entity_trace/main_wing_gmsh_defect_entity_trace.v1.json`
- production_default_changed: `False`

## Quality Summary

- `mesh_quality_status`: `warn`
- `mesh_quality_advisory_flags`: `["gmsh_ill_shaped_tets_present", "gmsh_min_gamma_below_1e_minus_4", "gmsh_gamma_p01_below_0p20"]`
- `tetrahedron_count`: `584460`
- `ill_shaped_tet_count`: `78`
- `min_gamma`: `8.13168e-07`
- `min_sicn`: `0.00077902`
- `min_sige`: `0.000864631`
- `min_volume`: `1.09613e-06`
- `worst_tet_sample_count`: `20`
- `worst_tet_sample_covers_all_ill_shaped`: `False`
- `gamma_percentiles`: `{"p01": 0.13359208369407768, "p05": 0.33242963726724084, "p50": 0.8056187158799668}`

## Worst-Tet Sample Partition

- `sample_count`: `20`
- `by_nearest_physical_name`: `{"farfield": 15, "main_wing": 5}`
- `by_nearest_surface_tag`: `{"19": 2, "29": 1, "32": 2, "33": 3, "35": 4, "37": 6, "38": 2}`
- `farfield_sample_count`: `15`
- `main_wing_sample_count`: `5`
- `unknown_sample_count`: `0`

## Station-Seam Overlap

- `trace_status`: `defect_edges_traced_to_gmsh_entities`
- `traced_surface_entity_tags`: `[12, 13, 19, 20]`
- `candidate_curve_tags`: `[36, 50]`
- `main_wing_hotspot_surface_tags`: `[19, 29, 32]`
- `overlap_surface_tags`: `[19]`
- `overlap_worst_tet_sample_count`: `2`

## Hotspot Surface Summaries

- `{"surface_tag": 38, "surface_role": "farfield", "nearest_physical_name_counts": {"farfield": 2}, "sample_worst_tet_count": 2, "sample_element_ids": [515801, 529513], "sample_min_gamma": 8.131677887160085e-07, "sample_max_edge_ratio": 2.7100545721170963, "sample_barycenter_y_range_m": [-57.33211790976855, -10.957255487906295], "hotspot_patch_entry_count": 2, "hotspot_patch_min_gamma": 8.131677887160085e-07, "bbox": null, "curve_tags": [], "short_curve_tags": [], "family_hints": [], "suspect_score": null}`
- `{"surface_tag": 35, "surface_role": "farfield", "nearest_physical_name_counts": {"farfield": 4}, "sample_worst_tet_count": 4, "sample_element_ids": [523556, 523401, 518675, 527035], "sample_min_gamma": 4.999118715218154e-06, "sample_max_edge_ratio": 2.818639622537329, "sample_barycenter_y_range_m": [9.676151168137611, 51.10902347335237], "hotspot_patch_entry_count": 4, "hotspot_patch_min_gamma": 4.999118715218154e-06, "bbox": null, "curve_tags": [], "short_curve_tags": [], "family_hints": [], "suspect_score": null}`
- `{"surface_tag": 37, "surface_role": "farfield", "nearest_physical_name_counts": {"farfield": 6}, "sample_worst_tet_count": 6, "sample_element_ids": [518031, 526160, 521319, 516326, 562328, 527425], "sample_min_gamma": 1.0391810061402613e-05, "sample_max_edge_ratio": 3.768699992041863, "sample_barycenter_y_range_m": [-66.2381389442314, 78.1652464723121], "hotspot_patch_entry_count": 6, "hotspot_patch_min_gamma": 1.0391810061402613e-05, "bbox": null, "curve_tags": [], "short_curve_tags": [], "family_hints": [], "suspect_score": null}`
- `{"surface_tag": 33, "surface_role": "farfield", "nearest_physical_name_counts": {"farfield": 3}, "sample_worst_tet_count": 3, "sample_element_ids": [521054, 524470, 515757], "sample_min_gamma": 0.00013246881685098226, "sample_max_edge_ratio": 4.122428592605682, "sample_barycenter_y_range_m": [-41.640234891827035, 66.23947442905813], "hotspot_patch_entry_count": null, "hotspot_patch_min_gamma": null, "bbox": null, "curve_tags": [], "short_curve_tags": [], "family_hints": [], "suspect_score": null}`
- `{"surface_tag": 19, "surface_role": "aircraft", "nearest_physical_name_counts": {"main_wing": 2}, "sample_worst_tet_count": 2, "sample_element_ids": [551818, 558478], "sample_min_gamma": 0.0008847306797953164, "sample_max_edge_ratio": 25.725282630775443, "sample_barycenter_y_range_m": [12.619860331529626, 12.703193664852382], "hotspot_patch_entry_count": 2, "hotspot_patch_min_gamma": 0.0008847306797953164, "bbox": {"x_min": 0.05655589551667944, "y_min": 10.499999898666882, "z_min": 0.28585353041770695, "x_max": 1.0864346067220623, "y_max": 13.50000009828599, "z_max": 0.6447233711301434}, "curve_tags": [27, 48, 49, 50], "short_curve_tags": [], "family_hints": [], "suspect_score": 2.173869070675406}`
- `{"surface_tag": 29, "surface_role": "aircraft", "nearest_physical_name_counts": {"main_wing": 1}, "sample_worst_tet_count": 1, "sample_element_ids": [558476], "sample_min_gamma": 0.007814526015991446, "sample_max_edge_ratio": 38.51393593694695, "sample_barycenter_y_range_m": [12.707018316916873, 12.707018316916873], "hotspot_patch_entry_count": null, "hotspot_patch_min_gamma": null, "bbox": {"x_min": 0.925579086525485, "y_min": 10.499999898666882, "z_min": 0.28355450133899884, "x_max": 1.0961382612808304, "y_max": 13.50000009828599, "z_max": 0.5118537804500131}, "curve_tags": [26, 49, 61, 62], "short_curve_tags": [61, 62], "family_hints": ["tiny_face_candidate", "short_curve_candidate", "high_aspect_strip_candidate"], "suspect_score": 23.11267080050286}`
- `{"surface_tag": 32, "surface_role": "aircraft", "nearest_physical_name_counts": {"main_wing": 2}, "sample_worst_tet_count": 2, "sample_element_ids": [557345, 557346], "sample_min_gamma": 0.010731379891030304, "sample_max_edge_ratio": 158.8300748146559, "sample_barycenter_y_range_m": [16.578588312030405, 16.578588312030405], "hotspot_patch_entry_count": null, "hotspot_patch_min_gamma": null, "bbox": {"x_min": 0.23037017658312592, "y_min": 16.4999998979051, "z_min": 0.7623469019905605, "x_max": 0.6686575541235461, "y_max": 16.500000097905104, "z_max": 0.8441453609632887}, "curve_tags": [31, 52, 63], "short_curve_tags": [31, 63], "family_hints": ["tiny_face_candidate", "short_curve_candidate", "high_aspect_strip_candidate", "span_extreme_candidate"], "suspect_score": 41.92238194623743}`

## Engineering Findings

- `mesh_quality_warning_present`
- `gmsh_ill_shaped_tets_present`
- `gmsh_min_gamma_below_1e_minus_4`
- `worst_tet_sample_incomplete_for_all_ill_shaped_tets`
- `worst_tet_sample_mostly_farfield`
- `main_wing_near_surface_quality_hotspots_present`
- `main_wing_quality_hotspot_overlaps_station_seam_trace`
- `main_wing_hotspot_surfaces_include_short_curve_strips`

## Blocking Reasons

- none

## Next Actions

- `repair_station_seam_export_before_solver_iteration_budget`
- `inspect_main_wing_hotspot_surfaces_19_29_32_after_station_pcurve_fix`
- `separate_farfield_sliver_cleanup_from_lift_gap_root_cause`
- `avoid_more_solver_iterations_until_geometry_and_mesh_gates_are_clean`

## Limitations

- This audit reads existing mesh-quality artifacts only; it does not remesh or repair topology.
- The worst-tet list is a bounded sample, not a complete localization of every ill-shaped tet.
- Quality hotspots are route-risk evidence, not SU2 convergence evidence.
