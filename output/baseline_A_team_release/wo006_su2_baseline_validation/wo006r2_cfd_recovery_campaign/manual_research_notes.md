# WO-006R2 Manual Research Notes

## Official / Primary Sources Checked

- SU2 Physical Definition: https://su2code.github.io/docs_v7/Physical-Definition/
  - Supports incompressible initialization with `INC_DENSITY_INIT`,
    `INC_VELOCITY_INIT`, `INC_TEMPERATURE_INIT`, and farfield state ownership.
- SU2 Theory: https://su2code.github.io/docs_v7/Theory/
  - Separates `INC_EULER`, viscous solvers, RANS, and wall-function expectations.
  - Wall-resolved runs without wall functions need fine near-wall mesh; docs state
    `y+ < 5` when no wall model is active.
- SU2 Markers and Boundary Conditions:
  https://su2code.github.io/docs_v7/Markers-and-BC/
  - Solid viscous walls should be no-slip heatflux walls, not `MARKER_EULER`.
- SU2 Convective Schemes: https://su2code.github.io/docs_v7/Convective-Schemes/
  - Incompressible solver supports central and FDS low-speed schemes.
- SU2 Custom Output: https://su2code.github.io/docs_v7/Custom-Output/
  - `MARKER_PLOTTING` controls surface outputs; coefficient histories can expose
    force and moment sanity.
- SU2 Incompressible Turbulent NACA0012:
  https://su2code.github.io/tutorials/Inc_Turbulent_NACA0012/
  - Official external incompressible RANS + SA example with farfield and no-slip
    wall, TMR mesh, and `y+ < 1` near-wall spacing.
- SU2 Turbulent Flat Plate:
  https://su2code.github.io/tutorials/Turbulent_Flat_Plate/
  - SA is a common robust first model for external aerodynamic RANS.
- SU2 Transitional Flat Plate:
  https://su2code.github.io/tutorials/Transitional_Flat_Plate_T3A/
  - Transition modeling depends on turbulence assumptions and should be treated as
    a second-stage physics sensitivity here.
- Gmsh manual: https://gmsh.info/doc/texinfo/
  - Topological BL extrusion is available with the built-in kernel, but it is a
    simple extrusion with no fan or special reentrant-corner treatment; the
    `BoundaryLayer` field is 2D only.
- OpenVSP CFD Mesh API:
  https://openvsp.org/api_docs/3.42.2/group___c_f_d_mesh.html
  - OpenVSP exposes CFD mesh/source/wake controls, but this campaign does not
    treat OpenVSP as proof of solver-ready 3D prism BL quality.

## Engineering Interpretation

Euler/no-BL cases are instrumentation only. WO-006R2 needs no-slip viscous or
RANS ownership, explicit force/reference conventions, BL or a justified near-wall
alternative, and coefficient sanity before any AVL/VSPAERO/proxy comparison.
