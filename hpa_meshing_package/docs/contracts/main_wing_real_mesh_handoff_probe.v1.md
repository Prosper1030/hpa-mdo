# main_wing_real_mesh_handoff_probe.v1

`main_wing_real_mesh_handoff_probe.v1` records a bounded attempt to run the
real ESP-rebuilt main-wing geometry through the current
`gmsh_thin_sheet_surface` handoff route.

It is intentionally report-only:

- it consumes `data/blackcat_004_origin.vsp3`
- it requires the `esp_rebuilt` provider to select OpenVSP `Main Wing`
- it runs the current Gmsh handoff route in a bounded child process
- it records timeout / blocker evidence instead of forcing a pass
- it does not run BL runtime
- it does not run `SU2_CFD`
- it does not emit `su2_handoff.v1` or `convergence_gate.v1`
- it does not change production defaults

## Required Top-Level Fields

- `schema_version`: fixed string `main_wing_real_mesh_handoff_probe.v1`
- `component`: fixed string `main_wing`
- `source_fixture`
- `geometry_provider`: fixed string `esp_rebuilt`
- `geometry_family`: fixed string `thin_sheet_lifting_surface`
- `meshing_route`: fixed string `gmsh_thin_sheet_surface`
- `execution_mode`: fixed string `real_provider_bounded_mesh_handoff_probe_no_su2`
- `mesh_sizing_policy`
- `probe_status`
- `mesh_probe_status`
- `mesh_handoff_status`
- `provider_status`
- provider topology counts and selected geometry metadata
- watchdog paths and watchdog status fields
- mesh counts when a handoff is written
- guarantees, blocking reasons, and limitations

## Pass Meaning

A pass means a bounded coarse real-geometry probe wrote `mesh_handoff.v1` with
the real main-wing provider geometry. It still would not be solver credibility,
because SU2 and convergence are not run here.

A timeout is also useful evidence. For example, the current committed report
shows 2D meshing completed but 3D meshing timed out during volume insertion.
That is a meshing-policy blocker, not a reason to claim solver failure.
