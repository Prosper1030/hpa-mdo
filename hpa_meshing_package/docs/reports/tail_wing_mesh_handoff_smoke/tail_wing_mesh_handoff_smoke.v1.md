# tail_wing mesh_handoff smoke v1

This is a real Gmsh non-BL mesh-handoff smoke for the tail-wing route.
It does not run SU2, BL runtime, or production defaults.

- component: `tail_wing`
- meshing_route: `gmsh_thin_sheet_surface`
- smoke_status: `mesh_handoff_pass`
- mesh_handoff_status: `written`
- mesh_contract: `mesh_handoff.v1`
- marker_summary_status: `component_wall_and_farfield_present`
- wall_marker_status: `tail_wing_marker_present`
- su2_promotion_status: `blocked_before_su2_handoff`
- volume_element_count: `646`

## Blocking Reasons

- `tail_wing_su2_handoff_not_run`
- `convergence_gate_not_run`
- `synthetic_fixture_not_real_tail_geometry`

## Limitations

- Synthetic thin closed-solid tail slab is a route smoke fixture, not aerodynamic tail geometry.
- Boundary-layer runtime was not executed.
- SU2_CFD was not executed.
- su2_handoff.v1 was not emitted.
- convergence_gate.v1 was not emitted.
- Production defaults were not changed.
