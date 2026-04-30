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
