# fairing_solid_su2_handoff_smoke.v1

`fairing_solid_su2_handoff_smoke.v1` records an SU2 handoff materialization
smoke for the closed-solid fairing route.

It is intentionally solver-free:

- it consumes the fairing closed-solid `mesh_handoff.v1` smoke
- it writes `su2_handoff.v1`
- it writes `mesh.su2`
- it writes `su2_runtime.cfg`
- it does not run `SU2_CFD`
- it does not emit `convergence_gate.v1`
- it does not change production defaults

## Required Top-Level Fields

- `schema_version`: fixed string `fairing_solid_su2_handoff_smoke.v1`
- `component`: fixed string `fairing_solid`
- `geometry_family`: fixed string `closed_solid`
- `meshing_route`: fixed string `gmsh_closed_solid_volume`
- `execution_mode`: fixed string `su2_materialization_only_no_solver`
- `source_mesh_smoke_schema`: expected `fairing_solid_mesh_handoff_smoke.v1`
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

A materialization pass means hpa-mdo can turn the synthetic fairing
`mesh_handoff.v1` into a package-native SU2 case artifact bundle without asking
the solver to run.

It does **not** mean the route is CFD-ready. The smoke uses a component-owned
`fairing_solid` wall marker, but the mesh remains a synthetic box. Solver
execution, history parsing, convergence, and real fairing geometry remain
blocking gates.

## Promotion Rule

This smoke can move the route past "missing SU2 handoff", but it cannot promote
the route to solver credibility. The next gates are:

1. real fairing geometry evidence
2. solver run
3. `convergence_gate.v1`
