# VSP-native Black Cat high-density SU2 smoke

## Bottom line

The VSP-native mesh-native route now reaches a **million-class mesh** and SU2 can read and run it.

This is the real Black Cat main-wing route from `blackcat_004_origin.vsp3`, not a NACA surrogate. It uses OpenVSP-extracted main-wing sections, including the embedded high-lift airfoils (`FX 76-MP-140` / `CLARK-Y 11.7% smoothed`) already identified in the geometry provenance probe.

## What ran

- geometry: OpenVSP-native Black Cat main wing
- reference: `Sref = 35.175`, `Cref = 1.130189765`, `Bref = 33.0` from AVL
- points per side: `32`
- spanwise subdivisions: `2`
- feature refinement size: `3.0`
- farfield mesh size: `18.0`
- wing refinement radius: `12.0`
- mesh sizes: `0.025`, `0.022`, `0.020`
- target: `1,000,000` volume elements
- guard: `1,800,000` volume elements

## Mesh result

| h | nodes | tets | quality gate |
|---:|---:|---:|---|
| 0.025 | 258,378 | 717,901 | pass, warnings: `very_low_min_gamma`, `low_p01_gamma` |
| 0.022 | 345,491 | 950,904 | pass, warning: `very_low_min_gamma` |
| 0.020 | 372,577 | 1,032,855 | pass, warning: `very_low_min_gamma` |

Selected high-density case:

- case dir: `/tmp/hpa_mdo_blackcat_vsp_native_high_density_ladder/02_span_2_pps_32_feat_3_h_0p02`
- `.msh`: about `77 MB`
- `.su2`: about `74 MB`
- no ill-shaped tets
- no non-positive volume / SICN / SIGE elements
- `min_gamma = 5.47e-6`
- `gamma p01 = 0.0215`
- `gamma p05 = 0.0638`
- `min_sicn = 4.64e-4`

Engineering read: this is acceptable as a high-density no-BL SU2 smoke mesh. It is not clean enough to call production-quality because the isolated `min_gamma` sliver warning is real.

## SU2 smoke

The selected mesh was converted with:

```bash
gmsh mesh.msh -0 -format su2 -o mesh.su2 -save -v 2
```

Marker audit:

- `NELEM = 1,032,855`
- `NPOIN = 372,577`
- `NMARK = 2`
- `wing_wall = 677,260` surface triangles
- `farfield = 520` surface triangles
- marker audit: pass

Solver smoke:

- solver: `INC_NAVIER_STOKES`
- wall BC: `MARKER_HEATFLUX = ( wing_wall, 0.0 )`
- farfield: `MARKER_FAR = ( farfield )`
- velocity: `6.5 m/s`
- max iterations: `5`
- threads: `4`
- result: SU2 exit success, finite coefficients

Final smoke coefficients at iteration 4:

- `CL = 0.5348469092`
- `CD = 0.2248723315`
- `CMy = -0.1333902841`
- `L/D = 2.378446942`

The solver stopped because `ITER = 5`, not because the flow converged. The coefficients are therefore only a readability/finite-force smoke result.

## Engineering decision

This proves:

1. VSP-native geometry can produce a million-class mesh without STEP/BREP repair.
2. The mesh can be converted to SU2 and passes marker audit.
3. SU2 can run the high-density mesh and returns finite, positive drag.

This does **not** prove:

1. grid independence,
2. final CL/CD/Cm,
3. credible HPA drag,
4. boundary-layer correctness.

The next physical CFD move should still be a wall-resolved boundary-layer route with owned near-wall topology. A 2000-iteration run on this no-BL tetra mesh would mainly test solver stability, not the real viscous aircraft-wing physics.
