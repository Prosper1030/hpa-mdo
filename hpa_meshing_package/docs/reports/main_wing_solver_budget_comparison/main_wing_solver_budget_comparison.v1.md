# Main Wing Solver Budget Comparison v1

This report compares existing solver-smoke artifacts only; it does not execute SU2.

- report_status: `solver_budget_nonconverged`
- hpa_standard_velocity_mps: `6.5`
- hpa_standard_flow_status: `hpa_standard_6p5_observed`

## Current Route Row

- `reference_policy`: `openvsp_geometry_derived`
- `runtime_max_iterations`: `80`
- `report_path`: `/Volumes/Samsung SSD/hpa-mdo/hpa_meshing_package/docs/reports/main_wing_openvsp_reference_solver_smoke_probe_iter80/main_wing_real_solver_smoke_probe.v1.json`
- `convergence_gate_status`: `warn`
- `convergence_comparability_level`: `run_only`
- `residual_median_log_drop`: `0.357993`
- `coefficient_stability_status`: `pass`
- `final_coefficients`: `{"cl": 0.263161913, "cd": 0.02496911575, "cm": -0.2096803732, "cm_axis": "CMy"}`
- `main_wing_lift_acceptance_status`: `fail`
- `minimum_acceptable_cl`: `1`
- `advisory_flags`: `["convergence_gate_not_passed", "residual_drop_below_threshold", "reference_geometry_warn", "main_wing_cl_below_expected_lift", "mesh_quality_cv_sub_volume_ratio_high", "mesh_quality_cv_face_area_aspect_ratio_high", "overall_gate_warning:iterative_gate=warn", "overall_gate_warning:reference_gate=warn"]`

## Rows

| reference_policy | role | max_iter | final_iter | gate | residual_drop | CL | CD | CM | flags |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `declared_blackcat_full_span` | `baseline_smoke` | `12` | `11` | `fail` | `0.162743` | `0.264201` | `0.0188679` | `-0.138813` | convergence_gate_not_passed, residual_drop_below_threshold, coefficient_tail_not_stable, reference_geometry_warn, main_wing_cl_below_expected_lift, overall_gate_warning:iterative_gate=fail, overall_gate_warning:reference_gate=warn |
| `declared_blackcat_full_span` | `budget_probe` | `40` | `39` | `warn` | `0.216845` | `0.271915` | `0.02597` | `-0.146786` | convergence_gate_not_passed, residual_drop_below_threshold, reference_geometry_warn, main_wing_cl_below_expected_lift, overall_gate_warning:iterative_gate=warn, overall_gate_warning:reference_gate=warn |
| `openvsp_geometry_derived` | `baseline_smoke` | `12` | `11` | `fail` | `0.162743` | `0.260257` | `0.0185863` | `-0.203257` | convergence_gate_not_passed, residual_drop_below_threshold, coefficient_tail_not_stable, reference_geometry_warn, main_wing_cl_below_expected_lift, overall_gate_warning:iterative_gate=fail, overall_gate_warning:reference_gate=warn |
| `openvsp_geometry_derived` | `budget_probe` | `40` | `39` | `warn` | `0.216845` | `0.267856` | `0.0255824` | `-0.213081` | convergence_gate_not_passed, residual_drop_below_threshold, reference_geometry_warn, main_wing_cl_below_expected_lift, overall_gate_warning:iterative_gate=warn, overall_gate_warning:reference_gate=warn |
| `openvsp_geometry_derived` | `budget_probe` | `80` | `79` | `warn` | `0.357993` | `0.263162` | `0.0249691` | `-0.20968` | convergence_gate_not_passed, residual_drop_below_threshold, reference_geometry_warn, main_wing_cl_below_expected_lift, mesh_quality_cv_sub_volume_ratio_high, mesh_quality_cv_face_area_aspect_ratio_high, overall_gate_warning:iterative_gate=warn, overall_gate_warning:reference_gate=warn |

## Engineering Assessment

- This comparison is report-only and does not execute SU2.
- Solver execution is treated separately from convergence; only a pass gate can be called converged.
- The highest available current-route budget remains non-converged or warn-only.
- Current-route coefficient tails are stable, but residual and reference gates still limit comparability.
- Current-route CL is below 1 at HPA 6.5 m/s, so it cannot be accepted as converged main-wing evidence.
- SU2 mesh-quality diagnostics now point at local mesh quality as a better next suspect than simply adding iterations.
- Reference geometry remains warn-level, so moments and force comparability are not final engineering evidence.

## Next Actions

- `resolve_main_wing_cl_below_expected_lift_before_convergence_claims`
- `inspect_main_wing_mesh_quality_before_more_iterations`
- `compare_solver_numerics_and_mesh_local_sizing_before_larger_budget`
- `resolve_main_wing_reference_area_and_moment_origin_policy`

## Limitations

- This report reads existing solver-smoke and convergence-gate artifacts only.
- A stable coefficient tail is not a convergence claim when residual or reference gates warn.
- Mesh-quality advisory flags are triage signals, not replacement convergence gates.
- The current upstream mesh remains a coarse bounded non-BL probe.
