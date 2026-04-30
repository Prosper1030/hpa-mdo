# fairing_solid su2_handoff smoke v1

This is an SU2 handoff materialization smoke for the closed-solid fairing route.
It writes the SU2 case artifacts without executing SU2_CFD.

- component: `fairing_solid`
- materialization_status: `su2_handoff_written`
- su2_contract: `su2_handoff.v1`
- input_mesh_contract: `mesh_handoff.v1`
- solver_execution_status: `not_run`
- convergence_gate_status: `not_run`
- wall_marker_status: `fairing_solid_marker_present`
- force_surface_scope: `component_subset`
- component_force_ownership_status: `owned`

## Blocking Reasons

- `su2_solver_not_run`
- `convergence_gate_not_run`
- `synthetic_fixture_not_real_fairing_geometry`
- `real_fairing_geometry_not_used`

## Limitations

- This smoke materializes an SU2 case only; it does not run SU2_CFD.
- convergence_gate.v1 is not emitted because no solver history exists.
- The input mesh is a synthetic closed-solid box, not real fairing geometry.
- The handoff uses a component-owned fairing_solid wall marker, but the geometry is still synthetic.
- Production defaults were not changed.
