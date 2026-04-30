# fairing_solid_real_mesh_handoff_probe.v1

`fairing_solid_real_mesh_handoff_probe.v1` records a bounded attempt to run the
real fairing VSP geometry through the current `gmsh_closed_solid_volume` handoff
route.

It is intentionally report-only:

- it consumes the real fairing `best_design.vsp3` source by default
- it requires `fairing_solid_real_geometry_smoke.v1` to pass first
- it runs the current Gmsh closed-solid handoff route in a bounded child process
- it records pass / timeout / blocker evidence instead of forcing a pass
- it does not run BL runtime
- it does not run `SU2_CFD`
- it does not emit `su2_handoff.v1` or `convergence_gate.v1`
- it does not change production defaults

## Required Top-Level Fields

- `schema_version`: fixed string `fairing_solid_real_mesh_handoff_probe.v1`
- `component`: fixed string `fairing_solid`
- `source_fixture`
- `geometry_provider`: fixed string `openvsp_surface_intersection`
- `geometry_family`: fixed string `closed_solid`
- `meshing_route`: fixed string `gmsh_closed_solid_volume`
- `execution_mode`: fixed string `real_provider_bounded_mesh_handoff_probe_no_su2`
- `mesh_sizing_policy`
- `probe_status`
- `mesh_probe_status`
- `mesh_handoff_status`
- `provider_status`
- `marker_summary_status`
- `fairing_force_marker_status`
- provider topology counts and selected geometry metadata
- mesh counts when a handoff is written
- unit-normalization evidence
- guarantees, blocking reasons, and limitations

## Pass Meaning

A pass means a bounded coarse real-geometry probe wrote `mesh_handoff.v1` with a
component-owned `fairing_solid` wall marker and a `farfield` marker.

It still is not solver credibility. The next gate is real fairing
`su2_handoff.v1` materialization, followed by solver execution and
`convergence_gate.v1`.
