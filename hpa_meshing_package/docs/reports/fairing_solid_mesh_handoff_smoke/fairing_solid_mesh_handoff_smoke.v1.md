# fairing_solid mesh_handoff smoke v1

This is a real Gmsh mesh-handoff smoke for the closed-solid fairing route.
It does not run SU2, BL runtime, or production defaults.

- component: `fairing_solid`
- meshing_route: `gmsh_closed_solid_volume`
- smoke_status: `mesh_handoff_pass`
- mesh_handoff_status: `written`
- mesh_contract: `mesh_handoff.v1`
- marker_summary_status: `generic_wall_and_farfield_present`
- fairing_force_marker_status: `missing_component_specific_marker`
- su2_promotion_status: `blocked_before_su2_handoff`
- volume_element_count: `9158`

## Blocking Reasons

- `fairing_component_specific_force_marker_missing`
- `su2_handoff_not_run`
- `convergence_gate_not_run`

## Limitations

- Synthetic OCC box fixture is a route smoke fixture, not fairing aerodynamic geometry.
- The current wall marker is generic `aircraft`; fairing-specific force-surface ownership is not proven.
- SU2_CFD was not executed.
- convergence_gate.v1 was not emitted.
- Production defaults were not changed.
