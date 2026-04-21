# ESP Research Handoff

Date: 2026-04-21

## Purpose

This note is the current handoff for another AI or engineer who needs to study or implement the ESP path for `hpa_meshing_package`.

The goal is to prevent three recurring mistakes:

1. treating the old "ESP provider is still non-runnable" statement as current truth
2. confusing the now-landed native provider work with the still-open downstream Gmsh meshing problem
3. restarting from the wrong premise and repeating already-known dead ends

## Execution Constraint

- Do **not** create a new git worktree for this effort.
- Work directly in the current repository checkout at `/Volumes/Samsung SSD/hpa-mdo`.
- The user explicitly does not want more worktrees for this task because they are becoming hard to manage.

## What The User Wants Now

- Keep `openvsp_surface_intersection` as the formal v1 baseline, but stop treating it as the only path worth improving
- Preserve the native ESP/OpenCSM rebuild that is now landed on current `main`
- Use that native provider to study why `blackcat_004` still hangs in downstream Gmsh surface meshing
- Re-run at least provider smoke and mesh-only probes before making broader CFD claims
- Do not drift back into runtime-install framing or solver-only tuning when the current blocker is now post-provider

## Current Repo Truth

### Formal productized route on current `main`

The only formal runnable package line today is:

```text
.vsp3
  -> openvsp_surface_intersection
  -> normalized trimmed STEP
  -> thin_sheet_aircraft_assembly
  -> gmsh_thin_sheet_aircraft_assembly
  -> mesh_handoff.v1
  -> SU2 baseline
  -> su2_handoff.v1
  -> convergence_gate.v1
  -> mesh_study.v1
```

Evidence:

- [README.md](/Volumes/Samsung%20SSD/hpa-mdo/hpa_meshing_package/README.md)
- [current_status.md](/Volumes/Samsung%20SSD/hpa-mdo/hpa_meshing_package/docs/current_status.md)

### ESP on current `main`

`esp_rebuilt` is now **provider-runnable**, but it is still **not a production-ready meshing route**.

Evidence:

- [esp_pipeline.py](/Volumes/Samsung%20SSD/hpa-mdo/hpa_meshing_package/src/hpa_meshing/providers/esp_pipeline.py) now rebuilds lifting surfaces natively from `.vsp3` section data into OpenCSM `rule` lofts
- [blackcat_004_esp_rebuilt_native_provider_smoke/topology.json](/Volumes/Samsung%20SSD/hpa-mdo/hpa_meshing_package/.tmp/runs/blackcat_004_esp_rebuilt_native_provider_smoke/esp_runtime/topology.json) shows `1 body / 32 surfaces / 1 volume`
- [blackcat_004_esp_rebuilt_native_provider_smoke/provider_log.json](/Volumes/Samsung%20SSD/hpa-mdo/hpa_meshing_package/.tmp/runs/blackcat_004_esp_rebuilt_native_provider_smoke/provider_log.json) records a successful materialization path
- [blackcat_004_esp_rebuilt_main_wing_mesh_only_hang_probe/provider_log.json](/Volumes/Samsung%20SSD/hpa-mdo/hpa_meshing_package/.tmp/runs/blackcat_004_esp_rebuilt_main_wing_mesh_only_hang_probe/artifacts/providers/esp_rebuilt/provider_log.json) shows the provider completes before the later meshing hang

This is no longer a provider-existence gap. The concrete remaining gap is downstream meshing stability.

### Latest C1 meshing-forensics update

After the native provider landed, the next round of work added mesh-side watchdog artifacts and ran new `main_wing` / `assembly` probes. The important new truth is:

- the minimal blocker is now a **Gmsh meshing-regime problem**, not a provider materialization problem
- `main_wing` is the cleanest reproducer
- the external-flow route mixes two costs together:
  - aircraft BSpline surface meshing under default ref-length sizing
  - downstream farfield / full-route overhead
- if we isolate the aircraft-only surface mesh and coarsen it, native `main_wing` **can** complete 2D

## What Has Already Been Researched

There is a real feasibility spike:

- [esp_opencsm_feasibility.md](/Volumes/Samsung%20SSD/hpa-mdo/hpa_meshing_package/docs/esp_opencsm_feasibility.md)
- [feasibility_summary.json](/Volumes/Samsung%20SSD/hpa-mdo/hpa_meshing_package/experiments/esp_spike/feasibility_summary.json)

