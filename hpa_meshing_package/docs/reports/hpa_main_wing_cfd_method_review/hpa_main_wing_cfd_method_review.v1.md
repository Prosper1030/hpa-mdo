# HPA main-wing CFD method review

## Bottom line

For the Black Cat human-powered-aircraft main wing at `V = 6.5 m/s`, the Reynolds-number range is roughly:

- tip chord: `1.94e5`
- mean aerodynamic chord: `5.03e5`
- root chord: `5.78e5`

That is a low-Mach, low-Reynolds, transition-sensitive wing problem. The right engineering path is:

1. Use `INC_NAVIER_STOKES` only for no-slip setup and marker smoke.
2. Use `INC_RANS + SA` as the first robust grid-study baseline.
3. Use `INC_RANS + SST + LM transition` after the boundary-layer mesh is reliable.
4. Do not use Euler/no-BL tetra meshes to judge drag.

## Current route status

The latest VSP-native mesh-native route is good enough for high-density SU2 readability:

- real VSP main-wing geometry, not NACA
- `1,032,855` tetrahedra
- `372,577` nodes
- no ill-shaped tets
- no non-positive volume / SICN / SIGE elements
- marker audit passed: `wing_wall`, `farfield`
- short `INC_NAVIER_STOKES` no-slip smoke ran with finite positive drag

But it is **not** a final CFD mesh:

- tetra-only, no wall-resolved prism boundary layer
- isolated `min_gamma = 5.47e-6` sliver warning remains
- no grid-independence evidence
- no converged 2000-iteration physical case

The real `shell_v4` boundary-layer route is still not ready for production CFD because the real VSP wing fails before volume meshing in the Gmsh PLC / boundary-recovery family. The surrogate BL route proves the machinery can make a million-cell half-wing prism mesh, but it does not certify the real high-lift wing.

## Solver policy

Recommended sequence:

| stage | solver | turbulence / transition | wall | purpose |
|---|---|---|---|---|
| mesh smoke | `INC_EULER` | none | `MARKER_EULER` | marker and volume-mesh readability only |
| no-slip debug | `INC_NAVIER_STOKES` | none | `MARKER_HEATFLUX=(wing_wall,0.0)` | verify viscous wall setup and force sign |
| first physical grid study | `INC_RANS` | `SA` | wall-resolved no-slip, `y+ ~ 1` | robust baseline for CL/CD/Cm stability |
| low-Re physics check | `INC_RANS` | `SST + LM` | wall-resolved no-slip, `y+ ~ 1` | transition sensitivity and drag sanity |

For external HPA wing RANS runs, use lower external-flow turbulence settings than the current SU2 hardcoded defaults:

```text
FREESTREAM_TURBULENCEINTENSITY = 0.01
FREESTREAM_TURB2LAMVISCRATIO   = 3.0
```

These are not magic constants. They are a conservative first setting for clean external aerodynamics; tunnel/flight turbulence evidence should override them when available.

## Boundary-layer policy

Use wall-resolved boundary-layer prisms for drag work:

- target first-cell `y+`: `0.5` to `1.5`
- practical first-layer height: about `5e-5 m`
- initial layer count: `24`
- growth ratio: about `1.24`
- total BL thickness: about `0.036 m`
- BL collapse rate target: `<= 0.02`

Do not let Gmsh infer terminal BL topology at the real wing tip. The current failures and Gmsh documentation point to a simple extrusion limitation. The route should own:

- chord/span indexing,
- near-wall prism stack,
- tip/TE termination,
- transition sleeve or BL-to-core handoff,
- root symmetry face,
- wake/TE spacing.

## Mesh-quality policy

Hard blockers:

- any non-positive volume element
- any non-positive SICN or SIGE element
- any ill-shaped tet count above zero
- missing `wing_wall`, `farfield`, or `symmetry` marker when required
- wrong reference area convention for half-wing vs full-wing

Production targets:

- `gamma p01 >= 0.02`
- `minSICN p01 >= 0.02`
- `minSIGE p01 >= 0.30`
- no sliver cluster near leading edge, trailing edge, tip, or root
- BL first-cell `y+` within `0.5-1.5` on most of the wing
- BL layers achieved equals requested layers, except explicitly designed termination zones

The current VSP-native 1M tet mesh passes hard blockers and `gamma p01`, but the isolated `min_gamma` warning means it is still a smoke/stability mesh, not final CFD quality.

## Grid-study policy

For a 12 GB Mac-safe half-wing target:

| level | target cells | role |
|---|---:|---|
| coarse | `0.9M` | first physics run |
| medium | `1.8M` | main comparison case |
| fine | `3.0M` | RAM-capped check |

Run up to `2000` iterations when doing physical evidence, not when merely testing mesh readability. Select the cheapest adjacent mesh pair whose last-window-stable `CL/CD/Cm` changes are within:

- `CL`: `3%`
- `CD`: `5%`
- `CMy`: `5%`

Then compare against VSPAERO only as a final sanity check. If SU2 is converged and marker/reference-correct but still far from VSPAERO, investigate physics model and transition before blaming geometry.

## Sources checked

- SU2 Physical Definition: `INC_NAVIER_STOKES`, `INC_RANS`, incompressible initialization, SA/SST/LM transition setup. <https://su2code.github.io/docs_v7/Physical-Definition/>
- SU2 Markers and Boundary Conditions: `MARKER_EULER`, `MARKER_HEATFLUX`, `MARKER_FAR`, `MARKER_SYM`, wall functions. <https://su2code.github.io/docs_v7/Markers-and-BC/>
- SU2 Convective Schemes: incompressible `FDS`, central schemes, and low-speed scheme notes. <https://su2code.github.io/docs_v7/Convective-Schemes/>
- SU2 Transitional Flat Plate tutorial: SST + Langtry-Menter transition and why fully turbulent flow misses transition effects. <https://su2code.github.io/tutorials/Transitional_Flat_Plate_T3A/>
- NASA Turbulence Modeling Resource NACA0012 numerical grids: wall spacing, farfield, and trailing-edge spacing sensitivity. <https://turbmodels.larc.nasa.gov/naca0012numerics_grids.html>
- Gmsh reference manual: topological boundary layers are simple extrusion with no special fan/re-entrant-corner treatment. <https://gmsh.info/doc/texinfo/>
