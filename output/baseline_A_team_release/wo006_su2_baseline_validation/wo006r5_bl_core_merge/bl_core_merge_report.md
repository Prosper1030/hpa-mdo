# WO-006R5 BL+Core Merge Report

- Verdict: `wo006r5_core_merge_limitation_proven`
- BL+core handoff exists: `False`
- bl_mesh_handoff.v1.json emitted: `False`
- Coefficients interpretable: `False`
- Marker ownership audit: `fail`
- Mesh quality gate: `fail`
- SU2 readability smoke: `fail`

## Data Authority

| Topic | Current authority | Blocked stale value |
| --- | --- | --- |
| Design gross mass | 98.5 kg | blocked suspect P1 screening aggregate |
| Full span | 34.332286 m | 16.5 m half-span is not current truth |
| Half span | 17.166143 m | 16.5 m |
| Coefficients | non-interpretable | no-BL/probe/old smoke coefficients |

## Format Sources

- SU2 mesh file: https://su2code.github.io/docs_v7/Mesh-File/
- SU2 markers and boundary conditions: https://su2code.github.io/docs_v7/Markers-and-BC/
- Gmsh manual: https://gmsh.info/doc/texinfo/

## Blockers

- `bl_core_merge_gate`: `core_mesh_quality_gate_not_pass`
- `bl_core_merge_gate`: `owned_bl_core_coupling_incomplete`
- `bl_core_merge_gate`: `merged_mixed_su2_mesh_missing`
- `mesh_quality_gate`: `core_mesh_quality_gate_not_pass`
- `mesh_quality_gate`: `merged_bl_core_quality_not_proven`
- `su2_readability_smoke`: `merged_bl_core_su2_mesh_missing`
- `full_non_wall_boundary_surface_probe`: `full_non_wall_boundary_not_watertight`

## Engineering Caveat

This campaign is mesh/ownership evidence only. Passing software tests or writing probe SU2 files does not establish wall shear, y+, convergence, grid-pair independence, drag truth, Baseline A reopen evidence, procurement truth, or final aircraft sign-off.