That spike concluded:

- ESP/OpenCSM is worth keeping as an experimental provider direction
- it was **not** ready to be promoted to a first-class v1 provider
- local `serveESP` / `serveCSM` / `ocsm` runtime was not fully installed or run end-to-end
- the strongest topology improvement seen during that spike came from OpenVSP `SurfaceIntersection`, not from a completed local ESP rebuild

Important warning:

That spike was valid research, and current `main` has now moved one layer past it: the native provider exists, but a stable mesh route still does not.

## Real Failures Already Observed

### A. ESP provider no longer fails before meshing, but the route still fails during meshing

Real provider / route probes:

- [blackcat_004_esp_rebuilt_native_provider_smoke/topology.json](/Volumes/Samsung%20SSD/hpa-mdo/hpa_meshing_package/.tmp/runs/blackcat_004_esp_rebuilt_native_provider_smoke/esp_runtime/topology.json)
- [blackcat_004_esp_rebuilt_main_wing_mesh_only_hang_probe/provider_log.json](/Volumes/Samsung%20SSD/hpa-mdo/hpa_meshing_package/.tmp/runs/blackcat_004_esp_rebuilt_main_wing_mesh_only_hang_probe/artifacts/providers/esp_rebuilt/provider_log.json)
- [blackcat_004_esp_rebuilt_assembly_mesh_only_hang_probe/provider_log.json](/Volumes/Samsung%20SSD/hpa-mdo/hpa_meshing_package/.tmp/runs/blackcat_004_esp_rebuilt_assembly_mesh_only_hang_probe/artifacts/providers/esp_rebuilt/provider_log.json)

Observed result:

- provider materialization succeeds and emits normalized geometry artifacts
- main-wing topology probe reports `1 body / 32 surfaces / 1 volume`
- `duplicate_interface_face_pair_count = 0`
- both mesh-only CLI probes still hang before producing final mesh artifacts

Meaning:

- current `esp_rebuilt` does reach Gmsh-stage execution
- there is still no real completed ESP coarse mesh yet
- there are no ESP `CL / CD / CM` results yet

### D. 2026-04-21 C1 Mesh2D forensics narrowed the blocker

New artifacts:

- [codex_c1_mesh2d_forensics_20260421](/Volumes/Samsung%20SSD/hpa-mdo/hpa_meshing_package/.tmp/runs/codex_c1_mesh2d_forensics_20260421)
- [codex_c1_surface_only_forensics_scaled_20260421](/Volumes/Samsung%20SSD/hpa-mdo/hpa_meshing_package/.tmp/runs/codex_c1_surface_only_forensics_scaled_20260421)

What changed in the evidence:

- the route now drops `mesh2d_watchdog.json`, `mesh2d_watchdog_sample.txt`, and `surface_patch_diagnostics.json`
- this means the failure is no longer just "sample looked stuck"; each run now leaves:
  - the last meshing surface tag seen by the logger
  - a call-stack sample artifact
  - ranked suspicious surface / curve families

Main-wing full-route result:

- `Mesh.Algorithm = 1 / 5 / 6` on the native `main_wing` full route all timed out under default sizing
- the default-size route consistently triggered the watchdog around `16 s`
- algorithm `6` and `5` both last reported `surface 14 (BSpline surface)`
- algorithm `1` last reported `surface 11 (BSpline surface, MeshAdapt)`
- the call-stack samples show the default-size route spending time in Gmsh `Mesh2D -> meshGenerator`, with default frontal/delaunay runs going through `laplaceSmoothing` / BSpline reparameterization paths rather than producing a clean explicit geometry error

Main-wing coarse full-route result:

- coarse route cases (`global_min_size = 0.05`, `global_max_size = 1.0`) still timed out on the full route
- but their watchdog advanced to `surface 33 (Plane)`, which is outside the 32-aircraft-surface set
- this is strong evidence that coarse sizing can get through the aircraft surfaces and then pay heavily in the downstream farfield plane / external-flow path

Main-wing aircraft-only scaled probe:

- the properly scaled aircraft-only default-size probe still timed out and last reported `surface 14 (BSpline surface, Frontal-Delaunay)`
- the properly scaled aircraft-only coarse005 probe **completed**
- completed artifact:
  - [surface_mesh_2d.msh](/Volumes/Samsung%20SSD/hpa-mdo/hpa_meshing_package/.tmp/runs/codex_c1_surface_only_forensics_scaled_20260421/main_wing_surface_only_scaled_alg6_coarse005/artifacts/mesh/surface_mesh_2d.msh)
