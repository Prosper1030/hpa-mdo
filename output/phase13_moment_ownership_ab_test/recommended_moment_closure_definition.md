# Recommended Moment Closure Definition

## Interim Rule

Do not use the current all-axis `moment_closure_passed` as a production hard rejection. It should remain visible as a diagnostic until the torque ownership path is validated against an external reference or a hand-checkable free-body case.

For Phase 13 structural prefiltering, use:

`production_hard_feasible_interim = inverse_feasible AND clearance_feasible AND wire_feasible AND geometry_validity AND equilibrium_passed AND compatibility_passed AND force_closure_passed AND conditioning_passed`

Keep these reported beside it:

- `moment_closure_mx_residual_nm`
- `moment_closure_my_residual_nm`
- `moment_closure_mz_residual_nm`
- `torque_ownership_mode`
- `moment_closure_interpretability`

## Permanent Rule Candidate

Use a decomposed check, not a single all-axis norm:

1. Force closure: strict numerical tolerance.
2. Pitch/torsion closure My: strict only after aerodynamic Cm is mapped to either an explicit spar couple or a validated torsional generalized DOF.
3. Bending closure Mx: strict for external force/reaction resultants.
4. Yaw/offset-link Mz: report separately until rigid-link generalized moments and explicit wire support are proven to form a physical free-body resultant.

Next smallest implementation test: run the production model with `main_beam_my_about_main_spar` and `front_rear_vertical_couple` on a simple two-node hand-check model where the expected torque reaction is known exactly.
