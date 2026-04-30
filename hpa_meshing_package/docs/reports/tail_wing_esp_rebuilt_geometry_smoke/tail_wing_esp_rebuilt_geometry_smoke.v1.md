# tail_wing esp_rebuilt geometry smoke v1

This is a provider-geometry smoke for the tail-wing route.
It validates VSP/ESP materialization without running Gmsh or SU2.

- component: `tail_wing`
- geometry_smoke_status: `geometry_smoke_pass`
- provider_status: `materialized`
- validation_status: `success`
- effective_component: `horizontal_tail`
- selected_geom_name: `Elevator`
- surface_count: `6`
- mesh_handoff_status: `not_run`
- su2_handoff_status: `not_run`

## Blocking Reasons

- `tail_real_geometry_mesh_handoff_not_run`
- `tail_wing_solver_not_run`
- `convergence_gate_not_run`

## Limitations

- This smoke materializes provider geometry only; it does not run Gmsh.
- mesh_handoff.v1 is not emitted for the real tail geometry.
- SU2_CFD was not executed.
- convergence_gate.v1 was not emitted.
- The normalized tail geometry is a thin lifting-surface STEP; it is not solver credibility evidence by itself.
- Production defaults were not changed.
