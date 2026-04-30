# main_wing esp_rebuilt geometry smoke v1

This is a provider-geometry smoke for the main-wing route.
It validates VSP/ESP materialization without running Gmsh or SU2.

- component: `main_wing`
- geometry_smoke_status: `geometry_smoke_pass`
- provider_status: `materialized`
- validation_status: `success`
- effective_component: `main_wing`
- selected_geom_name: `Main Wing`
- surface_count: `32`
- volume_count: `1`
- mesh_handoff_status: `not_run`
- su2_handoff_status: `not_run`

## Blocking Reasons

- `main_wing_real_geometry_mesh_handoff_not_run`
- `main_wing_solver_not_run`
- `convergence_gate_not_run`

## Limitations

- This smoke materializes provider geometry only; it does not run Gmsh.
- mesh_handoff.v1 is not emitted for the real main-wing geometry.
- SU2_CFD was not executed.
- convergence_gate.v1 was not emitted.
- The normalized main-wing geometry is not solver credibility evidence by itself.
- Production defaults were not changed.
