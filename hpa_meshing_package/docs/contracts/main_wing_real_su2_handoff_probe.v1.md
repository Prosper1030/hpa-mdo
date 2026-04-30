# main_wing_real_su2_handoff_probe.v1

`main_wing_real_su2_handoff_probe.v1` records SU2 handoff materialization from
the real ESP/VSP main-wing mesh handoff.

It is intentionally solver-free:

- it consumes `main_wing_real_mesh_handoff_probe.v1`
- it requires the source mesh probe to have written `mesh_handoff.v1`
- it writes `su2_handoff.v1`
- it writes `mesh.su2`
- it writes `su2_runtime.cfg`
- it uses the HPA standard flow condition `V=6.5 m/s`
- it records component-owned `main_wing` force-marker ownership
- it does not run `SU2_CFD`
- it does not emit `convergence_gate.v1`
- it does not run BL runtime
- it does not change production defaults

## Required Top-Level Fields

- `schema_version`: fixed string `main_wing_real_su2_handoff_probe.v1`
- `component`: fixed string `main_wing`
- `source_fixture`
- `geometry_provider`: fixed string `esp_rebuilt`
- `geometry_family`: fixed string `thin_sheet_lifting_surface`
- `meshing_route`: fixed string `gmsh_thin_sheet_surface`
- `execution_mode`: fixed string `real_mesh_handoff_su2_materialization_only_no_solver`
- `source_mesh_probe_schema`: expected `main_wing_real_mesh_handoff_probe.v1`
- `no_su2_execution`: must be `true`
- `no_convergence_gate`: must be `true`
- `no_bl_runtime`: must be `true`
- `production_default_changed`: must be `false`
- `materialization_status`
- `source_mesh_probe_status`
- `source_mesh_handoff_status`
- `marker_summary_status`
- `su2_contract`
- `input_mesh_contract`
- `solver_execution_status`
- `convergence_gate_status`
- `run_status`
- `wall_marker_status`
- `force_surface_scope`
- `component_force_ownership_status`
- `reference_geometry_status`
- `observed_velocity_mps`
- source, case, mesh, SU2, runtime, and history paths
- mesh counts when available
- guarantees, blocking reasons, and limitations

## Pass Meaning

`su2_handoff_written` means hpa-mdo can materialize a package-native SU2 case
from the real main-wing `mesh_handoff.v1`. It proves handoff wiring, marker
ownership, and flow-condition propagation from real geometry-derived mesh
evidence.

It does **not** mean the route is CFD-ready. The solver is not executed, no
history exists, and no convergence gate is emitted by this probe. The upstream
mesh is still a coarse bounded probe rather than production default sizing.

## Promotion Rule

This probe can move the real main-wing route past "real SU2 handoff missing".
It cannot promote the route to aerodynamic credibility until:

1. `SU2_CFD` executes from this real handoff
2. `convergence_gate.v1` passes
3. reference chord and moment-origin provenance pass
4. mesh sizing / BL policy is promoted separately
