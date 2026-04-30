# main_wing_mesh_handoff_smoke.v1

`main_wing_mesh_handoff_smoke.v1` records a real Gmsh non-BL mesh-handoff
smoke for the registered main-wing route.

It is intentionally narrow:

- it runs Gmsh on a synthetic thin closed-solid wing slab
- it emits `mesh_handoff.v1`
- it does not run boundary-layer runtime
- it does not run `SU2_CFD`
- it does not emit `su2_handoff.v1`
- it does not emit `convergence_gate.v1`
- it does not change production defaults

## Required Top-Level Fields

- `schema_version`: fixed string `main_wing_mesh_handoff_smoke.v1`
- `component`: fixed string `main_wing`
- `geometry_family`: fixed string `thin_sheet_lifting_surface`
- `meshing_route`: fixed string `gmsh_thin_sheet_surface`
- `execution_mode`: fixed string `real_gmsh_non_bl_mesh_handoff_smoke`
- `no_su2_execution`: must be `true`
- `no_bl_runtime`: must be `true`
- `production_default_changed`: must be `false`
- `smoke_status`: `mesh_handoff_pass`, `mesh_handoff_fail`, or `unavailable`
- `mesh_handoff_status`: `written`, `missing`, or `unavailable`
- `mesh_contract`: expected `mesh_handoff.v1` when the smoke passes
- `marker_summary_status`
- `wall_marker_status`
- `su2_promotion_status`
- mesh counts, bounds, artifacts, guarantees, blocking reasons, and limitations

## Pass Meaning

A pass means `main_wing -> thin_sheet_lifting_surface ->
gmsh_thin_sheet_surface` can produce a real package-native `mesh_handoff.v1`
on a synthetic non-BL fixture with positive volume elements and generic
`aircraft` / `farfield` markers.

It does **not** mean the main-wing route is productized. It is not real
aerodynamic wing geometry, not a BL promotion, not a solver handoff, and not a
convergence claim.

## Promotion Rule

The next promotion gate is not another mesh-only pass. The route remains
blocked until:

1. `su2_handoff.v1` materializes from the non-BL main-wing mesh handoff
2. real main-wing geometry evidence is available
3. `convergence_gate.v1` reports solver comparability
