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
10. main-wing ESP-rebuilt geometry smoke reporting
11. main-wing real mesh-handoff probe reporting
12. main-wing mesh-handoff smoke reporting
13. main-wing SU2-handoff smoke reporting
14. machine-readable reporting

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

### 10. fairing_solid Real Geometry Smoke Layer

`src/hpa_meshing/fairing_solid_real_geometry_smoke.py`

- Consumes the real fairing `best_design.vsp3` artifact from the external fairing project when present
- Selects an OpenVSP `Fuselage` as the fairing candidate
- Runs `openvsp_surface_intersection` and writes a normalized STEP
- Records closed-solid topology evidence (`1 body / 8 surfaces / 1 volume` in the current committed report)
- Keeps Gmsh meshing, mesh handoff, SU2, convergence, BL runtime, and production defaults off
- Promotes the blocker from "real fairing geometry missing" to "real fairing geometry mesh handoff not run"

### 11. fairing_solid Real Mesh-Handoff Probe Layer

`src/hpa_meshing/fairing_solid_real_mesh_handoff_probe.py`

- Consumes the real fairing geometry smoke before invoking Gmsh
- Runs `fairing_solid -> gmsh_closed_solid_volume` in a bounded child process with coarse probe sizing
- Writes `fairing_solid_real_mesh_handoff_probe.v1.json` and `.md`
- Current committed evidence writes `mesh_handoff.v1` with `fairing_solid` / `farfield` markers
- Keeps SU2, BL runtime, convergence, and production defaults off
- Promotes the blocker from "real fairing geometry mesh handoff not run" to "real fairing SU2 handoff not run"

### 12. fairing_solid Mesh-Handoff Smoke Layer

`src/hpa_meshing/fairing_solid_mesh_handoff_smoke.py`

- Builds a synthetic closed-solid OCC box fixture
- Runs `fairing_solid -> gmsh_closed_solid_volume` through real Gmsh
- Writes `fairing_solid_mesh_handoff_smoke.v1.json` and `.md`
- Emits a real `mesh_handoff.v1` for the route-smoke fixture
- Keeps SU2, BL runtime, and production defaults off
- Records a component-specific `fairing_solid` force marker in the mesh-handoff evidence
- Keeps fairing solver promotion blocked until real-geometry SU2 handoff and convergence evidence exist

### 13. fairing_solid SU2-Handoff Smoke Layer

`src/hpa_meshing/fairing_solid_su2_handoff_smoke.py`

- Consumes the synthetic closed-solid fairing `mesh_handoff.v1` smoke
- Calls the package-native SU2 materializer without executing `SU2_CFD`
- Writes `fairing_solid_su2_handoff_smoke.v1.json` and `.md`
- Emits `su2_handoff.v1`, `mesh.su2`, and `su2_runtime.cfg`
- Keeps solver execution, history parsing, convergence, and production defaults off
- Records component force-surface ownership from the `fairing_solid` marker, while keeping real-geometry SU2 handoff and solver credibility outside the guarantee set

### 14. main_wing ESP-Rebuilt Geometry Smoke Layer

`src/hpa_meshing/main_wing_esp_rebuilt_geometry_smoke.py`

- Consumes `data/blackcat_004_origin.vsp3`
- Selects the OpenVSP `Main Wing` geometry as `main_wing`
- Runs the experimental `esp_rebuilt` provider and writes a normalized STEP
- Writes `main_wing_esp_rebuilt_geometry_smoke.v1.json` and `.md`
- Keeps Gmsh, mesh handoff, SU2, convergence, BL runtime, and production defaults off
- Promotes the blocker from "real main-wing geometry missing" to "real main-wing geometry mesh handoff not run"

### 15. main_wing Real Mesh-Handoff Probe Layer

`src/hpa_meshing/main_wing_real_mesh_handoff_probe.py`

- Consumes the real ESP-rebuilt main-wing geometry
- Invokes the current `gmsh_thin_sheet_surface` route in a bounded child process
- Records `mesh_handoff_timeout` for the current committed evidence
- Writes `main_wing_real_mesh_handoff_probe.v1.json` and `.md`
- Keeps BL runtime, SU2, convergence, and production defaults off
- Makes the current blocker explicit: 2D completes, but 3D times out during volume insertion before `mesh_handoff.v1`

### 16. main_wing Mesh-Handoff Smoke Layer

`src/hpa_meshing/main_wing_mesh_handoff_smoke.py`

- Builds a synthetic thin closed-solid wing slab fixture
- Runs `main_wing -> gmsh_thin_sheet_surface` through real Gmsh
- Writes `main_wing_mesh_handoff_smoke.v1.json` and `.md`
- Emits a real `mesh_handoff.v1` for the route-smoke fixture
- Keeps SU2, BL runtime, convergence, and production defaults off
- Records component-owned `main_wing` / `farfield` markers in the mesh-handoff evidence
- Keeps main-wing SU2 promotion blocked until `su2_handoff.v1` materializes from this handoff

### 17. main_wing SU2-Handoff Smoke Layer

