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
```

它不是最終高品質 CFD framework，也不是 `origin-su2-high-quality` 那條 case-specific workflow 的包裝版。

## Read This First

1. `README.md`
2. [`docs/current_status.md`](docs/current_status.md)
3. [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
4. Contract docs in [`docs/contracts/`](docs/contracts)

## Official v1 Scope

### Works now

- `openvsp_surface_intersection` 是正式 `v1` geometry provider。
- 正式可執行的 meshing route 是 `aircraft_assembly` / `thin_sheet_aircraft_assembly`。
- Gmsh backend 會真的產生外流場 volume mesh，並輸出 `mesh_handoff.v1`。
- package-native SU2 baseline 會真的 materialize case、跑 `SU2_CFD`、parse history、輸出 `su2_handoff.v1`。
- reference provenance gate 和 force-surface provenance gate 已經接進 baseline SU2 handoff。

### Not in v1

- mesh study / iterative convergence gate
- alpha sweep
- component-level force mapping
- final high-quality credibility claim
- ESP/OpenCSM runtime hard dependency

## Experimental / Placeholder Areas

- `esp_rebuilt` 目前只保留 experimental provider contract，沒有要求本輪 materialize 成功。
- `main_wing` / `tail_wing` / `fairing_solid` / `fairing_vented` 的 schema、family dispatch、route registry 已經存在，但 backend 仍是 placeholder，不是正式可交付路徑。
- 目前只有 `gmsh_thin_sheet_aircraft_assembly` 會走真實 Gmsh meshing；其他 route 會回 `route_stage=placeholder`。

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
- `artifacts/providers/openvsp_surface_intersection/normalized.stp`
- `artifacts/mesh/mesh_metadata.json`
- `artifacts/mesh/marker_summary.json`
- `artifacts/su2/alpha_0_baseline/su2_handoff.json`
- `artifacts/su2/alpha_0_baseline/history.csv`

## Artifact Contracts

- [`GeometryProviderResult`](docs/contracts/GeometryProviderResult.md)
- [`mesh_handoff.v1`](docs/contracts/mesh_handoff.v1.md)
- [`su2_handoff.v1`](docs/contracts/su2_handoff.v1.md)
- [`reference / force-surface provenance gates`](docs/contracts/provenance_gates.md)

## Capability Boundaries

| Area | Status | Notes |
| --- | --- | --- |
| `openvsp_surface_intersection` provider | formal `v1` | `.vsp3 -> normalized STEP -> topology report` |
| `aircraft_assembly` family dispatch | formal `v1` | provider-aware + geometry-family-first |
| Gmsh backend for `thin_sheet_aircraft_assembly` | formal `v1` | real external-flow volume mesh |
| `mesh_handoff.v1` | fixed contract | downstream mesh handoff |
| `su2_handoff.v1` | fixed contract | baseline case materialization + history parse |
| Reference provenance gate | fixed contract | `geometry_derived`, `baseline_envelope_derived`, or `user_declared` |
| Force-surface provenance gate | fixed contract | currently whole-aircraft wall only |
| `esp_rebuilt` | experimental | registry + reporting only |
| Other component families | experimental | schema/dispatch exists, backend placeholder |
| Mesh convergence gate | roadmap | next planned production hardening step |
| Alpha sweep | roadmap | after convergence gate |
| Component-level force mapping | roadmap | not implemented yet |

## Recommended Next Gates

1. `mesh / iterative convergence gate`
2. `alpha sweep`
3. component-level force mapping
4. more providers only after the current product line is harder to validate

ESP/OpenCSM can remain experimental until it earns a separate formal promotion.
