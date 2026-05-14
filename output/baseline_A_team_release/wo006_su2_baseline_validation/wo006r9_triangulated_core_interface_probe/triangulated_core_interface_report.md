# WO-006R9 Triangulated Core Interface Probe

This is Baseline A mesh-interface evidence only, not CFD coefficient evidence.

## Result

- status: `blocked`
- GOAL_STATUS: `INCOMPLETE`
- CFD_STATUS: `mesh_ladder_incomplete`
- coefficient interpretable: `False`
- blockers: `['bl_core_coupling_incomplete', 'owned_bl_core_coupling_incomplete', 'merged_mixed_su2_mesh_missing']`
- evidence flags: `['core_quality_repaired_by_triangulated_interface']`

## Core Mesh

- nodes: `28410`
- volume elements: `6005`
- volume element types: `{'4': 6005}`
- tetra count: `6005`
- pyramid count: `0`
- non-positive SICN/SIGE/volume: `0` / `0` / `0`

## Coupling

- coupling status: `partial`
- unmatched core faces: `126`
- unmatched BL faces: `6272`

## Engineering Read

Triangulated preserved core boundary removes the R7 bad-pyramid family, but Baseline A still lacks a merged BL+core SU2 handoff.
