# WO-006R4 BL Ownership Repair Campaign Report

Verdict: `wo006r4_adapter_limitation_proven`

## Authority Basis

- Mass authority: `98.5 kg`.
- Span authority: `34.332286 m` full / `17.166143 m` half.
- References: Sref `33.420059598 m^2`, Cref `1.003721543 m`, Bref `34.332286000 m`.
- `106.828608 kg` remains suspect screening aggregate, and `16.5 m` remains local/splice screening only; both are not current truth.
- External authority shape changed: `false`.

## Route Decision

- BL/y+ handoff exists: `False`
- Coefficient interpretable: `False`
- Baseline A reopen status: `not_evaluated`
- Selected route: `none`

The campaign rejected a BL handoff because the only successful current-GO near-wall construction is an owned BL block without a conformal merged core and SU2 writer. That is not enough to expose `wing_wall` plus `farfield` in one credible viscous SU2 mesh.

## Attempts

### wo006r3_final_policy_attempt_01_bl_0p20

- route: `gmsh_topological_bl_extrude_boundary_layer`
- status: `blocked`
- accepted for: exact remaining DAE31-family blocker localization
- rejected for: BL/y+ handoff
- failure mode: `Gmsh HXT PLC segment/facet intersection`

### wo006r3_final_policy_attempt_02_bl_0p25

- route: `gmsh_topological_bl_extrude_boundary_layer`
- status: `blocked`
- accepted for: exact remaining DAE31-family blocker localization
- rejected for: BL/y+ handoff
- failure mode: `Gmsh HXT PLC segment/facet intersection`

### r3_shorter_diagonalization_on_bl_exploratory

- route: `blind_shorter_diagonalization_applied_to_bl`
- status: `rejected_workaround`
- accepted for: no-BL high-mesh faceted handoff only
- rejected for: BL extrusion
- failure mode: `Gmsh Unknown curve -1550`

### owned_bl_block_current_go_32x2

- route: `mesh_native_owned_bl_block_without_core_merge`
- status: `partial`
- accepted for: wall BL topology construction and first-layer basis
- rejected for: final SU2 BL handoff
- failure mode: `owned BL block has no conformal core merge or SU2 writer yet`

### owned_bl_core_preserve_interface_alg1

- route: `mesh_native_owned_bl_block_core_tet_probe`
- status: `blocked`
- accepted for: test whether core can preserve BL outer interface
- rejected for: final BL handoff because preserved core volume quality failed and wake/span-cap ownership is not yet a conformal merged BL+core topology
- failure mode: `core_mesh_quality_failed_and_owned_bl_core_coupling_partial`

### owned_bl_core_remesh_hxt

- route: `mesh_native_owned_bl_block_core_tet_probe`
- status: `rejected_workaround`
- accepted for: test whether remeshed core hides interface issues
- rejected for: final BL handoff because Gmsh changed the BL-core interface mesh
- failure mode: `core_interface_remeshed_not_conformal_to_owned_bl_block`

### owned_bl_core_remesh_alg1

- route: `mesh_native_owned_bl_block_core_tet_probe`
- status: `rejected_workaround`
- accepted for: test whether non-HXT remeshed core avoids quality failure
- rejected for: final BL handoff because Gmsh changed the BL-core interface mesh
- failure mode: `core_interface_remeshed_not_conformal_to_owned_bl_block`

## Smallest Blocker

current adapter lacks a conformal owned BL block + core merge/writer; Gmsh-owned BL extrusion still fails on DAE31-family PLC topology, while the mesh-native owned-BL core probes either fail preserved core quality or remesh the interface.

Concrete next repair target:

write a conformal BL+core ownership merge that preserves bl_outer_interface, wake_cut, and span_cap faces, then export mixed prisms/pyramids/tets to SU2 with wing_wall/farfield ownership and quality gates.

## Geometry Deviation

Max owned-BL wall-to-current-wing nearest distance: `0 m`.
No R4 adapter-level shape cleanup was applied.

## BL / y+ Basis

First layer `5e-05 m`, layers `24`, growth `1.24`, estimated y+ `1.042`.
This is estimated sizing, not postprocessed surface y+.

## Coefficients

No coefficient is interpretable. R3 no-BL coefficients, old Black Cat coefficients, old short BL smoke, and any no-convergence smoke remain route/readability evidence only.

## Blockers

- `wo006r3_final_policy_attempt_01_bl_0p20`: `Gmsh HXT PLC segment/facet intersection`; next `write a conformal BL+core ownership merge that preserves bl_outer_interface, wake_cut, and span_cap faces, then export mixed prisms/pyramids/tets to SU2 with wing_wall/farfield ownership and quality gates.`
- `wo006r3_final_policy_attempt_02_bl_0p25`: `Gmsh HXT PLC segment/facet intersection`; next `write a conformal BL+core ownership merge that preserves bl_outer_interface, wake_cut, and span_cap faces, then export mixed prisms/pyramids/tets to SU2 with wing_wall/farfield ownership and quality gates.`
- `r3_shorter_diagonalization_on_bl_exploratory`: `Gmsh Unknown curve -1550`; next `write a conformal BL+core ownership merge that preserves bl_outer_interface, wake_cut, and span_cap faces, then export mixed prisms/pyramids/tets to SU2 with wing_wall/farfield ownership and quality gates.`
- `owned_bl_block_current_go_32x2`: `owned BL block has no conformal core merge or SU2 writer yet`; next `write a conformal BL+core ownership merge that preserves bl_outer_interface, wake_cut, and span_cap faces, then export mixed prisms/pyramids/tets to SU2 with wing_wall/farfield ownership and quality gates.`
- `owned_bl_core_preserve_interface_alg1`: `core_mesh_quality_failed_and_owned_bl_core_coupling_partial`; next `write a conformal BL+core ownership merge that preserves bl_outer_interface, wake_cut, and span_cap faces, then export mixed prisms/pyramids/tets to SU2 with wing_wall/farfield ownership and quality gates.`
- `owned_bl_core_remesh_hxt`: `core_interface_remeshed_not_conformal_to_owned_bl_block`; next `write a conformal BL+core ownership merge that preserves bl_outer_interface, wake_cut, and span_cap faces, then export mixed prisms/pyramids/tets to SU2 with wing_wall/farfield ownership and quality gates.`
- `owned_bl_core_remesh_alg1`: `core_interface_remeshed_not_conformal_to_owned_bl_block`; next `write a conformal BL+core ownership merge that preserves bl_outer_interface, wake_cut, and span_cap faces, then export mixed prisms/pyramids/tets to SU2 with wing_wall/farfield ownership and quality gates.`

## Engineering Caveats

- This is adapter limitation evidence, not a final CFD validation.
- A valid workaround must preserve geometry or report measured deviation; R4 does not change the source shape.
- Low-Re HPA drag remains transition-sensitive; SA/SST/laminar setup cannot be chosen from this mesh route alone.
- A future pass still needs marker audit, no-slip wall BCs, postprocessed y+, convergence, and grid-pair evidence before CL/CD is used.

## Reviewer Prompt

```text
Review WO-006R4 as an adversarial aerospace/CFD reviewer. Check route_decision.json, blocker_register.csv, surface_geometry_deviation_report.md, yplus_and_boundary_layer_basis.md, solver_evidence_gate.json, and any core_probe_artifacts. Decide whether the verdict wo006r4_adapter_limitation_proven is supported without hiding topology by coarsening/remeshing, changing Baseline A authority shape, or promoting no-BL/unconverged coefficients.
```
