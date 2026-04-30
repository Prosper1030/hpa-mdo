# fairing_solid_real_su2_handoff_probe.v1

`fairing_solid_real_su2_handoff_probe.v1` records SU2 handoff materialization
from the real fairing mesh handoff probe.

It is intentionally solver-free:

- it consumes `fairing_solid_real_mesh_handoff_probe.v1`
- it requires the upstream real mesh probe to have written `mesh_handoff.v1`
- it writes `su2_handoff.v1`
- it writes `mesh.su2`
- it writes `su2_runtime.cfg`
- it does not run `SU2_CFD`
- it does not emit `convergence_gate.v1`
- it does not run BL runtime
- it does not change production defaults

## Required Top-Level Fields

- `schema_version`: fixed string `fairing_solid_real_su2_handoff_probe.v1`
- `component`: fixed string `fairing_solid`
- `source_fixture`
- `geometry_provider`: fixed string `openvsp_surface_intersection`
- `geometry_family`: fixed string `closed_solid`
- `meshing_route`: fixed string `gmsh_closed_solid_volume`
- `execution_mode`: fixed string `real_mesh_handoff_su2_materialization_only_no_solver`
- `source_mesh_probe_schema`: expected `fairing_solid_real_mesh_handoff_probe.v1`
- `materialization_status`
- `source_mesh_probe_status`
- `source_mesh_handoff_status`
- `provider_status`
- `fairing_force_marker_status`
- `su2_contract`
- `input_mesh_contract`
- `solver_execution_status`
- `convergence_gate_status`
- `wall_marker_status`
- `force_surface_scope`
- `component_force_ownership_status`
- `reference_geometry_status`
- case paths, mesh counts, guarantees, blocking reasons, and limitations

## Pass Meaning

A materialization pass means hpa-mdo can consume the real fairing
`mesh_handoff.v1` and emit a package-native SU2 case bundle with a component-owned
`fairing_solid` force marker.

It does not mean the fairing route is CFD-ready. The current real fairing
materialization is still blocked by solver execution, missing convergence
evidence, and reference-geometry warning status.

## Promotion Rule

This probe moves `fairing_solid` past "real SU2 handoff missing." It cannot
promote the route to solver credibility until:

1. fairing reference quantities are explicit enough for coefficient reporting
2. `SU2_CFD` runs on the real fairing case
3. `convergence_gate.v1` records the solver and provenance outcome
