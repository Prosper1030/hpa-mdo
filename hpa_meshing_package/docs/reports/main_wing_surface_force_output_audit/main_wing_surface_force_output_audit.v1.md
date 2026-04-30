# Main Wing Surface Force Output Audit v1

This report reads existing solver artifacts only; it does not execute SU2.

- audit_status: `blocked`
- production_default_changed: `False`
- selected_solver_report_path: `/Volumes/Samsung SSD/hpa-mdo/hpa_meshing_package/docs/reports/main_wing_openvsp_reference_solver_smoke_probe_iter80/main_wing_real_solver_smoke_probe.v1.json`
- solver_log_path: `/Volumes/Samsung SSD/hpa-mdo/hpa_meshing_package/docs/reports/main_wing_openvsp_reference_solver_smoke_probe_iter80/artifacts/raw_solver/solver.log`
- panel_reference_report_path: `/Volumes/Samsung SSD/hpa-mdo/hpa_meshing_package/docs/reports/main_wing_vspaero_panel_reference_probe/main_wing_vspaero_panel_reference_probe.v1.json`

## Solver Execution Observed

- `solver_execution_status`: `solver_executed`
- `run_status`: `solver_executed_but_not_converged`
- `convergence_gate_status`: `warn`
- `main_wing_lift_acceptance_status`: `fail`
- `observed_velocity_mps`: `6.5`
- `runtime_max_iterations`: `80`
- `final_iteration`: `79`
- `final_coefficients`: `{"cl": 0.263161913, "cd": 0.02496911575, "cm": -0.2096803732, "cm_axis": "CMy"}`

## Expected Outputs From Log

- `surface_csv`: `surface.csv`
- `forces_breakdown`: `forces_breakdown.dat`

## Checks

| check | status |
|---|---|
| `solver_report_available` | `pass` |
| `solver_executed` | `pass` |
| `surface_csv_retained` | `blocked` |
| `forces_breakdown_retained` | `blocked` |
| `panel_force_comparison_ready` | `blocked` |

## Panel Reference Observed

- `status`: `available`
- `panel_reference_cl`: `1.287645495943`
- `selected_su2_smoke_cl`: `0.263161913`
- `panel_to_su2_cl_ratio`: `4.892978171742504`
- `velocity_mps`: `6.5`
- `alpha_deg`: `0.0`

## Blocking Reasons

- `surface_force_output_pruned_or_missing`
- `forces_breakdown_output_missing`
- `panel_force_comparison_not_ready`

## Engineering Flags

- `solver_executed_but_not_converged`
- `main_wing_lift_acceptance_failed_cl_below_one`
- `hpa_standard_flow_conditions_6p5_mps_observed`

## Next Actions

- `preserve_surface_csv_in_solver_smoke_artifacts`
- `preserve_forces_breakdown_dat_in_solver_smoke_artifacts`
- `rerun_surface_force_output_audit_before_panel_delta_debug`

## Limitations

- This audit reads existing solver artifacts only and does not execute SU2.
- Solver execution is not convergence; convergence remains governed by the convergence gate.
- Surface-force output retention is required before using panel/SU2 force deltas to debug the CL gap.
