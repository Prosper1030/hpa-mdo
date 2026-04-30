# main_wing route readiness v1

- overall_status: `solver_executed_not_converged`
- hpa_standard_flow_status: `hpa_standard_6p5_observed`
- observed_velocity_mps: `6.5`

## Stages

| stage | status | evidence | artifact |
|---|---|---|---|
| `real_geometry` | `pass` | `real` | `/Volumes/Samsung SSD/hpa-mdo/hpa_meshing_package/docs/reports/main_wing_esp_rebuilt_geometry_smoke/main_wing_esp_rebuilt_geometry_smoke.v1.json` |
| `geometry_provenance` | `pass` | `real` | `/Volumes/Samsung SSD/hpa-mdo/hpa_meshing_package/docs/reports/main_wing_geometry_provenance_probe/main_wing_geometry_provenance_probe.v1.json` |
| `vspaero_panel_reference` | `pass` | `real` | `/Volumes/Samsung SSD/hpa-mdo/hpa_meshing_package/docs/reports/main_wing_vspaero_panel_reference_probe/main_wing_vspaero_panel_reference_probe.v1.json` |
| `real_mesh_handoff` | `pass` | `real` | `/Volumes/Samsung SSD/hpa-mdo/hpa_meshing_package/docs/reports/main_wing_real_mesh_handoff_probe/main_wing_real_mesh_handoff_probe.v1.json` |
| `synthetic_mesh_handoff` | `materialized_synthetic_only` | `synthetic` | `/Volumes/Samsung SSD/hpa-mdo/hpa_meshing_package/docs/reports/main_wing_mesh_handoff_smoke/main_wing_mesh_handoff_smoke.v1.json` |
| `synthetic_su2_handoff` | `materialized_synthetic_only` | `synthetic` | `/Volumes/Samsung SSD/hpa-mdo/hpa_meshing_package/docs/reports/main_wing_su2_handoff_smoke/main_wing_su2_handoff_smoke.v1.json` |
| `real_su2_handoff` | `pass` | `real` | `/Volumes/Samsung SSD/hpa-mdo/hpa_meshing_package/docs/reports/main_wing_real_su2_handoff_probe/main_wing_real_su2_handoff_probe.v1.json` |
| `openvsp_reference_su2_handoff` | `pass` | `real` | `/Volumes/Samsung SSD/hpa-mdo/hpa_meshing_package/docs/reports/main_wing_openvsp_reference_su2_handoff_probe/main_wing_openvsp_reference_su2_handoff_probe.v1.json` |
| `su2_force_marker_audit` | `pass` | `real` | `/Volumes/Samsung SSD/hpa-mdo/hpa_meshing_package/docs/reports/main_wing_su2_force_marker_audit/main_wing_su2_force_marker_audit.v1.json` |
| `surface_force_output_audit` | `pass` | `real` | `/Volumes/Samsung SSD/hpa-mdo/hpa_meshing_package/docs/reports/main_wing_surface_force_output_audit/main_wing_surface_force_output_audit.v1.json` |
| `openvsp_reference_geometry_gate` | `blocked` | `real` | `/Volumes/Samsung SSD/hpa-mdo/hpa_meshing_package/docs/reports/main_wing_openvsp_reference_geometry_gate/main_wing_reference_geometry_gate.v1.json` |
| `openvsp_reference_solver_smoke` | `pass` | `real` | `/Volumes/Samsung SSD/hpa-mdo/hpa_meshing_package/docs/reports/main_wing_openvsp_reference_solver_smoke_probe/main_wing_real_solver_smoke_probe.v1.json` |
| `openvsp_reference_solver_budget_probe` | `pass` | `real` | `/Volumes/Samsung SSD/hpa-mdo/hpa_meshing_package/docs/reports/main_wing_openvsp_reference_solver_smoke_probe_iter80/main_wing_real_solver_smoke_probe.v1.json` |
| `solver_smoke` | `pass` | `real` | `/Volumes/Samsung SSD/hpa-mdo/hpa_meshing_package/docs/reports/main_wing_real_solver_smoke_probe/main_wing_real_solver_smoke_probe.v1.json` |
| `solver_budget_probe` | `pass` | `real` | `/Volumes/Samsung SSD/hpa-mdo/hpa_meshing_package/docs/reports/main_wing_real_solver_smoke_probe_iter40/main_wing_real_solver_smoke_probe.v1.json` |
| `lift_acceptance_diagnostic` | `blocked` | `real` | `/Volumes/Samsung SSD/hpa-mdo/hpa_meshing_package/docs/reports/main_wing_lift_acceptance_diagnostic/main_wing_lift_acceptance_diagnostic.v1.json` |
| `convergence_gate` | `blocked` | `real` | `/Volumes/Samsung SSD/hpa-mdo/hpa_meshing_package/docs/reports/main_wing_real_solver_smoke_probe/main_wing_real_solver_smoke_probe.v1.json` |

## Blocking Reasons

- `main_wing_real_reference_geometry_warn`
- `main_wing_reference_geometry_incomplete`
- `main_wing_reference_area_differs_from_openvsp_sref`
- `main_wing_moment_origin_not_certified`
- `solver_executed_but_not_converged`
- `main_wing_cl_below_expected_lift`
- `alpha_zero_operating_lift_not_demonstrated`
- `solver_not_converged`
- `reference_geometry_warn`
- `mesh_quality_warning_present`
- `reference_area_delta_too_small_to_explain_lift_deficit`
- `vspaero_panel_cl_gt_one_while_su2_low`
- `panel_to_su2_cl_ratio_above_four`

## Next Actions

- `resolve_main_wing_cl_below_expected_lift_before_convergence_claims`
- `run_bounded_main_wing_iteration_sweep_after_reference_gate_is_clean`
- `preserve_synthetic_su2_as_wiring_evidence_only`

## Notes

- Synthetic mesh/SU2 stages prove route wiring only; they are not real aircraft CFD evidence.
- A materialized SU2 handoff is not a solver run, and a solver run is not convergence.
- Lift acceptance is a report-only gate here; main-wing convergence acceptance at V=6.5 m/s still requires CL > 1.0.
- VSPAERO panel reference evidence is a lower-order sanity baseline only; it is not high-fidelity CFD.
- Surface-force output retention is required before panel/SU2 force breakdown can be used to debug the CL gap.
- HPA standard flow is V=6.5 m/s; V=10 artifacts are legacy mismatch evidence only.
