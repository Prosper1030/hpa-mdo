# Mesh-Native Blackcat BL Force Marker Audit

This report records a force/reference audit for the mesh-native VSP faceted Gmsh
boundary-layer route, case `pps32_span2_wing020`.

## Case

- Source case dir:
  `/tmp/hpa_mdo_vsp_faceted_gmsh_bl_probe_20260501/pps32_span2_wing020`
- Force-audit dir:
  `/tmp/hpa_mdo_vsp_faceted_gmsh_bl_probe_20260501/pps32_span2_wing020_force_audit`
- Mesh size: `1,137,058` volume cells, `532,403` nodes.
- Source SU2 run: converged at inner iteration `751`.
- Source final coefficients:
  - `CD = 0.7226281625`
  - `CL = 0.4500948651`
  - `CMy = -0.4423051199`

The force breakdown was generated from the converged ASCII restart with one
additional low-priority SU2 iteration. This is an output audit, not a new
convergence claim.

## Reference Alignment

Current SU2 config:

- `REF_AREA = 35.175 m^2`
- `REF_LENGTH = 1.130190 m`
- `REF_ORIGIN_MOMENT = (0.651164, 0.0, 0.382683) m`

`data/blackcat_004_full.avl`:

- `Sref = 35.175 m^2`
- `Cref = 1.130189765 m`
- `Bref = 33.0 m`

Sampled VSP faceted surface:

- span from mesh stations: `32.94930391715896 m`
- planform area from stations: `35.1314813836065 m^2`
- station count: `21`
- points per station: `62`

Assessment: the current mesh-native case uses the AVL full-wing `Sref` and
`Cref` for SU2 force normalization. The sampled VSP station surface is about
`0.15%` lower in span and about `0.12%` lower in planform area, which is small
enough to treat as geometry sampling/provenance rather than the cause of the
current CL gap. Older ESP/VSP handoff artifacts still contain `Cref = 1.0425 m`;
do not mix that old route reference length into this mesh-native BL case.

## Force Direction

Current SU2 config:

- `INC_VELOCITY_INIT = (6.5, 0.0, 0.0) m/s`
- `AOA = 0 deg`
- `SIDESLIP_ANGLE = 0 deg`

History output confirms:

- `CD == CFx`
- `CL == CFz`
- `CFy` is approximately zero

Assessment: for this run, drag is along the positive freestream/x direction and
lift is the z-force coefficient. The sign problem seen in earlier short
transients is not present in the converged 1.137M-cell case; long-run `CD` is
positive.

## Marker Ownership

SU2 mesh boundary markers:

| Marker | Boundary elements | SU2 boundary type |
|---|---:|---|
| `wing_wall` | `41,348` | `5` |
| `farfield` | `4,076` | `5` |

Current SU2 config:

- `MARKER_HEATFLUX = ( wing_wall, 0.0 )`
- `MARKER_MONITORING = ( wing_wall )`
- `MARKER_PLOTTING = ( wing_wall )`
- `MARKER_FAR = ( farfield )`

Assessment: only `wing_wall` is a wall marker and only `wing_wall` is monitored
for force. `farfield` is not part of force integration.

## Force Breakdown

`forces_breakdown.dat` reports only one monitored surface:

- `Surface name: wing_wall`

Total coefficients:

| Coefficient | Total | `wing_wall` |
|---|---:|---:|
| `CL` | `0.450181` | `0.450181` |
| `CD` | `0.722552` | `0.722552` |
| `CMy` | `-0.442323` | `-0.442323` |
| `CFx` | `0.722552` | `0.722552` |
| `CFy` | `-0.000001` | `-0.000001` |
| `CFz` | `0.450181` | `0.450181` |

Selected pressure/friction split:

| Coefficient | Pressure | Friction |
|---|---:|---:|
| `CD` | `0.607320` | `0.115232` |
| `CL` | `0.455783` | `-0.005603` |
| `CMy` | `-0.434068` | `-0.008255` |

Assessment: there is no weird non-wing marker contributing a large amount of
drag. The total force is the same as `wing_wall`.

## Engineering Notes

- This audit clears the force-reference and marker-leakage concern for the
  current mesh-native BL case.
- It does not prove the CFD is physically final: `CL` is still far below the
  VSPAERO panel reference, and grid independence has not been established.
- The next engineering work should be mesh refinement and half-wing/symmetry
  cost reduction, then viscous/turbulence/transition setup checks, not another
  marker/force ownership patch.
