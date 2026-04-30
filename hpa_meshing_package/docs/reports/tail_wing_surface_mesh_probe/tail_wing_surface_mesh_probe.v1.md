# tail_wing surface mesh probe v1

This probe meshes the real ESP tail surfaces without claiming a volume handoff.

- probe_status: `surface_mesh_pass`
- surface_mesh_status: `written`
- mesh_handoff_status: `not_written`
- su2_volume_handoff_status: `not_su2_ready`
- provider_status: `materialized`
- provider_surface_count: `6`
- provider_volume_count: `0`
- imported_surface_count: `6`
- surface_element_count: `2286`
- volume_element_count: `0`

## Blocking Reasons

- `surface_only_tail_mesh_not_external_flow_volume_handoff`
- `tail_surface_only_mesh_not_su2_volume_handoff`
- `tail_wing_solver_not_run`
- `convergence_gate_not_run`

## Limitations

- mesh_handoff.v1 is not emitted by the surface-only probe.
- The probe has a tail_wing surface marker but no farfield volume marker.
- A zero-thickness surface mesh is not an external-flow SU2 volume mesh.
- Provider solidification/capping or a baffle-volume route is still required before SU2_CFD.
- SU2_CFD was not executed.
- convergence_gate.v1 was not emitted.
