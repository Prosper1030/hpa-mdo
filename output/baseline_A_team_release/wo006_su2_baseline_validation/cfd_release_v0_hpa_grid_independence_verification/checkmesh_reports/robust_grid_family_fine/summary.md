# Robust Grid Family Fine CheckMesh Summary

Verdict: `hard_topology_passed_but_strict_meshquality_failed`

- artifact: `robust_grid_family_checkmesh/openfoam_cases/fine/fullwing_artificial_tip_symmetry/`
- full-wing cells: `3708800`
- open cells: `0`
- negative volumes: `0`
- wrong-oriented face pyramids: `0`
- faces with face pyramid volume `< 1e-18`: `0`
- faces with face twist `<0.02`: `10`
- faces on cells with determinant `<0.001`: `2266249`
- max cell openness: `4.98214e-14`
- min volume: `7.77078e-10 m^3`
- max non-orthogonality: `87.516 deg`
- max skewness: `3.46221`
- failed mesh checks: `1`

The old lower-TE wrong-oriented face-pyramid blocker is still fixed. Solver
phase was blocked by the family-level strict `checkMesh` gate.