- completion evidence:
  - `35770 nodes / 74077 elements`
  - `Done meshing 2D` in about `1.26 s`
  - wrapper wall time about `2.83 s`

Assembly minimal smoke:

- the full-route assembly probe also timed out
- but the watchdog triggered while Gmsh was still in `Mesh1D`, not yet `Mesh2D`
- the corresponding sample showed roughly `9.9 GB` physical footprint on this Mac mini
- engineering meaning: assembly is same-family downstream pain, but it is not the cleanest minimal blocker; `main_wing` remains the right first diagnostic target

Suspicious patch family:

- the ranked suspicious surfaces are consistently `31/32` and then `5/6/1/10`
- common traits:
  - `short_curve_candidate`
  - `high_aspect_strip_candidate`
  - often `span_extreme_candidate`
- these live around:
  - the wing outer-span strip / cap family
  - root / trailing-edge-adjacent tiny strip faces

Important nuance:

- the surface that the watchdog catches during default-size timeout is `surface 14`, not one of the top-ranked tiny strips
- so the small-strip family is best treated as a likely **global meshing-regime trigger / quality poison**, while the actual visible stall manifests later on a larger BSpline patch

Current engineering interpretation:

- native C1 geometry is **not** fundamentally unmeshable in 2D
- the true blocker is the combination of:
  - default ref-length-driven near-body sizing
  - native BSpline patch parameterization / short-curve strip family
  - full external-flow farfield route overhead
- this means the next useful work should stay on meshing diagnostics / policy, not on provider existence, runtime installation, or large source-geometry redesigns

### B. Current OpenVSP route materializes geometry, but high-resolution meshing is still unstable

Provider topology evidence:

- [topology.json](/Volumes/Samsung%20SSD/hpa-mdo/hpa_meshing_package/.tmp/runs/blackcat_004_mesh_study_ref_length_main/cases/coarse/artifacts/providers/openvsp_surface_intersection/topology.json)

Confirmed facts:

- `representation = brep_trimmed_step`
- `units = m`
- `body_count = 3`
- `surface_count = 38`
- `volume_count = 3`
- `labels_present = true`
- `backend_rescale_required = true`
- `import_scale_to_units ~= 0.001`

This means the provider is not just exploding immediately. It does produce a structured trimmed STEP artifact. The instability is later in the route.

### C. Meshing regime on `openvsp_surface_intersection` currently has no stable window

Probe 1:

- [blackcat_probe_1m/report.json](/Volumes/Samsung%20SSD/hpa-mdo/hpa_meshing_package/.tmp/runs/blackcat_probe_1m/report.json)
- near-body size around `1.0 m`
- backend error: `Invalid boundary mesh (overlapping facets) on surface 6 surface 9`

Probe 2:

- [blackcat_probe_mid_0_80/report.json](/Volumes/Samsung%20SSD/hpa-mdo/hpa_meshing_package/.tmp/runs/blackcat_probe_mid_0_80/report.json)
- near-body size around `0.8 m`
- backend error: `PLC Error: A segment and a facet intersect at point`

Finer-than-that route:

- the ref-length-based `coarse` study run under `blackcat_004_mesh_study_ref_length_main` did not produce a real mesh/report within the observed window
- previously sampled call stacks showed it hanging in Gmsh `Mesh2D -> GFaceInitialMesh -> PolyMesh::split_triangle`

Working interpretation:

- too coarse: overlapping/self-intersection style failure
- somewhat finer: PLC intersection failure
- much finer: surface meshing hangs

So the current `openvsp_surface_intersection -> gmsh` route has not yet established a stable high-resolution surface meshing regime for this geometry.

## Historical But Important Evidence

There is older retained evidence from the previous docs-driven worktree that should not be mistaken for current `main`, but it is still useful because it shows why the earlier route was not high fidelity.

Historical artifact:

- [/Volumes/Samsung SSD/hpa-mdo/.worktrees/hpa-meshing-docs-driven-fix/hpa_meshing_package/.tmp/runs/blackcat_004_mesh_study_super_fine/cases/fine/artifacts/mesh/mesh_metadata.json](/Volumes/Samsung%20SSD/hpa-mdo/.worktrees/hpa-meshing-docs-driven-fix/hpa_meshing_package/.tmp/runs/blackcat_004_mesh_study_super_fine/cases/fine/artifacts/mesh/mesh_metadata.json)

