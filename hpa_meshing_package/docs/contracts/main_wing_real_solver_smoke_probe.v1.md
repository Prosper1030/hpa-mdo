# main_wing_real_solver_smoke_probe.v1

`main_wing_real_solver_smoke_probe.v1` records a bounded SU2 solver smoke run
from the real main-wing SU2 handoff.

It is intentionally a smoke probe, not a convergence claim:

- it consumes `main_wing_real_su2_handoff_probe.v1`
- it runs `SU2_CFD` in the materialized real main-wing case directory
- it writes or preserves `solver.log`
- it writes or preserves `history.csv`
- it emits `convergence_gate.v1`
- it prunes heavyweight field outputs from the committed smoke artifact set
- it uses the HPA standard flow condition `V=6.5 m/s`
- it applies a main-wing lift acceptance gate: at `V=6.5 m/s`, `CL` must be
  greater than `1.0` before the run can be accepted as converged
- it does not change production defaults

## Required Top-Level Fields

- `schema_version`: fixed string `main_wing_real_solver_smoke_probe.v1`
- `component`: fixed string `main_wing`
- `source_su2_probe_schema`: expected `main_wing_real_su2_handoff_probe.v1`
- `execution_mode`: fixed string `real_su2_handoff_solver_smoke`
- `production_default_changed`: must be `false`
- `materialized_handoff_consumed`
- `source_su2_probe_path`
- `source_materialization_status`
- source mesh, case, handoff, runtime config, solver log, history, and convergence gate paths
- `pruned_output_paths`
- `solver_command`
- `timeout_seconds`
- `solver_execution_status`
- `convergence_gate_status`
- `run_status`
- `return_code`
- `final_iteration`
- `final_coefficients`
- `main_wing_lift_acceptance_status`
- `minimum_acceptable_cl`
- `convergence_comparability_level`
- `component_force_ownership_status`
- `reference_geometry_status`
- `observed_velocity_mps`
- `runtime_max_iterations`
- `volume_element_count`
- guarantees, blocking reasons, and limitations

## Pass Meaning

`solver_executed` means `SU2_CFD` was launched and returned from the real
main-wing SU2 handoff. It is execution evidence only.

`solver_executed_but_not_converged` means the solver ran and wrote history, but
`convergence_gate.v1` did not pass. This must not be reported as converged CFD
or as a comparable aerodynamic result.

`runtime_max_iterations` records the SU2 iteration budget used by the consumed
handoff. Increasing it is allowed only as a probe-local campaign choice and is
not a production default change.

At the HPA standard flow condition (`V=6.5 m/s`), a numerically stable main-wing
run with `CL <= 1.0` is still rejected for convergence acceptance. The report
must record `main_wing_lift_acceptance_status=fail` and include
`main_wing_cl_below_expected_lift` in the blocker set.

## Promotion Rule

This probe can move the route past "solver never ran" only. It can promote to
converged or comparable CFD only when:

1. `solver_execution_status = solver_executed`
2. `convergence_gate_status = pass`
3. `convergence_comparability_level` is promoted above `not_comparable`
4. reference geometry status passes
5. `main_wing_lift_acceptance_status = pass` (`CL > 1.0` at `V=6.5 m/s`)
6. the mesh sizing / BL policy is promoted separately from smoke sizing
