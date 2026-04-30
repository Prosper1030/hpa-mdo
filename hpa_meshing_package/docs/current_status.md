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
| force-surface provenance gate | fixed | currently whole-aircraft wall only |

## Experimental

| Capability | Status | Why |
| --- | --- | --- |
| `esp_rebuilt` provider | experimental | native OpenCSM rule-loft rebuild 已可 materialize normalized geometry；`main_wing` aircraft-only coarse 2D 已可穿過，但 full external-flow route 的 default sizing 仍卡在 downstream Gmsh meshing |
| `main_wing` / `tail_wing` | experimental | dispatch exists, real backend not productized |
| `fairing_solid` / `fairing_vented` | experimental | dispatch exists, real backend not productized |
| direct multi-family package configs | experimental | do not present as formal current route |

If a route returns `route_stage=placeholder`, it is not a formal meshing result.

## ESP Current Reality

- `esp_rebuilt` 已不再是 `not_materialized` stub。`src/hpa_meshing/providers/esp_pipeline.py` 現在走 native OpenCSM lifting-surface rebuild：從 `.vsp3` 讀 wing/tail sections，生成 rule-loft `.csm`，再用 `serveCSM -batch` 輸出 normalized STEP 與 topology artifact。
- 這台 Mac mini（macOS 26.4.1 / arm64）的 runtime truth 已更新：`serveESP` / `serveCSM` 在 `PATH` 上、`ocsm` 仍缺席，但 batch 路徑可以直接用 `serveCSM`。因此 provider 在本機已經 runnable，不再被 `esp_runtime_missing` 擋住。
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
2. Component-level force mapping after the wall-marker story is stronger

## What A New Contributor Should Assume

- Start from the package root, not from old worktree memory
- Treat the provider-aware `aircraft_assembly` route as source of truth
- Treat `status=success` and `overall_convergence_gate` as separate signals: success means it ran, the gate says whether it is comparable
- Treat `mesh_study.v1` as the promotion gate before any alpha sweep work: if it says `still_run_only` or `insufficient`, do not pretend the baseline is ready to compare
- Treat everything else as scaffolding until it is promoted with a real backend and smoke evidence
