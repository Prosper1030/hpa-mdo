# Mesh-Native Black Cat VSP SU2 Iter1000

Date: 2026-05-01

## Purpose

Record the first long VSP-native mesh-native SU2 run after removing the
VSP/ESP STEP/BREP repair path from the CFD geometry critical path.

This run is a solver and marker evidence case, not final aerodynamic validation.

## Case

| item | value |
| --- | ---: |
| geometry source | OpenVSP-native section extraction |
| mesh route | mesh-native faceted wing + Gmsh tet volume |
| volume elements | 717,901 |
| nodes | 258,378 |
| wing marker elems | 469,776 |
| farfield marker elems | 518 |
| solver | `INC_NAVIER_STOKES` |
| wall BC | `MARKER_HEATFLUX=(wing_wall,0.0)` |
| iterations | 1000 configured, final row 999 |
| SU2 exit | success |

## Result

| coefficient | final |
| --- | ---: |
| CL | 0.2599127154 |
| CD | 0.1534721017 |
| CMy | -0.0903945690 |
| L/D | 1.693550245 |

Over the last 200 iterations, the relative ranges were tiny:

| metric | last-200 relative range |
| --- | ---: |
| CL | 5.99e-7 |
| CD | 1.42e-6 |
| CMy | 7.43e-8 |
| CMz | 5.22e-5 |

SU2 still printed `Cauchy[CD]=3.91e-9`, above the strict configured
`1e-10` criterion, so the code-level convergence flag is not technically met.
Engineering-wise, the integrated coefficients are essentially flat.

## Engineering Read

CD is not negative after the long viscous run. The earlier negative-CD concern is
therefore an Euler/slip-wall route problem, not a persistent SU2 force-sign
problem.

The result is still not drag-credible. This mesh has no prism boundary layer and
no wall-resolved y+ evidence. For a main-wing Reynolds number around 5.0e5, that
is a big deal: the near-wall velocity gradient is where viscous drag lives.
Using this run as final CD would be like judging wing skin friction from a mesh
that can see the wing shape but not the boundary layer.

Compared with the existing VSPAERO panel reference at the same nominal operating
point (`V=6.5 m/s`, `AoA=0 deg`, `Sref=35.175 m2`), this SU2 run is far away:

| source | CL | CD | L/D |
| --- | ---: | ---: | ---: |
| VSPAERO panel reference | 1.287645 | 0.045068 | 28.5711 |
| SU2 no-BL tet viscous run | 0.259913 | 0.153472 | 1.6936 |

Do not use this mismatch alone to blame the geometry. It says the current CFD
setup is not yet a physically comparable HPA wing CFD setup.

## CFD Setup Research Notes

Current HPA condition estimate from the committed advisory helper:

| chord reference | Reynolds number |
| --- | ---: |
| tip chord 0.435 m | 1.94e5 |
| MAC 1.13019 m | 5.03e5 |
| root chord 1.30 m | 5.78e5 |

Recommended first BL target for wall-resolved RANS:

| item | value |
| --- | ---: |
| first cell for y+ about 1 | 4.85e-5 m |
| practical first layer | 5.0e-5 m |
| layers | 24 |
| growth ratio | 1.24 |
| total BL thickness | 0.0362 m |

This matches the prior `shell_v4` Mac-safe BL direction, but that route is still
diagnostic for the real main wing because the tip/root BL transition topology is
not fully production-ready.

## Next Step

The next serious physics route should be half-wing symmetry + explicit prism BL:

1. Use `symmetry` marker at the root plane and half reference area for SU2.
2. Use `INC_RANS` with SA as the first grid-study model.
3. Use wall-resolved no-slip walls with y+ around 1 before trusting drag.
4. Generate coarse / medium / fine half-wing BL meshes around roughly 0.9M,
   1.8M, and 3.0M cells under a 12 GB RAM cap.
5. Run up to 2000 iterations and select the cheapest adjacent mesh pair where
   CL/CD/Cm changes are within the configured percent tolerances.

## Sources

- SU2 documents `INC_RANS`, SA/SST turbulence support, and wall-function vs
  wall-resolved y+ expectations: https://su2code.github.io/docs_v7/Theory/
- SU2 marker docs define `MARKER_SYM`, `MARKER_HEATFLUX`, `MARKER_FAR`, and
  wall-function syntax: https://su2code.github.io/docs_v7/Markers-and-BC/
- SU2's incompressible turbulent NACA0012 tutorial uses `INC_RANS` + SA,
  no-slip/farfield BCs, and a TMR mesh with y+ < 1:
  https://su2code.github.io/tutorials/Inc_Turbulent_NACA0012/
- Gmsh documents topological boundary-layer extrusion through
  `Extrude { Surface{...}; Layers{...}; }`, with the important limitation that
  this is only available in the built-in kernel:
  https://gmsh.info/doc/texinfo/
- NASA/TMBWG TMR NACA0012 grids are nested grid families with very fine wall
  spacing, farfield about 500 chords, and explicit grid-convergence intent:
  https://tmbwg.github.io/turbmodels/naca0012numerics_grids.html
