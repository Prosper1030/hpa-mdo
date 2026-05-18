# Kutta Wake C-Grid Design

- Inner path: true upper airfoil surface from upper TE to LE, then true lower
  surface to lower TE.
- The TE remains open; no single-pole O-grid closure wraps around the cusp.
- A downstream wake block fills the upper/lower TE slot as fluid cells.
- `airfoil_upper` and `airfoil_lower` remain separate wall patches.
- `te_wall` is present only as the finite TE strip at the airfoil TE gap.
- `outlet` is the downstream wake boundary; `farfield` is the outer C boundary.
- The section case is a thin all-hexa 3D extrusion with `tip_left/tip_right`
  written as OpenFOAM `empty` patches.
- Current parameters: `n_radial=64`, wake length `8.0c`,
  first layer `5e-05 m`, near-wall growth `1.12`.
