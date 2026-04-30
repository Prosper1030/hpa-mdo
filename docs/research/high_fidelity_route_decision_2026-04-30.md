# High-Fidelity Route Decision (2026-04-30)

## Decision

The high-fidelity automation mainline must move from a single `shell_v4` fixture
repair loop to a component-family route architecture.

The long-term target is:

```text
VSP / ESP geometry
  -> component-family classification
  -> route selection
  -> meshability gates
  -> Gmsh mesh handoff
  -> SU2 baseline / convergence reporting
```

for arbitrary human-powered-aircraft:

- main wing
- tail wing / horizontal tail / vertical tail
- fairing solid / vented fairing

`shell_v4` remains valuable, but its role is now diagnostic and promotional:
it can prove whether a boundary-layer route has enough owned topology to be
promoted. It must not be treated as the product route just because one hard
fixture becomes greener.

## Why This Decision Exists

The `shell_v1 -> shell_v4` history is still useful:

- `shell_v1` proved the route could reach a rough 3D volume smoke.
- `shell_v2` compressed the worst tip family into a smaller residual set.
- `shell_v3` moved the root cause upstream and produced a frozen geometry /
  coarse-CFD reference.
- `shell_v4` correctly opened a real boundary-layer / solver-validation branch.

That progression was not wasted effort. The problem is that the active
`root_last3` work has crossed from route hardening into narrow topology
microscopy. The evidence pattern is no longer a clean monotonic improvement:
`failed_steiner`, `segment_facet_intersection`, `loop_not_closed`, inferred
sleeve ownership, and missing or inferred BL-to-core handoff ownership all
point to the same architecture boundary.

The missing object is not another surface-id patch. The missing product
capability is an hpa-mdo-owned handoff topology that Gmsh only consumes after
hpa-mdo has already guaranteed the boundary.

## Product-Line Rule

Do not promote a component family by making one `shell_v4` fixture pass.

Promote a component family only when the route has:

1. provider materialization or a formal direct-CAD source
2. geometry-family classification
3. route-specific mesh smoke
4. `mesh_handoff.v1`
5. `su2_handoff.v1`
6. `convergence_gate.v1`
7. for BL routes only: owned transition sleeve / interface-loop handoff

This keeps "it ran" separate from "it is comparable", and keeps "diagnostic
evidence improved" separate from "this is a productized route".

## Component-Family Readiness

The machine-readable readiness surface is:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli route-readiness \
  --out .tmp/runs/component_family_route_readiness
```

It writes:

- `component_family_route_readiness.v1.json`
- `component_family_route_readiness.v1.md`

A committed snapshot is kept at:

- `hpa_meshing_package/docs/reports/component_family_route_readiness.v1.json`
- `hpa_meshing_package/docs/reports/component_family_route_readiness.v1.md`

The companion pre-mesh dispatch smoke matrix is:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli component-family-smoke-matrix \
  --out .tmp/runs/component_family_route_smoke_matrix
```

It writes:

- `component_family_route_smoke_matrix.v1.json`
- `component_family_route_smoke_matrix.v1.md`

A committed snapshot is kept at:

- `hpa_meshing_package/docs/reports/component_family_route_smoke_matrix.v1.json`
- `hpa_meshing_package/docs/reports/component_family_route_smoke_matrix.v1.md`

This smoke matrix is not a mesh pass. It only proves that main-wing, tail, and
fairing route skeletons are visible, classified, and dispatched outside
`root_last3`.

The first route-specific real Gmsh smoke selected from that matrix is:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli fairing-solid-mesh-handoff-smoke \
  --out .tmp/runs/fairing_solid_mesh_handoff_smoke
```

It writes:

- `fairing_solid_mesh_handoff_smoke.v1.json`
- `fairing_solid_mesh_handoff_smoke.v1.md`

A committed snapshot is kept at:

- `hpa_meshing_package/docs/reports/fairing_solid_mesh_handoff_smoke/fairing_solid_mesh_handoff_smoke.v1.json`
- `hpa_meshing_package/docs/reports/fairing_solid_mesh_handoff_smoke/fairing_solid_mesh_handoff_smoke.v1.md`

This smoke emits a real `mesh_handoff.v1` for `fairing_solid ->
gmsh_closed_solid_volume`. It now includes a component-specific `fairing_solid`
force marker in the mesh-handoff evidence. The SU2 backend can materialize a
`su2_handoff.v1` from that marker without running `SU2_CFD`, but the committed
route evidence is still not a solver route and `convergence_gate.v1` is
intentionally absent.

The matching non-BL main-wing mesh smoke is:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli main-wing-mesh-handoff-smoke \
  --out .tmp/runs/main_wing_mesh_handoff_smoke
```

