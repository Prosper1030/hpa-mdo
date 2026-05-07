# Recommended Fix

Do not use the z-state mass results for design rejection until the selector is patched and re-swept.

Recommended code changes, in order:

1. Add an explicit candidate-archive dump option to `scripts/direct_dual_beam_inverse_design.py` so every unique candidate, including post-selection probes and local-refine points, is persisted with hard margins and reject reasons.
2. Move active-wall/lighten probes out of the mutating selection archive, or recompute `selected` after probes if probes are allowed to affect selection. The current behavior can report a stale selected candidate.
3. Pass `--target-mass-kg` from `structure_budgeted_z_state_search.py` when the run is meant to be budget-aware, and keep the post-filter as an independent contract check.
4. Wire production numerical-consistency and wire-support feasibility into the selection contract, or explicitly split `inverse_feasible` from `production_hard_feasible` in all reported z-state tables.
5. Replace endpoint-only MVP grids near cliff regions with local refine or a bounded clearance-recovery sweep; keep `refresh_steps=0` only for comparability, not as final selection policy.
6. Fix or clearly quarantine any exported target-shape CSV that does not match the selected in-memory target shape, because downstream structural tools could otherwise read the wrong z state.

Immediate engineering experiment before external FEM:

- Re-run the z=1.95-2.10 m region with archive dumping, local refine enabled, target mass set, and a non-mutating probe archive. Then compare the continuous feasible frontier before sending any one recipe to FEM.
