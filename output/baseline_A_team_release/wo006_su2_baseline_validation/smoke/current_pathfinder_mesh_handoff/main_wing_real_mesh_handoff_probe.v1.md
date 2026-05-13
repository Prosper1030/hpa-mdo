# main_wing real mesh_handoff probe v1

This probe tries the real ESP main-wing geometry against the current Gmsh handoff route.
It runs in a bounded child process and does not run SU2.

- probe_status: `mesh_handoff_timeout`
- mesh_probe_status: `timeout`
- mesh_handoff_status: `missing`
- provider_status: `materialized`
- provider_surface_count: `50`
- provider_volume_count: `1`
- selected_geom_name: `Phase7SidecarWing`
- marker_summary_status: `unavailable`
- probe_profile: `coarse_first_volume_insertion_probe_not_production_default`
- coarse_first_tetra_enabled: `True`
- probe_global_min_size: `0.2`
- probe_global_max_size: `0.8`
- surface_patch_diagnostics_status: `available`
- surface_family_hint_counts: `{'high_aspect_strip_candidate': 34, 'short_curve_candidate': 34, 'span_extreme_candidate': 8, 'span_extreme_strip_candidate': 6, 'tiny_face_candidate': 34}`
- suspicious_surface_tags: `[1, 16, 3, 14, 2, 15, 49, 50, 4, 13, 33, 48]`
- volume_element_count: `None`
- bounded_probe_timeout_seconds: `60.0`
- mesh2d_watchdog_status: `completed_without_timeout`
- mesh3d_watchdog_status: `triggered_while_meshing`
- mesh3d_timeout_phase_classification: `volume_insertion`
- mesh_failure_classification: `None`
- mesh_quality_status: `unavailable`
- mesh_quality_advisory_flags: `[]`
- mesh_quality_metrics: `{}`
- mesh3d_nodes_created_per_boundary_node: `7.468692047561907`
- error: `bounded_mesh_handoff_timeout_after_60.0s`

## Blocking Reasons

- `main_wing_real_geometry_mesh_handoff_timeout`
- `main_wing_real_geometry_mesh3d_volume_insertion_timeout`
- `main_wing_solver_not_run`
- `convergence_gate_not_run`

## Limitations

- This is a bounded coarse real-geometry probe, not production default sizing.
- It does not run BL runtime.
- It does not run SU2_CFD.
- convergence_gate.v1 was not emitted.
- A timeout or blocked mesh is evidence for meshing policy work, not a solver result.
