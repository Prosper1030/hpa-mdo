# Current Status

## Official Product Line

The formal package-native line today is:

```text
aircraft_assembly (.vsp3)
  -> openvsp_surface_intersection
  -> normalized trimmed STEP
  -> thin_sheet_aircraft_assembly
  -> gmsh_thin_sheet_aircraft_assembly
  -> mesh_handoff.v1
  -> SU2 baseline
  -> su2_handoff.v1
  -> convergence_gate.v1
  -> mesh_study.v1 (optional baseline hardening gate)
```

This is the only route that should currently be treated as a real productized workflow in `hpa_meshing_package`.

## 2026-04-30 Route Architecture Decision

The high-fidelity line is now explicitly route-matrix first. The long-term goal is arbitrary
HPA main-wing / tail / fairing automation through:

```text
VSP / ESP geometry -> component-family classification -> route selection -> Gmsh -> SU2
```

Do not treat `shell_v4 root_last3` as the product route. It remains a diagnostic and
promotion branch for BL handoff topology. A boundary-layer route can be promoted only after
hpa-mdo owns the transition sleeve, receiver faces, interface loops, and layer-drop event
mapping well enough that Gmsh is only expected to tetrahedralize the core volume.

The machine-readable readiness view is emitted by:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli route-readiness --out .tmp/runs/component_family_route_readiness
```

This writes `component_family_route_readiness.v1.json` and
`component_family_route_readiness.v1.md`. A committed snapshot is kept under
[`docs/reports/`](reports/). The strategic decision record is
[`docs/research/high_fidelity_route_decision_2026-04-30.md`](../../docs/research/high_fidelity_route_decision_2026-04-30.md).

The pre-mesh dispatch smoke matrix is emitted by:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli component-family-smoke-matrix --out .tmp/runs/component_family_route_smoke_matrix
```

This writes `component_family_route_smoke_matrix.v1.json` and
`component_family_route_smoke_matrix.v1.md`. It checks that main-wing, tail,
and fairing component families classify and dispatch to registered route
skeletons outside `root_last3`. It does not run Gmsh, BL runtime, SU2,
`mesh_handoff.v1`, `su2_handoff.v1`, or `convergence_gate.v1`.

The first real fairing geometry smoke is emitted by:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli fairing-solid-real-geometry-smoke --out .tmp/runs/fairing_solid_real_geometry_smoke
```

This writes `fairing_solid_real_geometry_smoke.v1.json` and
`fairing_solid_real_geometry_smoke.v1.md`. It consumes the external
`HPA-Fairing-Optimization-Project` `best_design.vsp3`, selects a `Fuselage`,
materializes a normalized STEP through `openvsp_surface_intersection`, and
observes closed-solid topology. The current committed result is
`geometry_smoke_pass` with `1 body / 8 surfaces / 1 volume`. It does not run
Gmsh meshing, SU2, or convergence, so the next blocker is real fairing mesh
handoff.

The first real fairing mesh handoff probe is emitted by:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli fairing-solid-real-mesh-handoff-probe --out .tmp/runs/fairing_solid_real_mesh_handoff_probe
```

This writes `fairing_solid_real_mesh_handoff_probe.v1.json` and
`fairing_solid_real_mesh_handoff_probe.v1.md`. The current committed result is
`mesh_handoff_pass`: the real fairing VSP geometry writes `mesh_handoff.v1`
with `fairing_solid` and `farfield` markers using coarse probe sizing
(`node_count=29394`, `volume_element_count=153251` in the latest snapshot).
It still does not run SU2 or convergence, so the next blocker is real fairing
SU2 handoff materialization.

The first real fairing SU2 handoff probe is emitted by:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli fairing-solid-real-su2-handoff-probe --out .tmp/runs/fairing_solid_real_su2_handoff_probe --source-mesh-probe-report docs/reports/fairing_solid_real_mesh_handoff_probe/fairing_solid_real_mesh_handoff_probe.v1.json
```

This writes `fairing_solid_real_su2_handoff_probe.v1.json` and
`fairing_solid_real_su2_handoff_probe.v1.md`. The current committed result is
`su2_handoff_written`: the real fairing `mesh_handoff.v1` materializes
`su2_handoff.v1`, `mesh.su2`, and `su2_runtime.cfg` with a component-owned
`fairing_solid` force marker. It still does not run `SU2_CFD` or convergence.
`reference_geometry_status=warn`, so coefficient credibility remains blocked
until the fairing reference policy is explicit and a solver/convergence gate is
recorded.

The fairing reference-policy probe is emitted by:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli fairing-solid-reference-policy-probe --out .tmp/runs/fairing_solid_reference_policy_probe
```

