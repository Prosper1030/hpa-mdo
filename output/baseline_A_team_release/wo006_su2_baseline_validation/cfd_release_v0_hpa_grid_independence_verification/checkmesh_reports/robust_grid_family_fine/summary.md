# Robust Grid Family Fine CheckMesh Summary

Verdict: `strict_checkmesh_passed`

- artifact: `robust_grid_family_checkmesh/openfoam_cases/fine/fullwing_artificial_tip_symmetry/`
- full-wing cells: `6090240`
- open cells: `0`
- negative volumes: `0`
- wrong-oriented face pyramids: `0`
- max aspect ratio: `529.781`
- max non-orthogonality: `82.9339 deg`
- max skewness: `3.46267`
- failed mesh checks: `0`

The old lower-TE wrong-oriented face-pyramid failure remains fixed. Solver
phase is allowed by the family-level strict `checkMesh` gate.
