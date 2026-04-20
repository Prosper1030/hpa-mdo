# GeometryProviderResult

`GeometryProviderResult` is the formal output contract of the geometry provider layer.

## Purpose

It answers:

- what provider ran
- whether geometry was materialized
- where the normalized geometry artifact lives
- what geometry family hint the provider is declaring
- what topology / units / provenance information downstream stages may trust

## Required Signals

- `provider`
- `provider_stage`
- `status`
- `geometry_source`
- `source_path`
- `normalized_geometry_path` when materialized
- `geometry_family_hint`
- `topology`
- `artifacts`
- `provenance`

## Current Formal v1 Expectation

For `openvsp_surface_intersection`:

- input is `.vsp3`
- output is a normalized trimmed STEP
- `geometry_source` is `provider_generated`
- `geometry_family_hint` is expected to be `thin_sheet_aircraft_assembly` or another thin-sheet family
- artifacts include:
  - `normalized_geometry`
  - `topology_report`
  - `provider_log`

## Experimental Allowance

Experimental providers may legally return:

- `status=not_materialized`
- `normalized_geometry_path=null`

That is how `esp_rebuilt` currently reports its placeholder state without pretending it is a runnable path.
