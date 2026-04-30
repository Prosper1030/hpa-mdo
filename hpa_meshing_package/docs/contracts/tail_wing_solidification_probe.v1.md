# tail_wing_solidification_probe.v1

`tail_wing_solidification_probe.v1` records whether naive Gmsh
`healShapes(..., sewFaces=True, makeSolids=True)` can turn the real
ESP-rebuilt tail surfaces into OCC volumes.

It is intentionally not a repair route:

- it consumes `data/blackcat_004_origin.vsp3` through `esp_rebuilt`
- it imports the normalized surface-only STEP into Gmsh
- it tries bounded heal/sew/makeSolids parameter variants
- it records the best output surface and volume counts
- it does not emit `mesh_handoff.v1`
- it does not create a farfield or fluid volume
- it does not run BL runtime
- it does not run `SU2_CFD`
- it does not change production defaults

## Current Observed Result

The current real tail solidification probe does not create a volume:

- provider surface count: 6
- provider volume count: 0
- best output surface count: 12
- best output volume count: 0
- recommended next: `explicit_caps_or_baffle_volume_route_required`

## Engineering Meaning

This rules out "just tune Gmsh heal" as the next serious path for the real
tail. hpa-mdo needs an explicit geometry operation:

1. construct owned caps and a closed thin body before the OCC external-flow
   route, or
2. construct a baffle-volume route that gives SU2 a legitimate volume mesh
   while preserving both sides of the lifting surface.
