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
9. machine-readable reporting

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

## Real vs Placeholder Boundary

The package intentionally distinguishes between:

- registry exists
- contract exists
- real backend exists

That matters because a route can be valid in schema/dispatch but still be non-productized in the backend.

Current truth:

- `aircraft_assembly` with `openvsp_surface_intersection` is real
- `main_wing`, `tail_wing`, `horizontal_tail`, `vertical_tail`, `fairing_solid`, and `fairing_vented` are not yet real meshing products in this package
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
  -> report.json
```

The contracts are intentionally machine-readable first, then human-readable through docs and reports.
`component_family_route_readiness.v1` sits beside this per-run flow as a strategic route-status
artifact; it does not imply that a component family has run.
`component_family_route_smoke_matrix.v1` is also beside the per-run flow: it proves dispatch
visibility only and still does not imply that Gmsh or SU2 ran.

## Why This Boundary Matters

- New AI / new developers can tell what is formal without reading multiple worktrees
- Baseline CFD can evolve without dragging in `origin-su2-high-quality`
- ESP/OpenCSM can stay experimental without blocking the formal package
- The next hardening step can focus on alpha sweep / force-mapping policy instead of reopening the baseline gate shape again
