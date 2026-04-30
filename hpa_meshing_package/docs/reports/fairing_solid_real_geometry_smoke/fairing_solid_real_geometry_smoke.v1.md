# fairing_solid real geometry smoke v1

This is a provider-geometry smoke for the real fairing route.
It validates VSP materialization without running Gmsh meshing or SU2.

- component: `fairing_solid`
- geometry_smoke_status: `geometry_smoke_pass`
- provider_status: `materialized`
- validation_status: `success`
- geometry_provider: `openvsp_surface_intersection`
- selected_geom_name: `best_design`
- selected_geom_type: `Fuselage`
- gmsh_topology_probe_status: `observed`
- body_count: `1`
- surface_count: `8`
- volume_count: `1`
- mesh_handoff_status: `not_run`
- su2_handoff_status: `not_run`

## Blocking Reasons

- `fairing_real_geometry_mesh_handoff_not_run`
- `fairing_solver_not_run`
- `convergence_gate_not_run`

## Limitations

- This smoke materializes provider geometry only; it does not run Gmsh meshing.
- The provider may use Gmsh OCC import only as a topology probe.
- mesh_handoff.v1 is not emitted for the real fairing geometry.
- SU2_CFD was not executed.
- convergence_gate.v1 was not emitted.
- The normalized fairing geometry is not solver credibility evidence by itself.
- Production defaults were not changed.
