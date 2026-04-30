# hpa-meshing-package

`hpa_meshing_package` 是 `hpa-mdo` 內正式追蹤的 meshing product root，目標是把已經跑通的 provider-aware meshing + package-native SU2 baseline 能力收斂成一個可交付、可維護、可繼續擴展的 Python package。

這個 package 目前代表的正式主線是：

```text
.vsp3
  -> openvsp_surface_intersection
  -> normalized trimmed STEP
  -> geometry-family-first dispatch
  -> gmsh_thin_sheet_aircraft_assembly
  -> mesh_handoff.v1
  -> su2_handoff.v1
  -> history / CL / CD / CM
  -> convergence_gate.v1
```

它不是最終高品質 CFD framework，也不是 `origin-su2-high-quality` 那條 case-specific workflow 的包裝版。

## Read This First

1. `README.md`
2. [`docs/current_status.md`](docs/current_status.md)
3. [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
4. Contract docs in [`docs/contracts/`](docs/contracts)
5. High-fidelity route decision: [`../docs/research/high_fidelity_route_decision_2026-04-30.md`](../docs/research/high_fidelity_route_decision_2026-04-30.md)

## Official v1 Scope

### Works now

- `openvsp_surface_intersection` 是正式 `v1` geometry provider。
- 正式可執行的 meshing route 是 `aircraft_assembly` / `thin_sheet_aircraft_assembly`。
- Gmsh backend 會真的產生外流場 volume mesh，並輸出 `mesh_handoff.v1`。
- package-native SU2 baseline 會真的 materialize case、跑 `SU2_CFD`、parse history、輸出 `su2_handoff.v1`。
- reference provenance gate 和 force-surface provenance gate 已經接進 baseline SU2 handoff。
- mesh / iterative convergence gate 會直接寫進 `su2_handoff.v1` 與 `report.json`，明確標示這次 baseline run 是 `preliminary_compare`、`run_only` 還是 `not_comparable`。
- package-native mesh study 會用 `coarse / medium / fine` 預設，連跑同一幾何的 baseline CFD，並輸出 `mesh_study.v1`。

### Not in v1

- alpha sweep
- component-level force mapping
- final high-quality credibility claim
- ESP/OpenCSM runtime hard dependency

## Experimental / Placeholder Areas

- `esp_rebuilt` 目前已經能在本機 materialize provider-normalized geometry，但仍停留在 experimental：它不是 formal `v1` route，而且 blackcat meshing smoke 目前還卡在 downstream Gmsh `Mesh2D` hang。
- `main_wing` / `tail_wing` / `fairing_solid` / `fairing_vented` 的 schema、family dispatch、route registry 已經存在，但 backend 仍是 placeholder，不是正式可交付路徑。
- 目前只有 `gmsh_thin_sheet_aircraft_assembly` 會走真實 Gmsh meshing；其他 route 會回 `route_stage=placeholder`。
- `shell_v4` 是 BL / solver-entry diagnostic branch，不是任意主翼 product route；BL route 只有在 hpa-mdo owns transition sleeve / receiver faces / interface loops / layer-drop events 之後才可 promotion。

## ESP Reality Check

- `esp_rebuilt` 在目前 `main` 上已經不再是 `not_materialized` stub。它現在會走 native OpenCSM lifting-surface rebuild：從 `.vsp3` 讀 wing/tail sections，生成 rule-loft `.csm`，再用 `serveCSM -batch` 輸出 normalized STEP 與 topology artifact。
- 這台 Mac mini M4（macOS 26.4.1 / arm64）目前可用的 runtime truth 是：`serveESP` / `serveCSM` 在 `PATH` 上、`ocsm` 仍缺席，但 batch 路徑可以直接用 `serveCSM`。所以 `detect_esp_runtime()` 會回 `available=true`、`batch_binary=serveCSM`，provider 已可執行。
- 2026-04-21 的 provider smoke 已經成功 materialize：`hpa_meshing_package/.tmp/runs/blackcat_004_esp_rebuilt_native_provider_smoke/` 內有 `normalized.stp` / `topology.json` / `provider_log.json`。主翼單體 smoke 也能 materialize：`hpa_meshing_package/.tmp/runs/blackcat_004_esp_rebuilt_main_wing_mesh_only_hang_probe/`。
- 目前真正的 blocker 已經往後移：不是 provider runtime 缺失，而是 downstream Gmsh surface meshing 仍會 hang。`sample` 顯示 main-wing mesh-only smoke 卡在 `gmsh::model::mesh::generate(2) -> Mesh2D -> bowyerWatsonFrontal -> insertAPoint`。
- 結論：`esp_rebuilt` 現在是「provider runnable but route not yet production-ready」。下一步不是再補 runtime 安裝，而是把 native ESP geometry 接到更穩的 Gmsh meshing policy / diagnostics。
- 實作規劃請看 [ESP Rebuilt Provider Enablement Implementation Plan](../docs/superpowers/plans/2026-04-21-esp-rebuilt-provider-enablement.md)。

## Quick Start

### 1. Run tests

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src /Volumes/Samsung\ SSD/hpa-mdo/.venv/bin/python -m pytest tests -q
```

### 2. Validate provider-normalized geometry

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src /Volumes/Samsung\ SSD/hpa-mdo/.venv/bin/python -m hpa_meshing.cli validate-geometry \
  --component aircraft_assembly \
  --geometry ../data/blackcat_004_origin.vsp3 \
  --geometry-provider openvsp_surface_intersection \
  --out .tmp/runs/blackcat_004_validate
```

This validates the provider-aware path and writes `report.json` / `report.md` plus provider artifacts under `.tmp/runs/blackcat_004_validate/artifacts/providers/`.

### 3. Run baseline CFD from package root

The copy-paste config for the canonical smoke is:

- [`configs/aircraft_assembly.openvsp_baseline.yaml`](configs/aircraft_assembly.openvsp_baseline.yaml)

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src /Volumes/Samsung\ SSD/hpa-mdo/.venv/bin/python -m hpa_meshing.cli run \
  --config configs/aircraft_assembly.openvsp_baseline.yaml
```

This produces:

- `report.json`
- `report.md`
- `artifacts/providers/openvsp_surface_intersection/normalized.stp`
- `artifacts/mesh/mesh_metadata.json`
- `artifacts/mesh/marker_summary.json`
- `artifacts/su2/alpha_0_baseline/su2_handoff.json`
- `artifacts/su2/alpha_0_baseline/history.csv`

### 4. Run the minimal baseline mesh study

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src /Volumes/Samsung\ SSD/hpa-mdo/.venv/bin/python -m hpa_meshing.cli mesh-study \
  --config configs/aircraft_assembly.openvsp_baseline.yaml \
  --out .tmp/runs/blackcat_004_mesh_study
```

This produces:

- `report.json` with the `mesh_study.v1` payload
- `cases/coarse/report.json`
- `cases/medium/report.json`
- `cases/fine/report.json`

### 5. Write the component-family route-readiness report

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src /Volumes/Samsung\ SSD/hpa-mdo/.venv/bin/python -m hpa_meshing.cli route-readiness \
  --out .tmp/runs/component_family_route_readiness
```

This produces:

- `component_family_route_readiness.v1.json`
- `component_family_route_readiness.v1.md`

Use this report before choosing the next high-fidelity repair target. It keeps
the formal `aircraft_assembly` route separate from experimental main-wing,
tail, fairing, and `shell_v4` BL-promotion work.

### 6. Write the component-family route smoke matrix

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src /Volumes/Samsung\ SSD/hpa-mdo/.venv/bin/python -m hpa_meshing.cli component-family-smoke-matrix \
  --out .tmp/runs/component_family_route_smoke_matrix
```

This produces:

- `component_family_route_smoke_matrix.v1.json`
- `component_family_route_smoke_matrix.v1.md`

This is a pre-mesh dispatch smoke only. It checks that main-wing, tail, and
fairing component families classify and dispatch to registered routes without
using `root_last3`; it does not run Gmsh, BL runtime, SU2, or any production
mesh promotion.

## Artifact Contracts

- [`GeometryProviderResult`](docs/contracts/GeometryProviderResult.md)
- [`mesh_handoff.v1`](docs/contracts/mesh_handoff.v1.md)
- [`su2_handoff.v1`](docs/contracts/su2_handoff.v1.md)
- [`convergence_gate.v1`](docs/contracts/convergence_gate.v1.md)
- [`mesh_study.v1`](docs/contracts/mesh_study.v1.md)
- [`component_family_route_smoke_matrix.v1`](docs/contracts/component_family_route_smoke_matrix.v1.md)
- [`reference / force-surface provenance gates`](docs/contracts/provenance_gates.md)

## Capability Boundaries

| Area | Status | Notes |
| --- | --- | --- |
| `openvsp_surface_intersection` provider | formal `v1` | `.vsp3 -> normalized STEP -> topology report` |
| `aircraft_assembly` family dispatch | formal `v1` | provider-aware + geometry-family-first |
| Gmsh backend for `thin_sheet_aircraft_assembly` | formal `v1` | real external-flow volume mesh |
| `mesh_handoff.v1` | fixed contract | downstream mesh handoff |
| `su2_handoff.v1` | fixed contract | baseline case materialization + history parse |
| `convergence_gate.v1` | fixed contract | machine-readable mesh / iterative / overall comparability gate |
| Reference provenance gate | fixed contract | `geometry_derived`, `baseline_envelope_derived`, or `user_declared` |
| Force-surface provenance gate | fixed contract | currently whole-aircraft wall only |
| `esp_rebuilt` | experimental | native OpenCSM rule-loft provider is runnable on this machine, but blackcat meshing smoke still hangs in downstream Gmsh `Mesh2D` |
| Other component families | experimental | schema/dispatch exists, backend placeholder |
| Component-family route readiness | report-only `v1` | emits current route status so root_last3 / shell_v4 does not get mistaken for the product mainline |
| Component-family route smoke matrix | report-only `v1` | pre-mesh dispatch smoke for main-wing / tail / fairing route skeletons; no Gmsh, no SU2, no BL runtime |
| Mesh study | formal minimal `v1` | three-tier baseline study that emits `mesh_study.v1` and decides whether the baseline stays `run_only` or can move to `preliminary_compare` |
| Alpha sweep | roadmap | after the chosen mesh/runtime clears the mesh-study verdict |
| Component-level force mapping | roadmap | not implemented yet |

## Recommended Next Gates

1. `alpha sweep`, but only after `mesh_study.v1` says the baseline is at least `preliminary_compare`
2. component-level force mapping
3. more providers only after the current product line is harder to validate

ESP/OpenCSM can remain experimental until it earns a separate formal promotion.