This writes `fairing_solid_reference_policy_probe.v1.json` and
`fairing_solid_reference_policy_probe.v1.md`. It reads the neighboring fairing
optimization project under `/Volumes/Samsung SSD/HPA-Fairing-Optimization-Project`.
The committed result is `reference_mismatch_observed`: the external fairing
policy uses `REF_AREA=1.0`, `REF_LENGTH=2.82880659`, and the HPA standard
`V=6.5`, while the legacy pre-standard hpa-mdo real fairing SU2 handoff artifact
used `REF_AREA=100`, `REF_LENGTH=1`, and `V=10`. `V=10` is historical mismatch
evidence, not the current HPA standard.

The fairing reference-override SU2 handoff probe is emitted by:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli fairing-solid-reference-override-su2-handoff-probe --out .tmp/runs/fairing_solid_reference_override_su2_handoff_probe
```

This writes `fairing_solid_reference_override_su2_handoff_probe.v1.json` and
`fairing_solid_reference_override_su2_handoff_probe.v1.md`. The current
committed result is `su2_handoff_written` with
`reference_override_status=applied_with_moment_origin_warning`: `REF_AREA=1.0`,
`REF_LENGTH=2.82880659`, `V=6.5`, and the `fairing_solid` force marker are now
materialized into a real fairing `su2_handoff.v1`. Solver history and
convergence are still absent, and the borrowed zero moment origin remains a
blocker for moment coefficients.

Package-native SU2 runtime defaults now follow the same HPA flow standard:
`velocity_mps=6.5`, `density_kgpm3=1.225`, `temperature_k=288.15`, and
`dynamic_viscosity_pas=1.7894e-5`. Editable operator-facing values live under
`su2.flow_conditions` in the YAML config.

The first route-specific fairing mesh-handoff smoke is emitted by:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli fairing-solid-mesh-handoff-smoke --out .tmp/runs/fairing_solid_mesh_handoff_smoke
```

This writes `fairing_solid_mesh_handoff_smoke.v1.json` and
`fairing_solid_mesh_handoff_smoke.v1.md`. It runs real Gmsh for a synthetic
closed-solid fairing fixture and emits `mesh_handoff.v1`. It still does not run
SU2, does not emit `su2_handoff.v1`, and does not emit `convergence_gate.v1`.
It does include a component-owned `fairing_solid` marker in the mesh-handoff
evidence.

The first fairing SU2 handoff materialization smoke is emitted by:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli fairing-solid-su2-handoff-smoke --out .tmp/runs/fairing_solid_su2_handoff_smoke
```

This writes `fairing_solid_su2_handoff_smoke.v1.json` and
`fairing_solid_su2_handoff_smoke.v1.md`. It consumes the synthetic closed-solid
fairing `mesh_handoff.v1` and materializes `su2_handoff.v1`, `mesh.su2`, and
`su2_runtime.cfg` without executing `SU2_CFD`. It consumes the component-owned
`fairing_solid` wall marker; real-geometry SU2 handoff is tracked by the
separate real probe, while solver history and convergence remain missing.

The first main-wing ESP-rebuilt geometry smoke is emitted by:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli main-wing-esp-rebuilt-geometry-smoke --out .tmp/runs/main_wing_esp_rebuilt_geometry_smoke
```

This writes `main_wing_esp_rebuilt_geometry_smoke.v1.json` and
`main_wing_esp_rebuilt_geometry_smoke.v1.md`. It consumes
`data/blackcat_004_origin.vsp3`, selects the OpenVSP `Main Wing` as
`main_wing`, and materializes an ESP-normalized thin lifting-surface STEP. The
current committed result is `geometry_smoke_pass` with `surface_count=32` and
`volume_count=1`. It still does not run Gmsh, does not emit
`mesh_handoff.v1`, does not run SU2, and does not prove solver credibility.

The first real main-wing mesh handoff probe is emitted by:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli main-wing-real-mesh-handoff-probe --out .tmp/runs/main_wing_real_mesh_handoff_probe
```

This writes `main_wing_real_mesh_handoff_probe.v1.json` and
`main_wing_real_mesh_handoff_probe.v1.md`. The current result is
`mesh_handoff_timeout`: provider geometry is materialized with
`surface_count=32` and `volume_count=1`, 2D meshing completes
(`mesh2d_watchdog_status=completed_without_timeout`), and 3D meshing times out
during `volume_insertion` before `mesh_handoff.v1` is written. This is a
bounded coarse probe, not production sizing, and it still does not run SU2 or
convergence.

The first route-specific main-wing mesh smoke is emitted by:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli main-wing-mesh-handoff-smoke --out .tmp/runs/main_wing_mesh_handoff_smoke
```

