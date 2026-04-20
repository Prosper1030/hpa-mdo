# Provider Integration Mainline

Date: 2026-04-20

This note records the first provider-aware mainline for `hpa_meshing_package`.

## Mainline Decisions

- `hpa_meshing_package` now treats geometry normalization as a formal provider layer instead of scattered case patching.
- `geometry-family-first` remains the core dispatch rule after normalization.
- `openvsp_surface_intersection` is the first v1 provider.
- `esp_rebuilt` is registered only as an experimental provider contract in this round.

## Provider Roles

### `openvsp_surface_intersection`

- Input: `.vsp3`
- Output: normalized trimmed STEP artifact
- Geometry source: `provider_generated`
- Intended family hints:
  - `thin_sheet_lifting_surface`
  - `thin_sheet_aircraft_assembly`
- Required artifacts:
  - normalized geometry
  - topology report
  - provider log

### `esp_rebuilt`

- Status: experimental
- Geometry source: `esp_rebuilt`
- This round does not require local ESP/OpenCSM runtime or end-to-end materialization.
- The provider stays in the registry so reports and provenance can say `experimental` and `not_materialized` explicitly.

## Provenance Anchors

- B-line core: `codex/hpa-meshing-geometry-platform`
- A-line spike: `codex/hpa-meshing-esp-spike`
- A-line evidence kept unchanged:
  - `docs/esp_opencsm_feasibility.md`
  - `experiments/esp_spike/feasibility_summary.json`

## Expected Report Signals

Every provider-aware run should make these fields obvious:

- `geometry`
- `normalized_geometry`
- `geometry_source`
- `geometry_provider`
- `geometry_family`
- `meshing_route`
- provider topology/provenance artifacts
