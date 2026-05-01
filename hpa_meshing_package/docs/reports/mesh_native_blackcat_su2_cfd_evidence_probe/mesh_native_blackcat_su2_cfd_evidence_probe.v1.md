# Mesh-Native Black Cat SU2 CFD Evidence Probe

Date: 2026-05-01

## Purpose

Check whether the mesh-native Black Cat main-wing SU2 route still shows negative
drag after moving beyond smoke-scale meshes, and compare the Euler slip-wall
setup against a viscous wall-contract diagnostic.

This is CFD engineering evidence, not a final production validation package.
Raw large mesh/restart files were kept under `/tmp` during the run and are not
committed.

## Cases

| case | solver / wall | volume tets | nodes | quality | final iter | CL | CD | CMy |
| --- | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: |
| h=0.09 | `INC_EULER` / `MARKER_EULER` | 107,415 | 35,993 | pass, no warnings | 70 | 0.696225 | -0.148031 | 0.137433 |
| h=0.025 | `INC_EULER` / `MARKER_EULER` | 615,453 | 210,476 | pass, no warnings | 81 | 0.898460 | -0.087462 | 0.141785 |
| h=0.018 | `INC_EULER` / `MARKER_EULER` | 1,063,040 | 367,629 | pass, no warnings | 92 | 0.900420 | -0.075353 | 0.138954 |
| h=0.025 wall diagnostic | `INC_NAVIER_STOKES` / `MARKER_HEATFLUX=(wing_wall,0)` | 615,453 | 210,476 | same mesh | 93 | 0.288971 | 0.146000 | -0.069418 |

## Engineering Read

The high-density Euler trend is useful: increasing from 107k to 1.06M tets
moves CL toward about 0.90 and makes CD less negative, but CD remains negative
after numerical convergence. That means the issue is not just "the 100k mesh was
too coarse".

The same 615k mesh with a Navier-Stokes no-slip heatflux wall immediately gives
positive drag. Because this mesh has no boundary-layer prism strategy, the
viscous result is not final aerodynamic truth; however, it is a strong
diagnostic that the current Euler slip-wall route is not a valid drag route for
this closed thin-wing body.

SU2 documentation supports this wall-contract distinction: Euler/slip walls use
`MARKER_EULER`, while Navier-Stokes solid walls are normally modeled with
`MARKER_HEATFLUX` for adiabatic no-slip walls. SU2 also supports surface CSV
output through `SURFACE_CSV`, which should be retained for force-audit runs.

## Recommendation

Do not keep spending compute on global Euler refinement as the main fix. The
mesh-native generator has now proved million-cell mesh generation and SU2
handoff. The next CFD-valid route should be:

1. Add an explicit solver-wall profile: `euler_slip` versus `inc_ns_heatflux`.
2. Add wall-normal / boundary-layer refinement for the viscous route before
   interpreting drag.
3. Keep Euler runs for lift / pressure trend diagnostics, but do not treat
   Euler slip-wall CD as validated drag evidence for this closed faceted wing.
4. For the next expensive run, use a medium/high-density viscous wall mesh with
   local TE/tip/wake refinement, then compare CL/CD/Cm against the Euler trend.

## Sources

- SU2 markers and boundary conditions:
  https://su2code.github.io/docs_v7/Markers-and-BC/
- SU2 incompressible physical definition:
  https://su2code.github.io/docs_v7/Physical-Definition/
- SU2 custom output / `SURFACE_CSV`:
  https://su2code.github.io/docs_v7/Custom-Output/
