# main_wing real solver smoke probe iter40 artifacts

This directory records a bounded 40-iteration follow-up smoke from the real
main-wing SU2 handoff route. It is not the canonical default smoke report and
does not change production defaults.

Committed small artifacts:

- `main_wing_real_solver_smoke_probe.v1.json`: machine-readable smoke result.
- `main_wing_real_solver_smoke_probe.v1.md`: human-readable smoke result.
- `artifacts/convergence_gate.v1.json`: convergence gate emitted from the
  40-row history.
- `artifacts/raw_solver/history.csv`: copied raw solver history snapshot.
- `artifacts/raw_solver/solver.log`: copied raw solver log snapshot.

Large artifacts intentionally not committed:

- `.tmp/runs/main_wing_real_su2_handoff_probe_iter40/.../mesh.su2`
- `.tmp/runs/main_wing_real_su2_handoff_probe_iter40/.../su2_handoff.json`
- `.tmp/runs/main_wing_real_su2_handoff_probe_iter40/.../su2_runtime.cfg`

Engineering reading: the 40-iteration run improves the route from the
12-iteration `fail/not_comparable` smoke to `warn/run_only`, but it remains
`solver_executed_but_not_converged` because residual drop is below threshold and
the main-wing reference geometry gate is still `warn`.
