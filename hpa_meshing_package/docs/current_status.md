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
| `esp_rebuilt` provider | experimental | runtime discovery + OpenVSP→ESP batch pipeline skeleton；smoke 仍被卡在本機未安裝 ESP129 |
| `main_wing` / `tail_wing` | experimental | dispatch exists, real backend not productized |
| `fairing_solid` / `fairing_vented` | experimental | dispatch exists, real backend not productized |
| direct multi-family package configs | experimental | do not present as formal current route |

If a route returns `route_stage=placeholder`, it is not a formal meshing result.

## ESP Current Reality

- `esp_rebuilt` 已從「只回 not_materialized」的 stub 升級成 fail-loud provider：`src/hpa_meshing/providers/esp_rebuilt.py` 會先呼叫 `detect_esp_runtime()`，runtime 缺席時回傳 `status="failed"` + `failure_code="esp_runtime_missing"` 並把缺了哪些 binary 附在 provenance 與 `provider_log.json`。
- `src/hpa_meshing/providers/esp_pipeline.py` 已實作官方 `UDPRIM vsp3` batch skeleton（`serveCSM` / `ocsm` -batch + DUMP STEP），含 runner 與 batch_binary 注入點；測試以 fake runner 覆蓋 success / nonzero / 缺 binary 三條路徑。
- 這台 Mac mini（macOS 26.4.1 / arm64）仍未安裝 `ESP129-macos-arm64`，所以 2026-04-21 跑的 blackcat coarse smoke（`.tmp/runs/blackcat_004_coarse_esp_rebuilt/`）仍在 provider 階段停下；`failure_code=esp_runtime_missing`、失敗訊息指名 `serveESP / serveCSM / ocsm` 缺席，不是 Gmsh 問題。
- 結論：`esp_rebuilt` 目前仍是 experimental、在本機仍非 runnable；唯一剩下的 blocker 是安裝 ESP129 並把 `serveCSM` / `ocsm` 放上 `PATH`。
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
