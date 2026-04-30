# tail_wing_su2_handoff_smoke.v1

`tail_wing_su2_handoff_smoke.v1` records an SU2 handoff materialization smoke
for the registered tail-wing route.

It is intentionally solver-free:

- it consumes the tail-wing non-BL `mesh_handoff.v1` smoke
- it writes `su2_handoff.v1`
- it writes `mesh.su2`
- it writes `su2_runtime.cfg`
- it does not run `SU2_CFD`
- it does not emit `convergence_gate.v1`
- it does not change production defaults

## Required Top-Level Fields

- `schema_version`: fixed string `tail_wing_su2_handoff_smoke.v1`
- `component`: fixed string `tail_wing`
- `geometry_family`: fixed string `thin_sheet_lifting_surface`
- `meshing_route`: fixed string `gmsh_thin_sheet_surface`
- `execution_mode`: fixed string `su2_materialization_only_no_solver`
- `source_mesh_smoke_schema`: expected `tail_wing_mesh_handoff_smoke.v1`
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

A materialization pass means hpa-mdo can turn the synthetic tail-wing
`mesh_handoff.v1` into a package-native SU2 case artifact bundle without asking
the solver to run.

It does **not** mean the route is CFD-ready. The current smoke uses a
component-owned `tail_wing` wall marker, but the mesh remains a synthetic thin
closed-solid tail slab. Solver execution, history parsing, convergence, and real
aerodynamic tail geometry remain blocking gates.

## Promotion Rule

This smoke can move the route past "missing SU2 handoff", but it cannot promote
the route to solver credibility. The next gates are:

1. real VSP/ESP tail geometry evidence
2. solver run
3. `convergence_gate.v1`
