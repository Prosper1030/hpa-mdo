# Mesh Generator Fix Report

Verdict: `lower_te_blocker_removed_but_family_gate_not_passed`

The high-resolution TE/open-cell failure and the later lower-TE wrong-oriented
face-pyramid blocker are no longer the active blockers. The current swept
C-grid generator fixes the lower-TE body/wake sliver at source by a local
radial wall-layer rebalance; no polyMesh surgery is used.

This still is not a completed grid-family generator. The Fine mesh is not
strict-clean because inherited determinant/twist `meshQuality` warnings remain,
and its solver smoke tripped the force-runaway guard at pseudo-time 1.

## Latest Fine Generator Smoke

- smoke case: `fine_te_radial_chord_shift_run`
- full-wing cells: `3708800`
- half-wing seed cells: `1854400`
- n_perim / n_radial / span cells: `240` / `80` / `95`
- wake_cross_cells: `4`
- TE normal blend points: `1`
- first layer height: `5e-05 m`
- open cells: `0`
- negative volume cells: `0`
- max cell openness: `4.98214e-14`
- min volume: `7.77078e-10 m^3`
- max non-orthogonality: `87.516 deg`
- max skew: `3.46221`
- wrong-oriented face pyramids: `0`
- failed checks: `1`
- strict checkMesh clean: `False`
- solver status: `runaway_guard_triggered_at_pseudo_time_1`
- remaining blocker: `strict C/M/F family gate not passed; Fine has inherited determinant/twist warning and no stable force window`

Engineering read: do not send future agents back to the old open-cell or
100 wrong-oriented-face diagnosis as if it were still current. The active
task is a robust same-family Coarse/Medium/Fine generator with strict
family-level checkMesh gating before solver launch.

## Previous Grid Gate Evidence

- grid-gate status: `grid_independence_not_demonstrated`
- blocking items: `['coarse:strict_checkMesh_not_clean', 'coarse:solver_deferred_until_all_requested_rungs_are_strict_checkmesh_clean', 'coarse:solver_not_completed', 'medium:strict_checkMesh_not_clean', 'medium:solver_deferred_until_all_requested_rungs_are_strict_checkmesh_clean', 'medium:solver_not_completed', 'fine:strict_checkMesh_not_clean', 'fine:solver_deferred_until_all_requested_rungs_are_strict_checkmesh_clean', 'fine:solver_not_completed', 'coarse:family_solver_gate_blocked', 'medium:family_solver_gate_blocked', 'fine:family_solver_gate_blocked']`
- rung cell counts: `{'coarse': 866688, 'medium': 1996800, 'fine': 3708800}`
- max CD change observed before failure: `None%`

## Required Generator Fixes

- Preserve the lower-TE generator-level rebalance and keep wrong-oriented face pyramids at zero across Coarse/Medium/Fine.
- Preserve one topology family across Coarse/Medium/Fine; do not use 2.00M and 2.22M as the final family.
- Export explicit LE spacing, TE spacing, BL layer count, BL total thickness, and wall-normal growth metadata.
- Add wake refinement controls for near wake and downstream wake sampling planes.
- Add physical tip/tip-vortex refinement controls rather than relying on artificial side-patch diagnostics.
- Keep first-layer height and y+ checks tied to upper/lower real airfoil walls.
- Add Cp, Cf, wake-profile, and tip-vortex extraction hooks for every grid level.

## Stop Rule

If any rung is not strict `checkMesh -meshQuality` clean, produces open cells,
negative volumes, or wrong-oriented face pyramids, the solver phase must not
start. If any solver run cannot reach a stable force window, grid independence
remains not demonstrated and design power must not be updated.
