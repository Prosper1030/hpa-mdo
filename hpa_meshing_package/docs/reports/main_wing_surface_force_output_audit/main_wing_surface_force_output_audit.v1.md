# Main Wing Surface Force Output Audit v1

This report reads existing solver artifacts only; it does not execute SU2.

- audit_status: `warn`
- production_default_changed: `False`
- selected_solver_report_path: `/Volumes/Samsung SSD/hpa-mdo/hpa_meshing_package/docs/reports/main_wing_openvsp_reference_solver_smoke_probe_iter80/main_wing_real_solver_smoke_probe.v1.json`
- solver_log_path: `/Volumes/Samsung SSD/hpa-mdo/hpa_meshing_package/docs/reports/main_wing_openvsp_reference_solver_smoke_probe_iter80/artifacts/raw_solver/solver.log`
- panel_reference_report_path: `/Volumes/Samsung SSD/hpa-mdo/hpa_meshing_package/docs/reports/main_wing_vspaero_panel_reference_probe/main_wing_vspaero_panel_reference_probe.v1.json`

## Solver Execution Observed

- `solver_execution_status`: `solver_executed`
- `run_status`: `solver_executed_but_not_converged`
- `convergence_gate_status`: `fail`
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
| `surface_csv_retained` | `pass` |
| `forces_breakdown_retained` | `pass` |
| `panel_force_comparison_ready` | `pass` |
| `forces_breakdown_marker_owned` | `pass` |
| `forces_breakdown_matches_history_cl` | `pass` |

## Force Breakdown Observed

- `status`: `available`
- `path`: `/Volumes/Samsung SSD/hpa-mdo/hpa_meshing_package/docs/reports/main_wing_openvsp_reference_solver_smoke_probe_iter80/artifacts/raw_solver/forces_breakdown.dat`
- `surface_names`: `["main_wing"]`
- `total_coefficients`: `{"cl": 0.263162, "cd": 0.024969, "csf": -0.001195, "cl_over_cd": 10.539497, "cmx": 0.108619, "cmy": -0.20968, "cmz": -0.024814, "cfx": 0.024969, "cfy": -0.001195, "cfz": 0.263162}`
- `surface_coefficients`: `{"main_wing": {"cl": 0.263162, "cd": 0.024969, "csf": -0.001195, "cl_over_cd": 10.539497, "cmx": 0.108619, "cmy": -0.20968, "cmz": -0.024814, "cfx": 0.024969, "cfy": -0.001195, "cfz": 0.263162}}`
- `history_cl_delta_abs`: `8.699999998196262e-08`
- `panel_to_force_breakdown_cl_ratio`: `4.892976554149155`

## Panel Reference Observed

- `status`: `available`
- `panel_reference_cl`: `1.287645495943`
- `selected_su2_smoke_cl`: `0.263161913`
- `panel_to_su2_cl_ratio`: `4.892978171742504`
- `velocity_mps`: `6.5`
- `alpha_deg`: `0.0`

## Blocking Reasons


## Engineering Flags

- `solver_executed_but_not_converged`
- `main_wing_lift_acceptance_failed_cl_below_one`
- `hpa_standard_flow_conditions_6p5_mps_observed`
- `forces_breakdown_cl_below_panel_reference`

## Next Actions

- `surface_force_outputs_available_for_panel_delta_debug`
- `debug_panel_su2_lift_gap_from_retained_force_breakdown`

## Limitations

- This audit reads existing solver artifacts only and does not execute SU2.
- Solver execution is not convergence; convergence remains governed by the convergence gate.
- Surface-force output retention is required before using panel/SU2 force deltas to debug the CL gap.
