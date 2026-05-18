# Section Failure Diagnosis

Prior report bundle: `/Volumes/Samsung SSD/hpa-mdo/output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0_swept_cgrid_structured_hexa_smoke`.

The failed section route was a single closed O-grid loop around the true airfoil.
For a sharp or nearly sharp trailing edge that forces radial cells to wrap around
the upper/lower TE cusp.  That is not a valid local topology for these sections:
the wake should leave the TE downstream, not turn through the cusp.

Observed old O-grid evidence:
- dae31 root: severe closed-loop seam failure with non-orthogonality near `180 deg`,
  open cells, wrong-oriented face pyramids, and extreme skewness.  The live copied
  OpenFOAM sets localize the closed-loop failure to TE-seam cells near perimeter
  indices `0/47`, lower-aft cusp cells near `38-40`, and high radial-layer outer
  transition cells.
- cst_tip: lower absolute skew than dae31, but still failed the closed-loop gate
  with non-orthogonality above the section target and high-aspect / skewed faces
  at the finite CST trailing-edge transition.

LE curvature was not the dominant blocker: the most severe old dae31 skew was at
the TE seam/wake-side transition, while cst_tip had lower skew but still failed
orientation and non-orthogonality.  The rescue route therefore uses an open-TE
wake C-grid with a downstream TE H-block: airfoil upper/lower walls remain
separate, the finite TE strip is represented as `te_wall`, wake-block faces are
internal fluid faces, and no cell wraps around the TE cusp.