`src/hpa_meshing/main_wing_su2_handoff_smoke.py`

- Consumes the synthetic non-BL main-wing `mesh_handoff.v1` smoke
- Calls the package-native SU2 materializer without executing `SU2_CFD`
- Writes `main_wing_su2_handoff_smoke.v1.json` and `.md`
- Emits `su2_handoff.v1`, `mesh.su2`, and `su2_runtime.cfg`
- Keeps solver execution, history parsing, convergence, and production defaults off
- Records component force-surface ownership from the `main_wing` marker, while keeping real-geometry and solver credibility outside the guarantee set

### 18. tail_wing Mesh-Handoff Smoke Layer

`src/hpa_meshing/tail_wing_mesh_handoff_smoke.py`

- Builds a synthetic thin closed-solid tail slab fixture
- Runs `tail_wing -> gmsh_thin_sheet_surface` through real Gmsh
- Writes `tail_wing_mesh_handoff_smoke.v1.json` and `.md`
- Emits a real `mesh_handoff.v1` for the route-smoke fixture
- Keeps SU2, BL runtime, convergence, and production defaults off
- Records component-owned `tail_wing` / `farfield` markers in the mesh-handoff evidence
- Keeps tail solver promotion blocked until `su2_handoff.v1`, real tail geometry, and convergence evidence exist

### 19. tail_wing SU2-Handoff Smoke Layer

`src/hpa_meshing/tail_wing_su2_handoff_smoke.py`

- Consumes the synthetic non-BL tail-wing `mesh_handoff.v1` smoke
- Calls the package-native SU2 materializer without executing `SU2_CFD`
- Writes `tail_wing_su2_handoff_smoke.v1.json` and `.md`
- Emits `su2_handoff.v1`, `mesh.su2`, and `su2_runtime.cfg`
- Keeps solver execution, history parsing, convergence, and production defaults off
- Records component force-surface ownership from the `tail_wing` marker, while keeping real-geometry and solver credibility outside the guarantee set

### 20. tail_wing ESP-Rebuilt Geometry Smoke Layer

`src/hpa_meshing/tail_wing_esp_rebuilt_geometry_smoke.py`

- Consumes `data/blackcat_004_origin.vsp3`
- Selects the OpenVSP `Elevator` geometry as `tail_wing` / `horizontal_tail`
- Runs the experimental `esp_rebuilt` provider and writes a normalized STEP
- Writes `tail_wing_esp_rebuilt_geometry_smoke.v1.json` and `.md`
- Keeps Gmsh, mesh handoff, SU2, convergence, BL runtime, and production defaults off
- Promotes the blocker from "real tail geometry missing" to "real tail geometry mesh handoff not run"

### 21. tail_wing Real Mesh-Handoff Probe Layer

`src/hpa_meshing/tail_wing_real_mesh_handoff_probe.py`

- Consumes the real ESP-rebuilt tail geometry
- Invokes the current `gmsh_thin_sheet_surface` route without SU2
- Records `mesh_handoff_blocked` when the provider geometry is surface-only
- Writes `tail_wing_real_mesh_handoff_probe.v1.json` and `.md`
- Keeps BL runtime, SU2, convergence, and production defaults off
- Makes the current volume-handoff blocker explicit: the route expects OCC volumes

### 22. tail_wing Surface Mesh Probe Layer

`src/hpa_meshing/tail_wing_surface_mesh_probe.py`

- Consumes the real ESP-rebuilt tail geometry
- Imports the surface-only STEP directly into Gmsh
- Emits a 2D surface mesh with a `tail_wing` physical group
- Writes `tail_wing_surface_mesh_probe.v1.json` and `.md`
- Keeps `mesh_handoff.v1`, SU2, BL runtime, convergence, and production defaults off
- Proves surface meshability, not external-flow volume readiness

### 23. tail_wing Solidification Probe Layer

`src/hpa_meshing/tail_wing_solidification_probe.py`

- Consumes the real ESP-rebuilt tail geometry
- Runs bounded Gmsh heal/sew/makeSolids attempts
- Records `no_volume_created` for the current real tail geometry
- Writes `tail_wing_solidification_probe.v1.json` and `.md`
- Keeps `mesh_handoff.v1`, SU2, BL runtime, convergence, and production defaults off
- Promotes the next architecture action from naive heal tuning to explicit caps or baffle-volume construction

### 24. tail_wing Explicit Volume Route Probe Layer

`src/hpa_meshing/tail_wing_explicit_volume_route_probe.py`

- Consumes the real ESP-rebuilt tail geometry
- Tries `occ.addSurfaceLoop(..., sewing=True)` plus `occ.addVolume(...)`
- Tries an OCC baffle-fragment route inside a farfield box
- Records that the current surface-loop volume has negative signed volume and does not yield a valid external-flow farfield cut
- Records that the current baffle fragment owns a fluid/farfield candidate but fails 3D meshing with PLC intersection
- Writes `tail_wing_explicit_volume_route_probe.v1.json` and `.md`
- Keeps `mesh_handoff.v1`, SU2, BL runtime, convergence, and production defaults off

