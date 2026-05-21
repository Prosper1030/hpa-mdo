# Mesh Generator Fix Report

Verdict: `same_family_generator_checkmesh_gate_passed_solver_validation_in_progress`

The high-resolution TE/open-cell failure and the later lower-TE wrong-oriented
face-pyramid blocker are no longer the active blockers. The current swept
C-grid generator fixes the lower-TE body/wake sliver at source by a local
radial wall-layer rebalance; no polyMesh surgery is used.

This is now a repeatable grid-family generator rather than a one-off Fine mesh
patch. The current workflow generates Coarse/Medium/Fine with the same topology,
same local refinement rules, and a strict family checkMesh gate. The old
pseudo-time 1 cold-start force spike is handled by `potentialFoam` initialization
and a startup-grace runaway guard.

## Latest Fine Generator Smoke

- smoke case: `robust_grid_family_checkmesh`
- full-wing cells: `6090240`
- half-wing seed cells: `3045120`
- n_perim / n_radial / span cells: `240` / `80` / `156`
- wake_cross_cells: `4`
- TE normal blend points: `1`
- first layer height: `7e-05 m`
- open cells: `0`
- negative volume cells: `0`
- max aspect ratio: `529.781`
- min volume: available in checkMesh log
- max non-orthogonality: `82.9339 deg`
- max skew: `3.46267`
- wrong-oriented face pyramids: `0`
- failed checks: `0`
- strict checkMesh clean: `True`
- solver status: `deferred until full C/M/F solver campaign is run to stable force windows`
- remaining verification work: `Medium/Fine solver histories plus Cp/Cf/wake/tip-vortex comparison`

Engineering read: do not send future agents back to the old open-cell or
100 wrong-oriented-face diagnosis as if it were still current. The active
task is now the solver-complete same-family Coarse/Medium/Fine verification
campaign with stable force windows and field comparisons.

## Previous Grid Gate Evidence

- grid-gate status: `mesh_family_ready_for_solver`
- blocking items: `[]` for mesh/checkMesh gate
- rung cell counts: `{'coarse': 1335552, 'medium': 3136000, 'fine': 6090240}`
- max CD change observed before failure: `None%`

## Required Generator Fixes

- Preserve the lower-TE generator-level rebalance and keep wrong-oriented face pyramids at zero across Coarse/Medium/Fine.
- Preserve one topology family across Coarse/Medium/Fine; do not use 2.00M and 2.22M as the final family.
- Preserve explicit LE spacing, TE spacing, BL layer count, BL total thickness, and wall-normal growth metadata.
- Preserve wake refinement controls for near wake and downstream wake sampling planes.
- Preserve physical tip/tip-vortex refinement controls rather than relying on artificial side-patch diagnostics.
- Keep first-layer height and y+ checks tied to upper/lower real airfoil walls; artificial tip-cap diagnostics are excluded from physical drag and y+ acceptance.
- Add Cp, Cf, wake-profile, and tip-vortex extraction hooks for every grid level.

## Stop Rule

If any rung is not strict `checkMesh -meshQuality` clean, produces open cells,
negative volumes, wrong-oriented face pyramids, or OpenFOAM high-aspect failures,
the solver phase must not start. If any solver run cannot reach a stable force
window, grid independence remains not demonstrated and design power must not be
updated.