This writes `main_wing_mesh_handoff_smoke.v1.json` and
`main_wing_mesh_handoff_smoke.v1.md`. It runs real Gmsh for a synthetic thin
closed-solid wing slab and emits `mesh_handoff.v1` with component-owned
`main_wing` / `farfield` markers. It still does not run BL runtime, does not run SU2, does
not emit `su2_handoff.v1`, does not emit `convergence_gate.v1`, and does not
prove real aerodynamic main-wing geometry.

The first main-wing SU2 handoff materialization smoke is emitted by:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli main-wing-su2-handoff-smoke --out .tmp/runs/main_wing_su2_handoff_smoke
```

This writes `main_wing_su2_handoff_smoke.v1.json` and
`main_wing_su2_handoff_smoke.v1.md`. It consumes the synthetic non-BL
main-wing `mesh_handoff.v1` and materializes `su2_handoff.v1`, `mesh.su2`, and
`su2_runtime.cfg` without executing `SU2_CFD`. It consumes the component-owned
`main_wing` wall marker; real main-wing geometry, solver history, and
convergence remain missing.

The first tail-wing ESP-rebuilt geometry smoke is emitted by:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli tail-wing-esp-rebuilt-geometry-smoke --out .tmp/runs/tail_wing_esp_rebuilt_geometry_smoke
```

This writes `tail_wing_esp_rebuilt_geometry_smoke.v1.json` and
`tail_wing_esp_rebuilt_geometry_smoke.v1.md`. It consumes
`data/blackcat_004_origin.vsp3`, selects the OpenVSP `Elevator` as
`tail_wing` / `horizontal_tail`, and materializes an ESP-normalized thin
lifting-surface STEP. It still does not run Gmsh, does not emit
`mesh_handoff.v1`, does not run SU2, and does not prove solver credibility.

The first tail-wing mesh handoff smoke is emitted by:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli tail-wing-mesh-handoff-smoke --out .tmp/runs/tail_wing_mesh_handoff_smoke
```

This writes `tail_wing_mesh_handoff_smoke.v1.json` and
`tail_wing_mesh_handoff_smoke.v1.md`. It runs real Gmsh for a synthetic thin
closed-solid tail slab and emits `mesh_handoff.v1` with component-owned
`tail_wing` / `farfield` markers. It still does not run BL runtime, does not run
SU2, does not emit `su2_handoff.v1`, does not emit `convergence_gate.v1`, and
does not prove real aerodynamic tail geometry.

The first tail-wing SU2 handoff materialization smoke is emitted by:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli tail-wing-su2-handoff-smoke --out .tmp/runs/tail_wing_su2_handoff_smoke
```

This writes `tail_wing_su2_handoff_smoke.v1.json` and
`tail_wing_su2_handoff_smoke.v1.md`. It consumes the synthetic non-BL
tail-wing `mesh_handoff.v1` and materializes `su2_handoff.v1`, `mesh.su2`, and
`su2_runtime.cfg` without executing `SU2_CFD`. It consumes the component-owned
`tail_wing` wall marker; real tail geometry, solver history, and convergence
remain missing.

The first real tail-wing mesh handoff probe is emitted by:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli tail-wing-real-mesh-handoff-probe --out .tmp/runs/tail_wing_real_mesh_handoff_probe
```

This writes `tail_wing_real_mesh_handoff_probe.v1.json` and
`tail_wing_real_mesh_handoff_probe.v1.md`. The current result is
`mesh_handoff_blocked`: real ESP tail geometry is surface-only
(`surface_count=6`, `volume_count=0`), and the existing
`gmsh_thin_sheet_surface` route expects OCC volumes. Synthetic tail slab
evidence must not be treated as real tail mesh handoff evidence.

The real tail surface mesh probe is emitted by:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli tail-wing-surface-mesh-probe --out .tmp/runs/tail_wing_surface_mesh_probe
```

This writes `tail_wing_surface_mesh_probe.v1.json` and
`tail_wing_surface_mesh_probe.v1.md`. The current result is
`surface_mesh_pass`: Gmsh can mesh the six real ESP tail surfaces into 2286
surface elements with a `tail_wing` physical group. This is still not
`mesh_handoff.v1`; no farfield volume or SU2-ready external-flow volume exists.

