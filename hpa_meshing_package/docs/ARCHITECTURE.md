# Architecture

## Core Principle

這個 package 的正式架構是：

1. provider-aware geometry normalization
2. geometry-family-first dispatch
3. package-native meshing backend
4. package-native SU2 baseline handoff
5. convergence + provenance gating
6. mesh study aggregation for baseline promotion
7. component-family route-readiness reporting
8. component-family route smoke matrix reporting
9. fairing solid mesh-handoff smoke reporting
10. main-wing mesh-handoff smoke reporting
11. main-wing SU2-handoff smoke reporting
12. machine-readable reporting

目前不要把它理解成「任意 CAD -> 任意 mesher -> 最終可信數值」的全能框架。這一輪的正式產品線只有一條：

```text
.vsp3
  -> openvsp_surface_intersection
  -> normalized trimmed STEP
  -> thin_sheet_aircraft_assembly
  -> gmsh_thin_sheet_aircraft_assembly
  -> mesh_handoff.v1
  -> su2_handoff.v1
  -> convergence_gate.v1
  -> mesh_study.v1 (when running the study entrypoint)
```

## Layer Breakdown

### 1. Schema / Contract Layer

`src/hpa_meshing/schema.py`

- Defines `MeshJobConfig`, `GeometryProviderResult`, `MeshHandoff`, `SU2CaseHandoff`
- Defines `BaselineConvergenceGate`, `MeshStudyReport`, and the machine-readable gate sections/checks
- Keeps the artifact contracts explicit and versioned
- Lets reports, tests, and downstream tools agree on the same payload shape

### 2. Provider Layer

`src/hpa_meshing/providers/`

- Converts source geometry into a normalized geometry artifact plus topology/provenance metadata
- `openvsp_surface_intersection` is the current formal `v1` provider
- `esp_rebuilt` stays experimental and may report `not_materialized`

### 3. Geometry Classification Layer

`src/hpa_meshing/geometry/` and `src/hpa_meshing/dispatch.py`

- Resolves `geometry_family`
- Checks whether a component/family combination is allowed
- Maps family to route/backend capability

The important rule is: dispatch should depend on `geometry_family`, not on a pile of case names.

### 4. Meshing Backend Layer

`src/hpa_meshing/adapters/gmsh_backend.py`

- Owns real Gmsh execution
- Owns farfield volume generation
- Owns physical groups / marker recovery
- Owns `mesh_handoff.v1`

Current boundary:

- `gmsh_thin_sheet_aircraft_assembly` is real
- `gmsh_closed_solid_volume` has a real non-BL mesh-handoff smoke for `fairing_solid`
- `gmsh_thin_sheet_surface` has a real non-BL mesh-handoff smoke for a synthetic `main_wing` slab
- other registered routes are placeholder scaffolding for future promotion

### 5. Baseline CFD Layer

`src/hpa_meshing/adapters/su2_backend.py`

- Consumes `mesh_handoff.v1`
- Materializes `SU2_CFD` runtime config
- Writes `su2_handoff.v1`
- Parses `history.csv`
- Carries reference / force-surface provenance gates plus the baseline convergence gate

This is a baseline CFD route, not the repo's final high-quality validation framework.

### 6. Pipeline / Reporting Layer

`src/hpa_meshing/pipeline.py` and `src/hpa_meshing/reports/`

- Runs provider -> classify -> validate -> recipe -> mesh -> SU2 baseline
- Writes `report.json` / `report.md`
- Mirrors the baseline convergence gate into `report.json["convergence"]` for downstream orchestration
- Keeps failure codes and route stage explicit

### 7. Mesh Study Layer

`src/hpa_meshing/mesh_study.py`

- Resolves the default `coarse / medium / fine` presets from geometry-derived characteristic length
- Reuses `run_job(...)` so each case still follows the normal package-native mainline
- Aggregates mesh stats, CFD coefficients, and per-case `convergence_gate.v1`
- Emits `mesh_study.v1` so downstream tools can decide whether alpha sweep should even start

### 8. Component-Family Route Readiness Layer

`src/hpa_meshing/route_readiness.py`

- Reports which component families are productized versus registered scaffolding
- Keeps `aircraft_assembly` formal `v1` separate from `main_wing`, tail, and fairing future routes
- Marks `shell_v4` as a diagnostic / BL-promotion branch, not the current product route
- Exposes the policy that Gmsh should only be expected to recover core tetrahedra after hpa-mdo owns BL handoff topology
- Writes `component_family_route_readiness.v1.json` and `component_family_route_readiness.v1.md` through `hpa-mesh route-readiness`
- This is a report-only strategic artifact, not a per-run mesh artifact and not a runtime route mutation

### 9. Component-Family Route Smoke Matrix Layer

