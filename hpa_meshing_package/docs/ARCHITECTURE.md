# Architecture

## Core Principle

這個 package 的正式架構是：

1. provider-aware geometry normalization
2. geometry-family-first dispatch
3. package-native meshing backend
4. package-native SU2 baseline handoff
5. provenance-first reporting

目前不要把它理解成「任意 CAD -> 任意 mesher -> 最終可信數值」的全能框架。這一輪的正式產品線只有一條：

```text
.vsp3
  -> openvsp_surface_intersection
  -> normalized trimmed STEP
  -> thin_sheet_aircraft_assembly
  -> gmsh_thin_sheet_aircraft_assembly
  -> mesh_handoff.v1
  -> su2_handoff.v1
```

## Layer Breakdown

### 1. Schema / Contract Layer

`src/hpa_meshing/schema.py`

- Defines `MeshJobConfig`, `GeometryProviderResult`, `MeshHandoff`, `SU2CaseHandoff`
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
- Carries reference and force-surface provenance gates

This is a baseline CFD route, not the repo's final high-quality validation framework.

### 6. Pipeline / Reporting Layer

`src/hpa_meshing/pipeline.py` and `src/hpa_meshing/reports/`

- Runs provider -> classify -> validate -> recipe -> mesh -> SU2 baseline
- Writes `report.json` / `report.md`
- Keeps failure codes and route stage explicit

## Real vs Placeholder Boundary

The package intentionally distinguishes between:

- registry exists
- contract exists
- real backend exists

That matters because a route can be valid in schema/dispatch but still be non-productized in the backend.

Current truth:

- `aircraft_assembly` with `openvsp_surface_intersection` is real
- `main_wing`, `tail_wing`, `fairing_solid`, `fairing_vented` are not yet real meshing products in this package

## Artifact Flow

```text
MeshJobConfig
  -> GeometryProviderResult
  -> GeometryClassification / GeometryValidationResult
  -> MeshRecipe
  -> mesh_handoff.v1
  -> su2_handoff.v1
  -> report.json
```

The contracts are intentionally machine-readable first, then human-readable through docs and reports.

## Why This Boundary Matters

- New AI / new developers can tell what is formal without reading multiple worktrees
- Baseline CFD can evolve without dragging in `origin-su2-high-quality`
- ESP/OpenCSM can stay experimental without blocking the formal package
- The next hardening step can focus on convergence gates instead of reopening architecture again
