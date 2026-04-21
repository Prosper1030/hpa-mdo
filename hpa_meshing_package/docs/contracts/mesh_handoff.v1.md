# mesh_handoff.v1

`mesh_handoff.v1` is the fixed contract emitted by the package-native meshing backend.

## Purpose

It is the boundary between:

- geometry/provider/dispatch/meshing work
- downstream CFD consumers such as baseline SU2

## Required Fields

- `contract`
- `route_stage`
- `backend`
- `backend_capability`
- `meshing_route`
- `geometry_family`
- `geometry_source`
- `geometry_provider`
- `source_path`
- `normalized_geometry_path`
- `units`
- `mesh_format`
- `body_bounds`
- `farfield_bounds`
- `mesh_stats`
- `marker_summary`
- `physical_groups`
- `artifacts`
- `provenance`

## Artifacts

`artifacts` currently points to:

- `mesh`
- `mesh_metadata`
- `marker_summary`

The canonical metadata example is `artifacts/mesh/mesh_metadata.json`.

## Current Formal v1 Interpretation

For the official package route:

- `route_stage=baseline`
- `meshing_route=gmsh_thin_sheet_aircraft_assembly`
- `backend=gmsh`
- wall marker is currently the whole-aircraft marker `aircraft`
- farfield marker is currently `farfield`

If a route does not produce this contract and instead reports `route_stage=placeholder`, it is not part of the formal product line.
