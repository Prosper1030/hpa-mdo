# main_wing OpenVSP reference solver smoke iter40 artifact index

This directory records a bounded 40-iteration solver smoke launched from the
probe-local OpenVSP/VSPAERO reference SU2 handoff. It is execution and trend
evidence only, not a convergence or CFD-ready claim.

- `main_wing_real_solver_smoke_probe.v1.json`: solver smoke report.
- `main_wing_real_solver_smoke_probe.v1.md`: markdown summary.
- `artifacts/convergence_gate.v1.json`: machine-readable gate verdict.
- `artifacts/raw_solver/history.csv`: raw SU2 history copied from the `.tmp`
  case directory.
- `artifacts/raw_solver/solver.log`: raw SU2 log copied from the `.tmp` case
  directory.

Observed result:

- `solver_execution_status = solver_executed`
- `run_status = solver_executed_but_not_converged`
- `convergence_gate_status = warn`
- `convergence_comparability_level = run_only`
- `final_iteration = 39`
- `CL = 0.267856209`
- `CD = 0.02558236807`
- `CMy = -0.2130813257`

The run preserves `V=6.5 m/s` and does not change production defaults. Relative
to the 12-iteration OpenVSP-reference smoke, the longer budget improves the
gate from `fail/not_comparable` to `warn/run_only`, but the run is still blocked
by `solver_executed_but_not_converged`. The reference state also remains `warn`
because the OpenVSP/VSPAERO moment origin is a zero CG setting rather than an
owned aerodynamic moment policy.
