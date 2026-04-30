# main_wing real solver smoke probe v1

This probe runs SU2_CFD from the real main-wing SU2 handoff and keeps solver execution separate from convergence.

- run_status: `solver_executed_but_not_converged`
- solver_execution_status: `solver_executed`
- convergence_gate_status: `fail`
- convergence_comparability_level: `not_comparable`
- return_code: `0`
- final_iteration: `11`
- observed_velocity_mps: `6.5`
- component_force_ownership_status: `owned`
- reference_geometry_status: `warn`
- history_path: `/Volumes/Samsung SSD/hpa-mdo/hpa_meshing_package/docs/reports/main_wing_real_su2_handoff_probe/artifacts/su2/alpha_0_real_main_wing_materialization_probe/history.csv`
- solver_log_path: `/Volumes/Samsung SSD/hpa-mdo/hpa_meshing_package/docs/reports/main_wing_real_su2_handoff_probe/artifacts/su2/alpha_0_real_main_wing_materialization_probe/solver.log`
- convergence_gate_path: `hpa_meshing_package/docs/reports/main_wing_real_solver_smoke_probe/artifacts/convergence_gate.v1.json`
- error: `None`

## Blocking Reasons

- `solver_executed_but_not_converged`
- `main_wing_real_reference_geometry_warn`

## HPA-MDO Guarantees

- `real_main_wing_su2_handoff_v1_consumed`
- `solver_not_claimed_converged_without_gate_pass`
- `production_default_unchanged`
- `hpa_standard_flow_conditions_6p5_mps`
- `su2_solver_executed`
- `history_file_written`
- `convergence_gate_v1_emitted`
- `heavy_solver_outputs_pruned`

## Limitations

- Solver execution is not the same as convergence; only a pass convergence gate can be called converged.
- Reference geometry warn/fail remains a comparability blocker even when the solver runs.
- The upstream mesh is a coarse bounded probe, not production default sizing.
- Production defaults were not changed.