The real tail solidification probe is emitted by:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli tail-wing-solidification-probe --out .tmp/runs/tail_wing_solidification_probe
```

This writes `tail_wing_solidification_probe.v1.json` and
`tail_wing_solidification_probe.v1.md`. The current result is
`no_volume_created`: bounded Gmsh heal/sew/makeSolids attempts create 12
surfaces and 0 volumes. The next viable implementation is explicit caps or a
baffle-volume route.

The explicit tail volume route probe is emitted by:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src python -m hpa_meshing.cli tail-wing-explicit-volume-route-probe --out .tmp/runs/tail_wing_explicit_volume_route_probe
```

This writes `tail_wing_explicit_volume_route_probe.v1.json` and
`tail_wing_explicit_volume_route_probe.v1.md`. The current result is
`explicit_volume_route_blocked`: `occ.addSurfaceLoop(..., sewing=True)` plus
`occ.addVolume(...)` creates one explicit volume candidate, but the signed
volume is negative and the farfield cut is not a valid external-flow boundary.
The baffle-fragment candidate owns a fluid/farfield candidate, but fails 3D
meshing with `tail_baffle_fragment_mesh_failed_plc`. The next viable
implementation is explicit volume orientation repair or baffle-surface
ownership cleanup, not solver execution.

## Formal v1 Capabilities

| Capability | Status | Notes |
| --- | --- | --- |
| `openvsp_surface_intersection` provider | formal `v1` | `.vsp3 -> normalized STEP`, topology report, provider log |
| `GeometryProviderResult` | fixed | formal provider contract |
| `aircraft_assembly` family dispatch | formal `v1` | `thin_sheet_aircraft_assembly` |
| `gmsh_thin_sheet_aircraft_assembly` | formal `v1` | real Gmsh external-flow volume mesh |
| `mesh_handoff.v1` | fixed | downstream mesh contract |
| baseline SU2 materialization | formal `v1` | case generation, solver invocation, history parse |
| `su2_handoff.v1` | fixed | baseline CFD contract |
| `convergence_gate.v1` | fixed | mesh / iterative / overall comparability verdict for the baseline route |
| `mesh_study.v1` | formal minimal `v1` | three-tier coarse / medium / fine baseline study that aggregates per-case gates into one study verdict |
| reference provenance gate | fixed | `geometry_derived`, `baseline_envelope_derived`, `user_declared` |
| force-surface provenance gate | fixed | whole-aircraft wall plus component-owned `fairing_solid` / lifting-surface markers |

## Experimental

| Capability | Status | Why |
| --- | --- | --- |
| `esp_rebuilt` provider | experimental | native OpenCSM rule-loft rebuild 已可 materialize normalized geometry；`main_wing` aircraft-only coarse 2D 已可穿過，但 full external-flow route 的 default sizing 仍卡在 downstream Gmsh meshing |
| `main_wing` | experimental | real ESP/VSP geometry smoke exists for `Main Wing`; bounded real-geometry mesh handoff probe times out during 3D volume insertion after 2D completion; synthetic non-BL `mesh_handoff.v1` and `su2_handoff.v1` materialization smokes exist with a `main_wing` marker; real-geometry mesh handoff, solver history, and convergence gate are missing |
| `tail_wing` | experimental | real ESP/VSP geometry, surface-mesh, naive-solidification, and explicit-volume-route probes exist; real volume mesh handoff is blocked by surface-only provider output, negative signed-volume explicit surface-loop behavior, and baffle-fragment PLC failure; synthetic non-BL `mesh_handoff.v1` / `su2_handoff.v1` smokes exist but are not real tail mesh evidence |
| `fairing_solid` | experimental | real fairing VSP geometry smoke exists for a `best_design` Fuselage with closed-solid topology; bounded real-geometry mesh handoff writes `mesh_handoff.v1` with a `fairing_solid` marker; real-geometry `su2_handoff.v1` materialization exists; external fairing reference policy is now applied in a gated override handoff; borrowed zero moment origin, solver history, and convergence gate are still missing |
| `fairing_vented` | experimental | dispatch exists, real backend not productized |
| direct multi-family package configs | experimental | do not present as formal current route |

If a route returns `route_stage=placeholder`, it is not a formal meshing result.

## ESP Current Reality

