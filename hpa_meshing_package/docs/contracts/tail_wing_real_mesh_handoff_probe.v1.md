# tail_wing_real_mesh_handoff_probe.v1

`tail_wing_real_mesh_handoff_probe.v1` records the first real-provider tail
geometry attempt against the current `gmsh_thin_sheet_surface` mesh handoff
route.

It is intentionally a blocker report:

- it consumes `data/blackcat_004_origin.vsp3` through `esp_rebuilt`
- it invokes the current Gmsh thin-sheet route
- it does not run BL runtime
- it does not run `SU2_CFD`
- it does not change production defaults
- it is allowed to report `mesh_handoff_blocked`

## Current Observed Blocker

The real tail geometry currently materializes as a surface-only STEP:

- provider surface count: 6
- provider body count: 0
- provider volume count: 0

The current `gmsh_thin_sheet_surface` backend expects imported OCC volumes for
its external-flow path, so no `mesh_handoff.v1` is emitted for this real tail
geometry.

## Pass Meaning

This contract does not require a mesh pass. Its value is the explicit evidence
that synthetic closed-solid tail slabs are not equivalent to real ESP tail
geometry. The next architecture decision is either:

1. add a surface-only lifting-surface mesh route, or
2. solidify/cap the provider output before using the existing OCC-volume route.
