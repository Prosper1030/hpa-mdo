# tail_wing_explicit_volume_route_probe.v1

`tail_wing_explicit_volume_route_probe.v1` records whether the real
ESP-rebuilt tail surfaces can be promoted from surface-only geometry into an
owned external-flow volume route before any SU2 claim.

The probe is report-only:

- it consumes `data/blackcat_004_origin.vsp3`
- it selects the OpenVSP `Elevator` through the `esp_rebuilt` provider
- it tries `occ.addSurfaceLoop(..., sewing=True)` plus `occ.addVolume(...)`
- it tries an OCC baffle-fragment route inside a farfield box
- it does not emit `mesh_handoff.v1`
- it does not emit `su2_handoff.v1`
- it does not run `SU2_CFD`
- it does not change production defaults

## Current Observation

The current real tail probe is still blocked:

- provider surface count: 6
- provider volume count: 0
- surface-loop volume status: `volume_created`
- surface-loop signed volume: negative
- surface-loop farfield cut status: `invalid_fluid_boundary`
- baffle fragment status: `mesh_failed_plc`
- mesh handoff status: `not_written`

Engineering reading: a Gmsh volume tag is not enough. The surface loop creates
an explicit candidate volume, but its orientation / signed-volume behavior does
not yield a valid external-flow farfield cut. The baffle route owns a farfield
volume candidate, but the current duplicated baffle surfaces still ask Gmsh to
recover invalid boundary topology.

## Promotion Rule

This probe can only become a real mesh-handoff smoke after either:

1. the explicit capped/surface-loop body has a valid orientation and farfield
   subtraction with component-owned `tail_wing` and `farfield` markers, or
2. the baffle-volume route owns a non-duplicated wall/baffle surface set that
   meshes without PLC failure.

Until then, `tail_wing` remains blocked before real `mesh_handoff.v1`, and the
synthetic tail slab evidence must not be treated as real tail evidence.
