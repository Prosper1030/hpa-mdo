# WO-006R6 Core Interface Repair Report

- Verdict: `wo006r6_core_quality_limitation_proven`
- BL+core handoff exists: `False`
- bl_mesh_handoff.v1.json emitted: `False`
- Coefficients interpretable: `False`
- Zero unmatched interface faces: `False`
- Mesh quality gate: `fail`
- Marker ownership audit: `fail`
- SU2 readability smoke: `fail`

## Data Authority

| Topic | Current authority | Blocked stale value |
| --- | --- | --- |
| Design gross mass | 98.5 kg | 106.828608 kg suspect screening aggregate |
| Full span | 34.332286 m | not replaced by local 16.5 m half-span |
| Half span | 17.166143 m | 16.5 m local/splice screening only |
| Coefficients | non-interpretable | no-BL/probe/old smoke coefficients |

## Format Sources

- SU2 mesh file: https://su2code.github.io/docs_v7/Mesh-File/
- SU2 markers and boundary conditions: https://su2code.github.io/docs_v7/Markers-and-BC/
- SU2 multizone: https://su2code.github.io/docs_v7/Multizone/
- Gmsh manual: https://gmsh.info/doc/texinfo/

## Blockers

- `core_interface_repair_gate`: `core_mesh_quality_gate_not_pass`
- `core_interface_repair_gate`: `owned_bl_core_coupling_incomplete`
- `core_interface_repair_gate`: `merged_mixed_su2_mesh_missing`
- `mesh_quality_gate`: `core_mesh_quality_gate_not_pass`
- `mesh_quality_gate`: `merged_bl_core_quality_not_proven`
- `marker_ownership_audit`: `final_merged_marker_ownership_not_proven`
- `su2_readability_smoke`: `merged_bl_core_su2_mesh_missing`
- `final_handoff_gate`: `probe_su2_not_final`
- `final_handoff_gate`: `final_merged_su2_missing`
- `final_handoff_gate`: `unmatched_core_interface_faces`
- `final_handoff_gate`: `unmatched_bl_boundary_faces`
- `final_handoff_gate`: `bl_core_coupling_not_pass`
- `final_handoff_gate`: `marker_ownership_not_pass`
- `final_handoff_gate`: `mesh_quality_not_pass`
- `final_handoff_gate`: `non_positive_elements_present`
- `core_interface_topology_audit`: `zero_unmatched_bl_core_interface_not_proven`
- `full_non_wall_boundary_surface_probe`: `full_non_wall_boundary_not_watertight`

## Engineering Read

The preserved core interface route still produces non-positive core quality metrics before a merged BL+core handoff can be trusted.

This is mesh/interface evidence only. Passing parser checks or writing component probes does not establish wall shear, y+, convergence, grid-pair independence, drag truth, Baseline A reopen evidence, procurement truth, or final aircraft sign-off.
