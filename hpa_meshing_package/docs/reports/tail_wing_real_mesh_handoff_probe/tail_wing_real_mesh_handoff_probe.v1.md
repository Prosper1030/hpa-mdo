# tail_wing real mesh_handoff probe v1

This probe tries the real ESP tail geometry against the current Gmsh handoff route.
It records the surface_only blocker without running SU2.

- probe_status: `mesh_handoff_blocked`
- mesh_handoff_status: `missing`
- failure_code: `gmsh_backend_failed`
- provider_status: `materialized`
- provider_surface_count: `6`
- provider_volume_count: `0`
- error: `normalized STEP did not import any OCC volumes for gmsh_thin_sheet_surface.`

## Blocking Reasons

- `real_tail_geometry_surface_only_no_occ_volume`
- `tail_wing_solver_not_run`
- `convergence_gate_not_run`

## Limitations

- synthetic_tail_slab_is_not_real_tail_mesh_evidence
- Real ESP tail geometry currently materializes as surface-only STEP evidence.
- The current gmsh_thin_sheet_surface backend expects OCC volumes for its external-flow route.
- mesh_handoff.v1 is not emitted for the real tail geometry in this probe.
- SU2_CFD was not executed.
- convergence_gate.v1 was not emitted.
