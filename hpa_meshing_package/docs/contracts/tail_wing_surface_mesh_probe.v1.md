# tail_wing_surface_mesh_probe.v1

`tail_wing_surface_mesh_probe.v1` records whether the real ESP-rebuilt tail
surfaces can be meshed by Gmsh as a 2D surface mesh.

It is intentionally not a CFD handoff contract:

- it consumes `data/blackcat_004_origin.vsp3` through `esp_rebuilt`
- it imports the normalized surface-only STEP into Gmsh
- it generates a 2D surface mesh with a `tail_wing` physical group
- it does not emit `mesh_handoff.v1`
- it does not create a farfield or fluid volume
- it does not run BL runtime
- it does not run `SU2_CFD`
- it does not change production defaults

## Current Observed Result

The current real tail surface probe passes as surface evidence:

- provider surface count: 6
- provider volume count: 0
- imported surface count: 6
- surface element count: 2286
- volume element count: 0

## Engineering Meaning

A pass here only means the provider surfaces are meshable and the `tail_wing`
surface marker can be owned in a 2D surface mesh. It does not mean the tail is
ready for external-flow SU2 analysis.

Before `SU2_CFD`, hpa-mdo still needs either:

1. provider-side solidification/capping that produces a valid closed body for
   farfield subtraction, or
2. a baffle-volume route that gives SU2 a legitimate external-flow volume mesh
   while preserving both sides of the lifting surface.
