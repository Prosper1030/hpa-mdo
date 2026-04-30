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
- `artifacts/raw_solver/surface.csv`: raw SU2 surface output retained from the
  `.tmp` case directory.

Observed result:

- `solver_execution_status = solver_executed`
- `run_status = solver_executed_but_not_converged`
- `convergence_gate_status = fail`
- `convergence_comparability_level = not_comparable`
- `final_iteration = 79`
- `CL = 0.263161913`
- `CD = 0.02496911575`
- `CMy = -0.2096803732`

The run preserves `V=6.5 m/s` and does not change production defaults. Relative
to the 40-iteration OpenVSP-reference smoke, coefficient stability improves and
`surface.csv` is retained, but the residual gate remains below threshold and the
main-wing lift gate fails because `CL <= 1.0`. The run is therefore still
blocked by `solver_executed_but_not_converged`,
`main_wing_cl_below_expected_lift`, and `main_wing_real_reference_geometry_warn`.
The solver log advertises `forces_breakdown.dat`, but that file is not
materialized in the retained raw solver artifacts.

Mesh-quality observations from `artifacts/raw_solver/solver.log`:

- minimum orthogonality angle: `31.473 deg`
- maximum CV face area aspect ratio: `377.909`
- maximum CV sub-volume ratio: `13256.1`
- maximum surface curvature reported by SU2 preprocessing: `1768.33`

These numbers do not by themselves prove the convergence blocker root cause,
but they are strong enough to make mesh-quality and local sizing/numerics checks
more useful than simply increasing the iteration count again.
