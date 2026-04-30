# main_wing real solver smoke probe v1

This probe runs SU2_CFD from the real main-wing SU2 handoff and keeps solver execution separate from convergence.

- run_status: `solver_executed_but_not_converged`
- solver_execution_status: `solver_executed`
- convergence_gate_status: `fail`
- convergence_comparability_level: `not_comparable`
- return_code: `0`
- final_iteration: `79`
- observed_velocity_mps: `6.5`
- minimum_acceptable_cl: `1.0`
- main_wing_lift_acceptance_status: `fail`
- component_force_ownership_status: `owned`
- reference_geometry_status: `warn`
- runtime_max_iterations: `80`
- retained_su2_handoff_path: `hpa_meshing_package/docs/reports/main_wing_openvsp_reference_solver_smoke_probe_iter80/artifacts/source_su2/su2_handoff.json`
- retained_runtime_cfg_path: `hpa_meshing_package/docs/reports/main_wing_openvsp_reference_solver_smoke_probe_iter80/artifacts/source_su2/su2_runtime.cfg`
- history_path: `/Volumes/Samsung SSD/hpa-mdo/hpa_meshing_package/.tmp/runs/main_wing_openvsp_reference_su2_handoff_probe_iter80/artifacts/su2/alpha_0_real_main_wing_openvsp_reference_probe/history.csv`
- solver_log_path: `/Volumes/Samsung SSD/hpa-mdo/hpa_meshing_package/.tmp/runs/main_wing_openvsp_reference_su2_handoff_probe_iter80/artifacts/su2/alpha_0_real_main_wing_openvsp_reference_probe/solver.log`
- convergence_gate_path: `hpa_meshing_package/docs/reports/main_wing_openvsp_reference_solver_smoke_probe_iter80/artifacts/convergence_gate.v1.json`
- error: `None`

## Blocking Reasons

- `solver_executed_but_not_converged`
- `main_wing_cl_below_expected_lift`
- `main_wing_real_reference_geometry_warn`

## Solver Log Mesh Quality

- max_surface_curvature: `1768.33`
- min_orthogonality_angle_deg: `31.473`
- max_cv_face_area_aspect_ratio: `377.909`
- max_cv_sub_volume_ratio: `13256.1`

## HPA-MDO Guarantees

- `real_main_wing_su2_handoff_v1_consumed`
- `solver_not_claimed_converged_without_gate_pass`
- `production_default_unchanged`
- `hpa_standard_flow_conditions_6p5_mps`
- `su2_solver_executed`
- `history_file_written`
- `convergence_gate_v1_emitted`
- `heavy_solver_outputs_pruned`
- `surface_force_outputs_retained`
- `source_su2_provenance_retained`

## Limitations

- Solver execution is not the same as convergence; only a pass convergence gate can be called converged.
- At HPA standard V=6.5 m/s, main-wing convergence acceptance additionally requires CL > 1.
- Reference geometry warn/fail remains a comparability blocker even when the solver runs.
- The upstream mesh is a coarse bounded probe, not production default sizing.
- Production defaults were not changed.
