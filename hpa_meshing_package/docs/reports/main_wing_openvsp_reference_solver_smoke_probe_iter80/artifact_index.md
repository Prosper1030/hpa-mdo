# main_wing OpenVSP reference solver smoke iter80 artifact index

This directory records a bounded 80-iteration solver smoke launched from the
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
- `final_iteration = 79`
- `CL = 0.263161913`
- `CD = 0.02496911575`
- `CMy = -0.2096803732`

The run preserves `V=6.5 m/s` and does not change production defaults. Relative
to the 40-iteration OpenVSP-reference smoke, coefficient stability improves, but
the residual gate still warns: median residual log drop is about `0.358` against
the `0.5` pass threshold. The run is therefore still blocked by
`solver_executed_but_not_converged`, with `main_wing_real_reference_geometry_warn`
also remaining active.