What it showed:

- `node_count = 6486`
- `volume_element_count = 29596`
- total aircraft boundary triangles only `212`
- farfield triangles `6416`

This was one of the strongest pieces of evidence that the old route was engineering-invalid as a high-fidelity setup:

- too much resolution was being spent on the farfield box
- aircraft surface was massively under-resolved
- medium/fine appeared comparable by some gates, but the geometry was not actually resolved enough to trust the resulting coefficients

Historical fine-run aero result:

- [/Volumes/Samsung SSD/hpa-mdo/.worktrees/hpa-meshing-docs-driven-fix/hpa_meshing_package/.tmp/runs/blackcat_004_mesh_study_super_fine/cases/fine/report.json](/Volumes/Samsung%20SSD/hpa-mdo/.worktrees/hpa-meshing-docs-driven-fix/hpa_meshing_package/.tmp/runs/blackcat_004_mesh_study_super_fine/cases/fine/report.json)

Relevant signals:

- `cl = 0.03153145365`
- `cd = 0.02925969757`
- `cm = -0.007360669653`
- force scope remained `whole_aircraft_wall`
- `component_provenance = geometry_labels_present_but_not_mapped`

Why this matters:

- these numbers were not accepted as final truth
- they reinforced the suspicion that the route was under-resolving the aircraft surface badly enough to distort the physics

## What Has Already Been Fixed In Current Main

### 1. Sizing logic is no longer tied to global span

Current Gmsh sizing code:

- [gmsh_backend.py](/Volumes/Samsung%20SSD/hpa-mdo/hpa_meshing_package/src/hpa_meshing/adapters/gmsh_backend.py)

Current behavior:

- surface sizing resolves from geometry-derived `ref_length`
- edge sizing is now tied to preset-scaled `near_body_size`
- hidden size sources are disabled:
  - `Mesh.MeshSizeFromPoints = 0`
  - `Mesh.MeshSizeFromCurvature = 0`
  - `Mesh.MeshSizeExtendFromBoundary = 0`

This means the old gross mistake of "use span-based characteristic length and barely resolve the wing" has already been corrected in current `main`.

### 2. Mesh-study presets now use `ref_length`

Current study logic:

- [mesh_study.py](/Volumes/Samsung%20SSD/hpa-mdo/hpa_meshing_package/src/hpa_meshing/mesh_study.py)

Current preset construction is based on `reference_length`, not bbox span.

This is an improvement, but it exposed the next blocker more clearly: the route now tries to do real high-resolution meshing and fails in Gmsh.

### 3. Documentation drift has been corrected

The repo now explicitly says that ESP is provider-runnable but not yet a stable production meshing route:

- [README.md](/Volumes/Samsung%20SSD/hpa-mdo/hpa_meshing_package/README.md)
- [current_status.md](/Volumes/Samsung%20SSD/hpa-mdo/hpa_meshing_package/docs/current_status.md)
- [ESP enablement plan](/Volumes/Samsung%20SSD/hpa-mdo/docs/superpowers/plans/2026-04-21-esp-rebuilt-provider-enablement.md)

## What Is Probably Not The Main Problem

### Not just SU2 installation

The current ESP attempt never reaches SU2.

### Not just solver iteration or CFL

The current blocker is before trustworthy CFD results exist.

### Not "ESP provider still does not exist"

That is now outdated. Current `main` does have a real ESP materialization path; the unresolved issue is the downstream meshing path.

### Not "OpenVSP provider always produces garbage"

That is too simplistic. The `openvsp_surface_intersection` route does produce a trimmed STEP with `3 bodies / 38 surfaces / 3 volumes`.

The more accurate statement is:

- OpenVSP `SurfaceIntersection` materializes something structured and nontrivial
- but the downstream OCC/Gmsh route is still not stable enough for the desired high-resolution assembly meshing on this aircraft

## What Another AI Should Focus On

### Primary engineering target

Make `esp_rebuilt` into a real provider that can:

