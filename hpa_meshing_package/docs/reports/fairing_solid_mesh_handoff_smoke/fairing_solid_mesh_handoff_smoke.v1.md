# fairing_solid mesh_handoff smoke v1

This is a real Gmsh mesh-handoff smoke for the closed-solid fairing route.
It does not run SU2, BL runtime, or production defaults.

- component: `fairing_solid`
- meshing_route: `gmsh_closed_solid_volume`
- smoke_status: `mesh_handoff_pass`
- mesh_handoff_status: `written`
- mesh_contract: `mesh_handoff.v1`
- marker_summary_status: `component_wall_and_farfield_present`
- fairing_force_marker_status: `component_specific_marker_present`
- su2_promotion_status: `blocked_before_su2_handoff`
- volume_element_count: `9179`

## Blocking Reasons

- `fairing_su2_handoff_not_materialized`
- `convergence_gate_not_run`

## Limitations

- Synthetic OCC box fixture is a route smoke fixture, not fairing aerodynamic geometry.
- The fairing-specific marker is mesh-handoff evidence only; SU2 handoff has not consumed it yet.
- SU2_CFD was not executed.
- convergence_gate.v1 was not emitted.
- Production defaults were not changed.
