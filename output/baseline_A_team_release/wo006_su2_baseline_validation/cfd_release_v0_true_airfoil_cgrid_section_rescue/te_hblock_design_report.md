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

Current best state: the TE H-block removes open cells, negative volumes, and
wrong-oriented face pyramids in the primary section runs.  The remaining blocker
is strict section quality: dae31 is smoke-only above the 75-degree debug target,
and `-allGeometry` flags high-aspect underdetermined cells from the requested
low first-layer height.  This is not a span-count, solver, AoA, or placeholder
airfoil problem.