1. keep the native `.vsp3 -> OpenCSM rule-loft -> normalized STEP` path working
2. explain why the current native geometry still hangs in Gmsh `Mesh2D`
3. produce at least one completed mesh-only `blackcat_004` run
4. then decide whether assembly, main-wing-only, or a refined fallback should carry the first real ESP coarse run
5. only after that, resume higher-level CFD/gate work

### Questions worth researching

1. What is the best automatable official OpenVSP -> ESP path on macOS arm64 for this repo?
   - current landed answer is native OpenCSM `rule` lofts via `serveCSM -batch`
   - remaining question is whether that loft recipe should be refined, not whether `UDPRIM vsp3` should come back

2. Why does the current native geometry still hang in Gmsh `Mesh2D`?
   - default sizing plus BSpline reparameterization cost on the exported patch family?
   - short-curve / high-aspect strip surfaces poisoning global meshing quality?
   - full-route farfield plane cost hiding the fact that aircraft-only coarse 2D is already passable?

3. Should the next diagnostic focus on `main_wing` first, or on the full `aircraft_assembly` export?
   - answer is now clearly `main_wing` first
   - assembly smoke is same-family evidence, but its first visible pain can appear earlier in `Mesh1D` with much higher memory pressure

4. What exact Gmsh diagnostics should be added next?
   - keep the new watchdog / sample / patch-ranking artifacts
   - consider an in-route diagnostic mode that skips farfield and meshes aircraft-only surfaces directly
   - localize size / meshing-policy experiments around the suspicious strip family instead of doing blind global sweeps

5. Does the native ESP export actually reduce the old overlap disease on the main wing?
   - current evidence says yes at the provider topology layer (`duplicate_interface_face_pair_count = 0`)
   - and the new aircraft-only coarse005 completion is the first meshing-side evidence that the native provider is at least salvageable as a mainline direction

## What Another AI Should Not Waste Time On First

- further gate-threshold tuning
- SU2 solver parameter tuning
- alpha sweep
- component force mapping
- report beautification
- redoing runtime installation work that the current machine no longer needs for provider execution
- trying to infer final aero truth from the historical low-resolution `fine` run

Those are downstream concerns. The immediate blocker is now a stable meshing path on top of the already-landed provider.

## Concrete Files To Read First

1. [ESP enablement plan](/Volumes/Samsung%20SSD/hpa-mdo/docs/superpowers/plans/2026-04-21-esp-rebuilt-provider-enablement.md)
2. [esp_rebuilt.py](/Volumes/Samsung%20SSD/hpa-mdo/hpa_meshing_package/src/hpa_meshing/providers/esp_rebuilt.py)
3. [esp_pipeline.py](/Volumes/Samsung%20SSD/hpa-mdo/hpa_meshing_package/src/hpa_meshing/providers/esp_pipeline.py)
4. [esp_opencsm_feasibility.md](/Volumes/Samsung%20SSD/hpa-mdo/hpa_meshing_package/docs/esp_opencsm_feasibility.md)
5. [README.md](/Volumes/Samsung%20SSD/hpa-mdo/hpa_meshing_package/README.md)
6. [current_status.md](/Volumes/Samsung%20SSD/hpa-mdo/hpa_meshing_package/docs/current_status.md)
7. [gmsh_backend.py](/Volumes/Samsung%20SSD/hpa-mdo/hpa_meshing_package/src/hpa_meshing/adapters/gmsh_backend.py)
8. [mesh_study.py](/Volumes/Samsung%20SSD/hpa-mdo/hpa_meshing_package/src/hpa_meshing/mesh_study.py)
9. [blackcat_004_esp_rebuilt_native_provider_smoke/topology.json](/Volumes/Samsung%20SSD/hpa-mdo/hpa_meshing_package/.tmp/runs/blackcat_004_esp_rebuilt_native_provider_smoke/esp_runtime/topology.json)
10. [blackcat_004_esp_rebuilt_main_wing_mesh_only_hang_probe/provider_log.json](/Volumes/Samsung%20SSD/hpa-mdo/hpa_meshing_package/.tmp/runs/blackcat_004_esp_rebuilt_main_wing_mesh_only_hang_probe/artifacts/providers/esp_rebuilt/provider_log.json)

## One-Sentence Summary

Current `main` now has a runnable native ESP provider and at least one completed native `main_wing` aircraft-only coarse 2D probe, but the full external-flow route still lacks a stable default-size Gmsh meshing window for `blackcat_004`, so the next engineering target is meshing-policy hardening rather than provider enablement.