It writes:

- `main_wing_mesh_handoff_smoke.v1.json`
- `main_wing_mesh_handoff_smoke.v1.md`

A committed snapshot is kept at:

- `hpa_meshing_package/docs/reports/main_wing_mesh_handoff_smoke/main_wing_mesh_handoff_smoke.v1.json`
- `hpa_meshing_package/docs/reports/main_wing_mesh_handoff_smoke/main_wing_mesh_handoff_smoke.v1.md`

This smoke emits a real `mesh_handoff.v1` for `main_wing ->
gmsh_thin_sheet_surface` on a synthetic thin closed-solid wing slab with
component-owned `main_wing` / `farfield` markers. It is not a BL route, not real
aerodynamic wing geometry, not a solver handoff, and not a convergence claim.
Its engineering value is narrower but important: the main-wing family now has a
real package-native mesh-handoff artifact outside `root_last3`, and the marker
scope no longer collapses to whole-aircraft force accounting.

The first main-wing SU2 handoff materialization smoke is:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli main-wing-su2-handoff-smoke \
  --out .tmp/runs/main_wing_su2_handoff_smoke
```

It writes:

- `main_wing_su2_handoff_smoke.v1.json`
- `main_wing_su2_handoff_smoke.v1.md`

A committed snapshot is kept at:

- `hpa_meshing_package/docs/reports/main_wing_su2_handoff_smoke/main_wing_su2_handoff_smoke.v1.json`
- `hpa_meshing_package/docs/reports/main_wing_su2_handoff_smoke/main_wing_su2_handoff_smoke.v1.md`

This smoke emits `su2_handoff.v1`, `mesh.su2`, and `su2_runtime.cfg` without
running `SU2_CFD`. It now consumes the component-owned `main_wing` wall marker
and reports `force_surface_scope=component_subset`. It deliberately keeps the
remaining engineering blockers visible: the geometry is still synthetic, solver
history is absent, and convergence has not been evaluated.

The current expected strategic reading is:

| Component family | Current role | Productized? | Next useful promotion gate |
| --- | --- | --- | --- |
| `aircraft_assembly` | current product line | yes, formal `v1` | mesh-study / convergence promotion |
| `main_wing` | experimental + diagnostic | no | real ESP/VSP geometry smoke, then solver/convergence smoke |
| `tail_wing` / `horizontal_tail` / `vertical_tail` | registered future route | no | tail-specific geometry and mesh smoke |
| `fairing_solid` | registered future route | no | committed SU2 materialization smoke, then solver/convergence gate |
| `fairing_vented` | registered future route | no | perforation ownership and marker contract |

## Boundary-Layer Promotion Policy

The BL route is not abandoned, but it becomes promotion-only.

A BL route can ask Gmsh to do only core tetrahedralization when hpa-mdo already
owns:

- transition sleeve object
- transition rings
- receiver faces
- interface loops
- layer-drop event mapping
- BL-to-core handoff boundary

If any of those are inferred or missing, the correct result is still a handoff
insufficiency. Inferred sleeve ownership cannot pass because it still asks Gmsh
to recover boundary topology that hpa-mdo has not actually defined.

## Gmsh Source Policy

`/Volumes/Samsung SSD/external-src/gmsh` and the previous forensic worktree are
useful for understanding Gmsh boundary recovery. They are not the primary
product-repair path.

Use Gmsh source for:

- forensic instrumentation
- throw-site localization
- minimal repro construction
- distinguishing hpa-mdo topology debt from a true Gmsh bug

Do not use a Gmsh fork as the default answer. A fork is only justified after a
reproducible, cross-fixture Gmsh bug remains after hpa-mdo owns the handoff
topology.

## New Agent Operating Rules

Every future high-fidelity task should answer these before editing code:

1. Which pipeline layer does this advance?
2. Does it help arbitrary main-wing / tail / fairing automation?
3. Is this a product route, diagnostic route, or research branch?
4. What evidence promotes it, and what evidence stops it?

If a task cannot answer those questions, it should not become a repair loop.

## Next Two Tasks

1. Replace the synthetic main-wing slab with real ESP/VSP main-wing geometry
   evidence before any solver/convergence claim.
2. Write the committed `fairing_solid` `su2_handoff.v1` materialization report
   artifact, then add the next tail-family non-BL mesh-handoff smoke.
