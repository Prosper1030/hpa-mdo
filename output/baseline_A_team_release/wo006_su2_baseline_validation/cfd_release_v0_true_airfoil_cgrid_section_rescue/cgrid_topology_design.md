# Wake C-Grid Topology Design

- Inner path: true airfoil coordinates from TE_upper to LE to TE_lower.
- The path is open at the TE; no single-loop O-grid closure is used.
- Upper and lower TE nodes remain separate; no TE bluntness is introduced.
- Radial construction: wall-normal first layer, then straight rays to a C-shaped
  farfield boundary.
- Wake construction: a downstream H-block fills the open TE wake slot.  Its
  upper/lower interfaces are internal faces shared with the C-grid side faces,
  not wall or freestream patches.
- Patches: `airfoil_upper`, `airfoil_lower`, `te_wall`, `outlet`, `farfield`,
  `tip_left`, `tip_right`.
- Section side planes are written as OpenFOAM `empty` patches for the 2D
  extruded section gate.
- Section meshQualityDict records the deliberate section-only tolerance:
  `maxNonOrtho=85`, `minDeterminant=1e-8`, because aligned BL cells are allowed
  but skew/orientation/open-cell failures are not.
