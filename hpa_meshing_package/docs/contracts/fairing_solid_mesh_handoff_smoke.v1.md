# fairing_solid_mesh_handoff_smoke.v1

`fairing_solid_mesh_handoff_smoke.v1` records the first real Gmsh mesh-handoff
smoke for the closed-solid fairing route.

It is intentionally narrow:

- it runs Gmsh on a synthetic closed-solid OCC box fixture
- it emits `mesh_handoff.v1`
- it does not run `SU2_CFD`
- it does not emit `su2_handoff.v1`
- it does not emit `convergence_gate.v1`
- it does not run BL runtime paths
- it does not change production defaults

## Required Top-Level Fields

- `schema_version`: fixed string `fairing_solid_mesh_handoff_smoke.v1`
- `component`: fixed string `fairing_solid`
- `geometry_family`: fixed string `closed_solid`
- `meshing_route`: fixed string `gmsh_closed_solid_volume`
- `execution_mode`: fixed string `real_gmsh_mesh_handoff_smoke`
- `no_su2_execution`: must be `true`
- `no_bl_runtime`: must be `true`
- `production_default_changed`: must be `false`
- `smoke_status`: `mesh_handoff_pass`, `mesh_handoff_fail`, or `unavailable`
- `mesh_handoff_status`: `written`, `missing`, or `unavailable`
- `mesh_contract`: expected `mesh_handoff.v1` when the smoke passes
- `marker_summary_status`
- `fairing_force_marker_status`
- `su2_promotion_status`
- mesh counts, bounds, artifacts, guarantees, blocking reasons, and limitations

## Pass Meaning

A pass means `fairing_solid -> closed_solid -> gmsh_closed_solid_volume` can
produce a real package-native `mesh_handoff.v1` with positive volume elements,
an authoritative `fairing_solid` wall / force marker, and a `farfield` marker.

It does **not** mean the fairing route is productized. The component-specific
marker is mesh-handoff evidence only until `su2_handoff.v1` consumes it and a
convergence gate is emitted.

## Promotion Rule

The next promotion gate is not another mesh-only pass. The route remains blocked
until:

1. `su2_handoff.v1` consumes the `fairing_solid` force marker
2. `convergence_gate.v1` reports solver comparability
