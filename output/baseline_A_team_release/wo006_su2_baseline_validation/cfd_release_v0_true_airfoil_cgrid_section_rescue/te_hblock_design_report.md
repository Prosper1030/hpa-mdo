# TE H-Block / Collar Design Report

The rescue implementation uses a finite-TE H-block downstream of the true
airfoil TE gap.

- The dae31 and cst_tip TE endpoints are preserved from the true Baseline A
  coordinate authority.
- No NACA0012 or smoothed replacement airfoil is used.
- No TE bluntness, bevel, or coordinate perturbation is introduced.
- The wake H-block shares its upper/lower side faces with the C-grid side faces,
  making those faces internal fluid faces.
- The physical wall patches are `airfoil_upper`, `airfoil_lower`, and `te_wall`.
- The downstream boundary is `outlet`; the C-shaped outer boundary is
  `farfield`.

Current blocker: the finite-TE H-block still creates bad cells at the TE/wake
interface for dae31 and the morph section.  This is now a local TE H-block
quality problem, not a span-count, solver, AoA, or placeholder-airfoil problem.
