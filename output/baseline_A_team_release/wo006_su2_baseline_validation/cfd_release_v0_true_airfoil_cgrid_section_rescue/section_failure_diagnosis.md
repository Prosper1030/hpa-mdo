# Section Failure Diagnosis

Prior report bundle: `/Volumes/Samsung SSD/hpa-mdo/output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0_swept_cgrid_structured_hexa`.

The failed section route was a single closed O-grid loop around the true airfoil.
For a sharp or nearly sharp trailing edge that forces radial cells to wrap around
the upper/lower TE cusp.  That is not a valid local topology for these sections:
the wake should leave the TE downstream, not turn through the cusp.

Observed old O-grid evidence:
- dae31 root: `max_skew=19010.2`, `max_non_orth=179.918 deg`, open/oriented-face
  failures.  The copied OpenFOAM sets localized non-closed cells mostly to high
  radial layers near perimeter indices `7-9` and `186-188`, i.e. the two sides of
  the TE/wake seam after the closed-loop wrap.
- cst_tip: `max_skew=22.3157`, `max_non_orth=154.64 deg`, localized mostly around
  high radial layers and upper-side indices `30-37`, with the finite CST trailing
  edge still interacting with the closed O-grid transition.

LE curvature was not the dominant blocker: the most severe old dae31 skew was at
the TE seam/wake-side transition, while cst_tip had lower skew but still failed
orientation and non-orthogonality.  The rescue route therefore uses an open-TE
wake C-grid: airfoil upper/lower walls remain separate, the wake cut is a fluid
patch/outlet, and no cell wraps around the TE cusp.
