# component_family_route_smoke_matrix.v1

`component_family_route_smoke_matrix.v1` is a report-only contract for checking
that component-family route skeletons are visible before choosing the next
high-fidelity repair target.

It is intentionally **pre-mesh**:

- it does not run Gmsh
- it does not run boundary-layer runtime paths
- it does not run `SU2_CFD`
- it does not emit `mesh_handoff.v1`
- it does not emit `su2_handoff.v1`
- it does not emit `convergence_gate.v1`

A pass means the component can be loaded from a synthetic route-skeleton STEP,
classified into its geometry family, validated against component/family rules,
and resolved to a registered meshing route. It is architecture evidence only,
not a production mesh pass, solver pass, BL promotion, or CFD credibility claim.

## Required Top-Level Fields

- `schema_version`: fixed string `component_family_route_smoke_matrix.v1`
- `target_pipeline`: fixed target pipeline label
- `execution_mode`: fixed string `pre_mesh_dispatch_smoke`
- `no_gmsh_execution`: must be `true`
- `no_su2_execution`: must be `true`
- `report_status`: `completed` or `failed`
- `rows`: component-family route smoke rows
- `scope_policy`: explicit exclusions for `root_last3`, `root_last4`, BL runtime, Gmsh, and SU2
- `global_limitations`: human-readable anti-overclaiming text
- `next_actions`: recommended next route-promotion actions

## Row Fields

Each row represents one component route skeleton:

- `component`
- `fixture_kind`
- `source_path`
- `geometry_source`
- `geometry_family`
- `classification_provenance`
- `validation_status`
- `recipe_status`
- `smoke_status`
- `productization_status`
- `route_role`
- `meshing_route`
- `backend`
- `backend_capability`
- `mesh_handoff_status`
- `su2_handoff_status`
- `convergence_gate_status`
- `promotion_status`
- `blocking_reasons`
- `guarantees`
- `limitations`

## Current Components

The matrix currently covers:

- `aircraft_assembly`
- `main_wing`
- `tail_wing`
- `horizontal_tail`
- `vertical_tail`
- `fairing_solid`
- `fairing_vented`

## Promotion Rule

This contract cannot promote a component family by itself. A component family
is still blocked before product use until real route evidence exists:

1. provider materialization or formal direct-CAD source
2. route-specific real mesh smoke
3. `mesh_handoff.v1`
4. `su2_handoff.v1`
5. `convergence_gate.v1`
6. for BL routes only: owned transition sleeve / interface-loop handoff
