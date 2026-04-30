# main_wing real mesh_handoff probe v1

This probe tries the real ESP main-wing geometry against the current Gmsh handoff route.
It runs in a bounded child process and does not run SU2.

- probe_status: `mesh_handoff_pass`
- mesh_probe_status: `completed`
- mesh_handoff_status: `written`
- provider_status: `materialized`
- provider_surface_count: `32`
- provider_volume_count: `1`
- selected_geom_name: `Main Wing`
- marker_summary_status: `component_wall_and_farfield_present`
- probe_profile: `coarse_first_volume_insertion_probe_not_production_default`
- coarse_first_tetra_enabled: `True`
- probe_global_min_size: `0.35`
- probe_global_max_size: `1.4`
- surface_patch_diagnostics_status: `available`
- surface_family_hint_counts: `{'high_aspect_strip_candidate': 24, 'short_curve_candidate': 22, 'span_extreme_candidate': 8, 'span_extreme_strip_candidate': 6, 'tiny_face_candidate': 22}`
- suspicious_surface_tags: `[31, 32, 6, 5, 26, 25, 8, 3, 28, 23, 7, 4]`
- volume_element_count: `584460`
- bounded_probe_timeout_seconds: `45.0`
- mesh2d_watchdog_status: `completed_without_timeout`
- mesh3d_watchdog_status: `completed_without_timeout`
- mesh3d_timeout_phase_classification: `optimization`
- mesh_failure_classification: `None`
- mesh_quality_status: `warn`
- mesh_quality_advisory_flags: `['gmsh_ill_shaped_tets_present', 'gmsh_min_gamma_below_1e_minus_4', 'gmsh_gamma_p01_below_0p20']`
- mesh_quality_metrics: `{'tetrahedron_count': 584460, 'ill_shaped_tet_count': 78, 'non_positive_min_sicn_count': 0, 'non_positive_min_sige_count': 0, 'non_positive_volume_count': 0, 'min_gamma': 8.131677887160085e-07, 'min_sicn': 0.0007790197756303649, 'min_sige': 0.0008646308768278953, 'min_volume': 1.096125480738833e-06, 'gamma_percentiles': {'p01': 0.13359208369407768, 'p05': 0.33242963726724084, 'p50': 0.8056187158799668}, 'min_sicn_percentiles': {'p01': 0.29972214941891534, 'p05': 0.42705267509854167, 'p50': 0.8377961522730251}, 'min_sige_percentiles': {'p01': 0.31680952267939777, 'p05': 0.4447358513541527, 'p50': 0.8604170445340937}, 'volume_percentiles': {'p01': 0.0032049488207234198, 'p05': 0.004861129795522252, 'p50': 0.009257178820713675}, 'worst_tet_sample_count': 20}`
- mesh3d_nodes_created_per_boundary_node: `23.914980793854035`
- error: `None`

## Blocking Reasons

- `main_wing_solver_not_run`
- `convergence_gate_not_run`

## Limitations

- This is a bounded coarse real-geometry probe, not production default sizing.
- It does not run BL runtime.
- It does not run SU2_CFD.
- convergence_gate.v1 was not emitted.
- A timeout or blocked mesh is evidence for meshing policy work, not a solver result.
- Mesh handoff was materialized, but Gmsh quality advisories mean it should not be treated as CFD-ready.