`src/hpa_meshing/component_family_smoke_matrix.py`

- Builds synthetic route-skeleton STEP fixtures for registered component families
- Runs only load / classify / validate / recipe-dispatch logic
- Writes `component_family_route_smoke_matrix.v1.json` and `.md`
- Keeps `main_wing`, tail, and fairing route skeletons outside `root_last3`
- Does not call `run_job`, Gmsh, BL runtime, SU2, or convergence gates
- Exists to decide which component family deserves the next real `mesh_handoff.v1` smoke

### 10. fairing_solid Mesh-Handoff Smoke Layer

`src/hpa_meshing/fairing_solid_mesh_handoff_smoke.py`

- Builds a synthetic closed-solid OCC box fixture
- Runs `fairing_solid -> gmsh_closed_solid_volume` through real Gmsh
- Writes `fairing_solid_mesh_handoff_smoke.v1.json` and `.md`
- Emits a real `mesh_handoff.v1` for the route-smoke fixture
- Keeps SU2, BL runtime, and production defaults off
- Records a component-specific `fairing_solid` force marker in the mesh-handoff evidence
- Keeps fairing solver promotion blocked until real fairing geometry and convergence evidence exist

### 11. fairing_solid SU2-Handoff Smoke Layer

`src/hpa_meshing/fairing_solid_su2_handoff_smoke.py`

- Consumes the synthetic closed-solid fairing `mesh_handoff.v1` smoke
- Calls the package-native SU2 materializer without executing `SU2_CFD`
- Writes `fairing_solid_su2_handoff_smoke.v1.json` and `.md`
- Emits `su2_handoff.v1`, `mesh.su2`, and `su2_runtime.cfg`
- Keeps solver execution, history parsing, convergence, and production defaults off
- Records component force-surface ownership from the `fairing_solid` marker, while keeping real-geometry and solver credibility outside the guarantee set

### 12. main_wing Mesh-Handoff Smoke Layer

`src/hpa_meshing/main_wing_mesh_handoff_smoke.py`

- Builds a synthetic thin closed-solid wing slab fixture
- Runs `main_wing -> gmsh_thin_sheet_surface` through real Gmsh
- Writes `main_wing_mesh_handoff_smoke.v1.json` and `.md`
- Emits a real `mesh_handoff.v1` for the route-smoke fixture
- Keeps SU2, BL runtime, convergence, and production defaults off
- Records component-owned `main_wing` / `farfield` markers in the mesh-handoff evidence
- Keeps main-wing SU2 promotion blocked until `su2_handoff.v1` materializes from this handoff

### 13. main_wing SU2-Handoff Smoke Layer

`src/hpa_meshing/main_wing_su2_handoff_smoke.py`

- Consumes the synthetic non-BL main-wing `mesh_handoff.v1` smoke
- Calls the package-native SU2 materializer without executing `SU2_CFD`
- Writes `main_wing_su2_handoff_smoke.v1.json` and `.md`
- Emits `su2_handoff.v1`, `mesh.su2`, and `su2_runtime.cfg`
- Keeps solver execution, history parsing, convergence, and production defaults off
- Records component force-surface ownership from the `main_wing` marker, while keeping real-geometry and solver credibility outside the guarantee set

### 14. tail_wing Mesh-Handoff Smoke Layer

`src/hpa_meshing/tail_wing_mesh_handoff_smoke.py`

- Builds a synthetic thin closed-solid tail slab fixture
- Runs `tail_wing -> gmsh_thin_sheet_surface` through real Gmsh
- Writes `tail_wing_mesh_handoff_smoke.v1.json` and `.md`
- Emits a real `mesh_handoff.v1` for the route-smoke fixture
- Keeps SU2, BL runtime, convergence, and production defaults off
- Records component-owned `tail_wing` / `farfield` markers in the mesh-handoff evidence
- Keeps tail solver promotion blocked until `su2_handoff.v1`, real tail geometry, and convergence evidence exist

### 15. tail_wing SU2-Handoff Smoke Layer

`src/hpa_meshing/tail_wing_su2_handoff_smoke.py`

- Consumes the synthetic non-BL tail-wing `mesh_handoff.v1` smoke
- Calls the package-native SU2 materializer without executing `SU2_CFD`
- Writes `tail_wing_su2_handoff_smoke.v1.json` and `.md`
- Emits `su2_handoff.v1`, `mesh.su2`, and `su2_runtime.cfg`
- Keeps solver execution, history parsing, convergence, and production defaults off
- Records component force-surface ownership from the `tail_wing` marker, while keeping real-geometry and solver credibility outside the guarantee set

### 16. tail_wing ESP-Rebuilt Geometry Smoke Layer

`src/hpa_meshing/tail_wing_esp_rebuilt_geometry_smoke.py`

