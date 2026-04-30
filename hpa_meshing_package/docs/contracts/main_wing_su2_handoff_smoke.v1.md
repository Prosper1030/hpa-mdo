# main_wing_su2_handoff_smoke.v1

`main_wing_su2_handoff_smoke.v1` records an SU2 handoff materialization smoke
for the registered main-wing route.

It is intentionally solver-free:

- it consumes the main-wing non-BL `mesh_handoff.v1` smoke
- it writes `su2_handoff.v1`
- it writes `mesh.su2`
- it writes `su2_runtime.cfg`
- it does not run `SU2_CFD`
- it does not emit `convergence_gate.v1`
- it does not change production defaults

## Required Top-Level Fields

- `schema_version`: fixed string `main_wing_su2_handoff_smoke.v1`
- `component`: fixed string `main_wing`
- `geometry_family`: fixed string `thin_sheet_lifting_surface`
- `meshing_route`: fixed string `gmsh_thin_sheet_surface`
- `execution_mode`: fixed string `su2_materialization_only_no_solver`
- `source_mesh_smoke_schema`: expected `main_wing_mesh_handoff_smoke.v1`
- `no_su2_execution`: must be `true`
- `no_convergence_gate`: must be `true`
- `production_default_changed`: must be `false`
- `materialization_status`
- `su2_contract`
- `input_mesh_contract`
- `solver_execution_status`
- `convergence_gate_status`
- `wall_marker_status`
- `force_surface_scope`
- `component_force_ownership_status`
- case paths, guarantees, blocking reasons, and limitations

## Pass Meaning

A materialization pass means hpa-mdo can turn the synthetic main-wing
`mesh_handoff.v1` into a package-native SU2 case artifact bundle without asking
the solver to run.

It does **not** mean the route is CFD-ready. The current smoke still uses the
component-owned `main_wing` wall marker, but the mesh remains synthetic.
Real aerodynamic geometry, real SU2 handoff, and real solver smoke are tracked
by the separate real-route probes. This smoke remains synthetic wiring evidence.

## Promotion Rule

This smoke can move the route past "missing SU2 handoff", but it cannot promote
the route to solver credibility. The current real-route gates are:

1. real VSP/ESP main-wing mesh and SU2 handoff evidence
2. solver execution evidence
3. `convergence_gate.v1` pass
4. reference chord / moment-origin provenance pass