- `esp_rebuilt` 已不再是 `not_materialized` stub。`src/hpa_meshing/providers/esp_pipeline.py` 現在走 native OpenCSM lifting-surface rebuild：從 `.vsp3` 讀 wing/tail sections，生成 rule-loft `.csm`，再用 `serveCSM -batch` 輸出 normalized STEP 與 topology artifact。
- 這台 Mac mini（macOS 26.4.1 / arm64）的 runtime truth 已更新：`serveESP` / `serveCSM` 在 `PATH` 上、`ocsm` 仍缺席，但 batch 路徑可以直接用 `serveCSM`。因此 provider 在本機已經 runnable，不再被 `esp_runtime_missing` 擋住。
- 2026-04-30 的 `main_wing_esp_rebuilt_geometry_smoke.v1` 已把主翼 real provider evidence 收進 committed report：`Main Wing` 可被選取並 materialize 成 normalized STEP，topology 為 `1 body / 32 surfaces / 1 volume`；後續 `main_wing_real_mesh_handoff_probe.v1` 則把下一個 blocker 收斂成 3D volume insertion timeout。
- 2026-04-21 的 provider smoke 已成功 materialize：`hpa_meshing_package/.tmp/runs/blackcat_004_esp_rebuilt_native_provider_smoke/` 內有 `normalized.stp` / `topology.json` / `provider_log.json`，且 topology 為 `1 body / 32 surfaces / 1 volume`、`duplicate_interface_face_pair_count = 0`。
- 2026-04-21 晚上的 C1 diagnostics 已把「有 hang」收斂成更精確的證據：`hpa_meshing_package/.tmp/runs/codex_c1_mesh2d_forensics_20260421/` 內的 `main_wing` full-route A/B 顯示 `Mesh.Algorithm = 1 / 5 / 6` 在 default sizing 下都會 timeout；default case 的 watchdog 會穩定卡在 `surface 14 (BSpline surface)`，coarse route 則能穿過 aircraft surfaces、把最後 surface 記到 `surface 33 (Plane)`，表示 farfield 會放大下游成本。
- 同一輪 `surface_patch_diagnostics.json` 也留下了可疑 patch family：`surface 31/32` 與 `surface 5/6/1/10` 持續被排在最前面，特徵是 `short_curve_candidate + high_aspect_strip_candidate`，位置落在翼外段 span-extreme strip 與 root / trailing-edge 附近的小 strip faces。
- 更重要的是，`hpa_meshing_package/.tmp/runs/codex_c1_surface_only_forensics_scaled_20260421/` 已證明 native `main_wing` 本體不是完全不能做 2D：aircraft-only、properly scaled、`global_min_size=0.05` 的 coarse005 probe 可以在 `2.83 s` 內完成 `surface_mesh_2d.msh`，`35770 nodes / 74077 elements`；但相同 aircraft-only probe 在 default sizing 下仍會於 `surface 14` 附近 timeout。
- 結論：`esp_rebuilt` 目前仍是 experimental，但已經從「provider runnable」再往前推到「可診斷的 meshing route」。最小 blocker 不再是 provider topology，而是 native loft patches 在 default/ref-length sizing 下進入不穩定的 Gmsh 2D meshing regime；assembly 則在此之上再疊加 farfield / 1D memory 壓力。
- 具體實作規劃請看 [docs/superpowers/plans/2026-04-21-esp-rebuilt-provider-enablement.md](../../docs/superpowers/plans/2026-04-21-esp-rebuilt-provider-enablement.md)。

## Explicit Non-Goals For This Round

- claiming final high-quality CFD credibility
- alpha sweep
- component-level force mapping
- making ESP/OpenCSM a hard runtime dependency

## Planned Next Gates

1. Alpha sweep only after `mesh_study.v1` promotes the chosen baseline mesh/runtime to at least `preliminary_compare`
2. Real ESP/VSP main-wing 3D volume-insertion timeout repair before solver claims on the `main_wing` route
3. Run real fairing solver smoke now that drag/reference normalization is explicit; keep moment coefficients blocked until moment-origin policy is owned
4. Tail-wing `su2_handoff.v1` materialization smoke before tail solver claims
5. Component-level force mapping after the wall-marker story is stronger

## What A New Contributor Should Assume

- Start from the package root, not from old worktree memory
- Treat the provider-aware `aircraft_assembly` route as source of truth
- Treat `status=success` and `overall_convergence_gate` as separate signals: success means it ran, the gate says whether it is comparable
- Treat `mesh_study.v1` as the promotion gate before any alpha sweep work: if it says `still_run_only` or `insufficient`, do not pretend the baseline is ready to compare
- Treat everything else as scaffolding until it is promoted with a real backend and smoke evidence