- Consumes `data/blackcat_004_origin.vsp3`
- Selects the OpenVSP `Elevator` geometry as `tail_wing` / `horizontal_tail`
- Runs the experimental `esp_rebuilt` provider and writes a normalized STEP
- Writes `tail_wing_esp_rebuilt_geometry_smoke.v1.json` and `.md`
- Keeps Gmsh, mesh handoff, SU2, convergence, BL runtime, and production defaults off
- Promotes the blocker from "real tail geometry missing" to "real tail geometry mesh handoff not run"

## Real vs Placeholder Boundary

The package intentionally distinguishes between:

- registry exists
- contract exists
- real backend exists

That matters because a route can be valid in schema/dispatch but still be non-productized in the backend.

Current truth:

- `aircraft_assembly` with `openvsp_surface_intersection` is real
- `fairing_solid` has real closed-solid mesh-handoff and SU2-handoff materialization smokes on a synthetic box with component-owned force markers, but is not yet a real-geometry, solver, or convergence route
- `main_wing` has real non-BL mesh-handoff and SU2-handoff materialization smokes on a synthetic slab with component-owned force markers, but is not yet a real-geometry, solver, or convergence route
- `tail_wing` has real ESP/VSP provider geometry evidence and synthetic non-BL mesh/SU2 handoff smokes with component-owned force markers, but is not yet a real-geometry mesh, solver, or convergence route
- `horizontal_tail`, `vertical_tail`, and `fairing_vented` are not yet real meshing products in this package
- `shell_v4` evidence is useful for BL handoff promotion, but it is not a substitute for component-family productization

## Artifact Flow

```text
MeshJobConfig
  -> GeometryProviderResult
  -> GeometryClassification / GeometryValidationResult
  -> MeshRecipe
  -> mesh_handoff.v1
  -> su2_handoff.v1
  -> convergence_gate.v1
  -> mesh_study.v1
  -> component_family_route_readiness.v1
  -> component_family_route_smoke_matrix.v1
  -> fairing_solid_mesh_handoff_smoke.v1
  -> fairing_solid_su2_handoff_smoke.v1
  -> main_wing_mesh_handoff_smoke.v1
  -> main_wing_su2_handoff_smoke.v1
  -> tail_wing_esp_rebuilt_geometry_smoke.v1
  -> tail_wing_mesh_handoff_smoke.v1
  -> tail_wing_su2_handoff_smoke.v1
  -> report.json
```

The contracts are intentionally machine-readable first, then human-readable through docs and reports.
`component_family_route_readiness.v1` sits beside this per-run flow as a strategic route-status
artifact; it does not imply that a component family has run.
`component_family_route_smoke_matrix.v1` is also beside the per-run flow: it proves dispatch
visibility only and still does not imply that Gmsh or SU2 ran.
`fairing_solid_mesh_handoff_smoke.v1` is the first route-specific real Gmsh smoke
outside the formal aircraft-assembly line; it proves mesh handoff only.
`fairing_solid_su2_handoff_smoke.v1` proves that this fairing mesh handoff can
materialize an SU2 case without running the solver; it now owns the
`fairing_solid` force marker, but still leaves real geometry, solver history,
and convergence outside the guarantee set.
`main_wing_mesh_handoff_smoke.v1` adds the matching lifting-surface non-BL
route smoke; it proves the route can emit `mesh_handoff.v1` on a synthetic slab,
not that real ESP/VSP main-wing geometry or solver comparability is ready.
`main_wing_su2_handoff_smoke.v1` proves that this mesh handoff can materialize
an SU2 case without running the solver; it now owns the `main_wing` force marker,
but still leaves real geometry, solver history, and convergence outside the guarantee set.
`tail_wing_mesh_handoff_smoke.v1` adds the first tail-family real Gmsh smoke;
it proves the `tail_wing` component can emit an owned-marker `mesh_handoff.v1`
on a synthetic slab, not that horizontal/vertical tail subroutes or real tail CFD
are ready.
`tail_wing_su2_handoff_smoke.v1` proves that this mesh handoff can materialize
an SU2 case without running the solver; it now owns the `tail_wing` force marker,
but still leaves real geometry, solver history, and convergence outside the guarantee set.
`tail_wing_esp_rebuilt_geometry_smoke.v1` proves the VSP/ESP provider can
materialize the real tail source geometry, but it does not replace the missing
real-geometry mesh handoff.

## Why This Boundary Matters

- New AI / new developers can tell what is formal without reading multiple worktrees
- Baseline CFD can evolve without dragging in `origin-su2-high-quality`
- ESP/OpenCSM can stay experimental without blocking the formal package
- The next hardening step can focus on alpha sweep / force-mapping policy instead of reopening the baseline gate shape again
