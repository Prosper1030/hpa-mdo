# main_wing OpenVSP reference solver smoke artifact index

This directory records a bounded solver smoke launched from the probe-local
OpenVSP/VSPAERO reference SU2 handoff. It is execution evidence only, not a
convergence or CFD-ready claim.

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
- `convergence_gate_status = fail`
- `convergence_comparability_level = not_comparable`
- `final_iteration = 11`
- `CL = 0.2602573982`
- `CD = 0.01858625024`
- `CMy = -0.2032569615`

The run preserves `V=6.5 m/s` and does not change production defaults. The
reference state remains `warn` because the OpenVSP/VSPAERO moment origin is a
zero CG setting rather than an owned aerodynamic moment policy.
