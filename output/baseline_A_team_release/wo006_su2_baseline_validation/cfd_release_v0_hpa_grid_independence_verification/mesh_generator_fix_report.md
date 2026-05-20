# Mesh Generator Fix Report

Verdict: `generator_fix_not_yet_implemented`

This report intentionally does not claim the swept C-grid generator has been
fixed. It records the exact generator work that must happen before another
Coarse/Medium/Fine OpenFOAM grid study can be considered physically valid.

## Current Blocker Evidence

- grid-gate status: `grid_independence_not_demonstrated`
- blocking items: `['coarse:solver_not_completed', 'medium:solver_not_completed', 'fine:checkMesh_not_solver_smoke_acceptable', 'fine:solver_not_completed']`
- rung cell counts: `{'coarse': 890112, 'medium': 1996800, 'fine': 3769600}`
- max CD change observed before failure: `50.73972140084425%`

## Required Generator Fixes

- Fix the high-resolution `n_perim` TE stencil open-cell regression before Fine.
- Preserve one topology family across Coarse/Medium/Fine; do not use 2.00M and 2.22M as the final family.
- Export explicit LE spacing, TE spacing, BL layer count, BL total thickness, and wall-normal growth metadata.
- Add wake refinement controls for near wake and downstream wake sampling planes.
- Add physical tip/tip-vortex refinement controls rather than relying on artificial side-patch diagnostics.
- Keep first-layer height and y+ checks tied to upper/lower real airfoil walls.
- Add Cp, Cf, wake-profile, and tip-vortex extraction hooks for every grid level.

## Stop Rule

If Fine still fails checkMesh, produces open cells, or cannot run to a stable
force window, grid independence remains not demonstrated and design power
must not be updated.
