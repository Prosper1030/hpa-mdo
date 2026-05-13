# WO-006R4 y+ And Boundary-Layer Basis

## Authority Flow Condition

- Velocity: `6.5 m/s`
- Density: `1.225 kg/m^3`
- Dynamic viscosity: `1.7894e-05 Pa*s`
- Kinematic viscosity: `1.46073469e-05 m^2/s`

## Current GO Chord / Re Basis

- Root chord: `1.256773096 m`
- Mean aerodynamic chord / Cref: `1.003721543 m`
- Tip chord: `0.645004090 m`
- Re at Cref: `446637.576`

## BL Policy

- First layer: `5e-05 m`
- Growth ratio: `1.24`
- Layers: `24`
- Total geometric BL thickness: `0.036173050 m`
- Estimated y+ for first layer: `1.042`
- Estimate model: `turbulent_schlichting`

This is a first-layer sizing estimate only. It is not a postprocessed SU2 surface y+ field because no conformal BL SU2 handoff exists in R4.

Official-source read: SU2 wall-resolved viscous/RANS credibility requires no-slip wall BCs, a near-wall mesh consistent with the wall model choice, and solved wall-shear evidence. Gmsh topological BL extrusion remains a topology gate before solver physics can be interpreted.

Official sources used:

- Gmsh manual: https://gmsh.info/doc/texinfo/
- SU2 mesh format: https://su2code.github.io/docs_v7/Mesh-File/
- SU2 markers / boundary conditions: https://su2code.github.io/docs_v7/Markers-and-BC/
- SU2 theory / wall functions: https://su2code.github.io/docs_v7/Theory/