## Real vs Placeholder Boundary

The package intentionally distinguishes between:

- registry exists
- contract exists
- real backend exists

That matters because a route can be valid in schema/dispatch but still be non-productized in the backend.

Current truth:

- `aircraft_assembly` with `openvsp_surface_intersection` is real
- `fairing_solid` has real VSP geometry smoke for a Fuselage closed solid and a bounded real-geometry `mesh_handoff.v1` pass with component-owned force markers, but is not yet a real-geometry SU2, solver, or convergence route
- `main_wing` has real ESP/VSP provider geometry evidence and a bounded real-geometry mesh-handoff timeout report; real non-BL mesh-handoff / SU2-handoff materialization smokes also exist on a synthetic slab with component-owned force markers, but it is not yet a real-geometry mesh, solver, or convergence route
- `tail_wing` has real ESP/VSP provider geometry evidence, real surface-mesh evidence, a naive-solidification no-volume probe, an explicit-volume-route blocker probe, and a real mesh-handoff blocker report; synthetic non-BL mesh/SU2 handoff smokes exist with component-owned force markers, but they are not real tail mesh evidence
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
  -> fairing_solid_real_geometry_smoke.v1
  -> fairing_solid_real_mesh_handoff_probe.v1
  -> fairing_solid_mesh_handoff_smoke.v1
  -> fairing_solid_su2_handoff_smoke.v1
  -> main_wing_esp_rebuilt_geometry_smoke.v1
  -> main_wing_real_mesh_handoff_probe.v1
  -> main_wing_mesh_handoff_smoke.v1
  -> main_wing_su2_handoff_smoke.v1
  -> tail_wing_esp_rebuilt_geometry_smoke.v1
  -> tail_wing_real_mesh_handoff_probe.v1
  -> tail_wing_surface_mesh_probe.v1
  -> tail_wing_solidification_probe.v1
  -> tail_wing_explicit_volume_route_probe.v1
  -> tail_wing_mesh_handoff_smoke.v1
  -> tail_wing_su2_handoff_smoke.v1
  -> report.json
```

The contracts are intentionally machine-readable first, then human-readable through docs and reports.
`component_family_route_readiness.v1` sits beside this per-run flow as a strategic route-status
artifact; it does not imply that a component family has run.
`component_family_route_smoke_matrix.v1` is also beside the per-run flow: it proves dispatch
visibility only and still does not imply that Gmsh or SU2 ran.
`fairing_solid_real_geometry_smoke.v1` proves the real fairing VSP source can
be selected as a Fuselage and materialized as a closed-solid normalized STEP,
but it does not replace the missing real-geometry mesh handoff.
`fairing_solid_real_mesh_handoff_probe.v1` proves the current real fairing
geometry can write `mesh_handoff.v1` with component-owned `fairing_solid` and
`farfield` markers using coarse bounded probe sizing. It still does not replace
the missing real-geometry SU2 handoff, solver history, or convergence gate.
`fairing_solid_mesh_handoff_smoke.v1` is the first route-specific real Gmsh smoke
outside the formal aircraft-assembly line; it proves mesh handoff only on a
synthetic closed-solid fixture.
`fairing_solid_su2_handoff_smoke.v1` proves that this fairing mesh handoff can
materialize an SU2 case without running the solver; it now owns the
`fairing_solid` force marker, but still leaves real-geometry SU2 handoff,
solver history, and convergence outside the guarantee set.
`main_wing_esp_rebuilt_geometry_smoke.v1` proves the VSP/ESP provider can
select and materialize the real `Main Wing` source geometry, but it does not
replace the missing real-geometry mesh handoff.
`main_wing_real_mesh_handoff_probe.v1` proves the current real main-wing handoff
is blocked before `mesh_handoff.v1`: 2D meshing completes, but 3D volume
insertion exceeds the bounded probe timeout.
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
`tail_wing_real_mesh_handoff_probe.v1` proves that the current real tail handoff
is blocked before `mesh_handoff.v1`: the provider output is surface-only and the
current route expects OCC volumes.
`tail_wing_surface_mesh_probe.v1` proves that the same real provider output is
meshable as a 2D Gmsh surface with a `tail_wing` marker, but it is explicitly
not SU2-ready because no farfield or fluid volume exists.
`tail_wing_solidification_probe.v1` proves that bounded naive Gmsh
heal/sew/makeSolids attempts still produce 0 volumes, so the next serious route
needs explicit caps or a baffle-volume construction.
`tail_wing_explicit_volume_route_probe.v1` proves that the next explicit route
candidate is still blocked: the surface-loop volume has negative signed volume
and cannot be promoted to a valid external-flow cut, while the baffle-fragment
candidate fails with PLC until hpa-mdo owns the duplicate baffle surface
topology.

## Why This Boundary Matters

- New AI / new developers can tell what is formal without reading multiple worktrees
- Baseline CFD can evolve without dragging in `origin-su2-high-quality`
- ESP/OpenCSM can stay experimental without blocking the formal package
- The next hardening step can focus on alpha sweep / force-mapping policy instead of reopening the baseline gate shape again
