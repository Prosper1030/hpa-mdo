# main_wing route readiness v1

- overall_status: `solver_executed_not_converged`
- hpa_standard_flow_status: `hpa_standard_6p5_observed`
- observed_velocity_mps: `6.5`

## Stages

| stage | status | evidence | artifact |
|---|---|---|---|
| `real_geometry` | `pass` | `real` | `/Volumes/Samsung SSD/hpa-mdo/hpa_meshing_package/docs/reports/main_wing_esp_rebuilt_geometry_smoke/main_wing_esp_rebuilt_geometry_smoke.v1.json` |
| `real_mesh_handoff` | `pass` | `real` | `/Volumes/Samsung SSD/hpa-mdo/hpa_meshing_package/docs/reports/main_wing_real_mesh_handoff_probe/main_wing_real_mesh_handoff_probe.v1.json` |
| `synthetic_mesh_handoff` | `materialized_synthetic_only` | `synthetic` | `/Volumes/Samsung SSD/hpa-mdo/hpa_meshing_package/docs/reports/main_wing_mesh_handoff_smoke/main_wing_mesh_handoff_smoke.v1.json` |
| `synthetic_su2_handoff` | `materialized_synthetic_only` | `synthetic` | `/Volumes/Samsung SSD/hpa-mdo/hpa_meshing_package/docs/reports/main_wing_su2_handoff_smoke/main_wing_su2_handoff_smoke.v1.json` |
| `real_su2_handoff` | `pass` | `real` | `/Volumes/Samsung SSD/hpa-mdo/hpa_meshing_package/docs/reports/main_wing_real_su2_handoff_probe/main_wing_real_su2_handoff_probe.v1.json` |
| `openvsp_reference_su2_handoff` | `pass` | `real` | `/Volumes/Samsung SSD/hpa-mdo/hpa_meshing_package/docs/reports/main_wing_openvsp_reference_su2_handoff_probe/main_wing_openvsp_reference_su2_handoff_probe.v1.json` |
| `openvsp_reference_solver_smoke` | `pass` | `real` | `/Volumes/Samsung SSD/hpa-mdo/hpa_meshing_package/docs/reports/main_wing_openvsp_reference_solver_smoke_probe/main_wing_real_solver_smoke_probe.v1.json` |
| `openvsp_reference_solver_budget_probe` | `pass` | `real` | `/Volumes/Samsung SSD/hpa-mdo/hpa_meshing_package/docs/reports/main_wing_openvsp_reference_solver_smoke_probe_iter80/main_wing_real_solver_smoke_probe.v1.json` |
| `solver_smoke` | `pass` | `real` | `/Volumes/Samsung SSD/hpa-mdo/hpa_meshing_package/docs/reports/main_wing_real_solver_smoke_probe/main_wing_real_solver_smoke_probe.v1.json` |
| `solver_budget_probe` | `pass` | `real` | `/Volumes/Samsung SSD/hpa-mdo/hpa_meshing_package/docs/reports/main_wing_real_solver_smoke_probe_iter40/main_wing_real_solver_smoke_probe.v1.json` |
| `convergence_gate` | `blocked` | `real` | `/Volumes/Samsung SSD/hpa-mdo/hpa_meshing_package/docs/reports/main_wing_real_solver_smoke_probe/main_wing_real_solver_smoke_probe.v1.json` |

## Blocking Reasons

- `main_wing_real_reference_geometry_warn`
- `main_wing_reference_geometry_incomplete`
- `main_wing_reference_area_differs_from_openvsp_sref`
- `main_wing_moment_origin_not_certified`
- `solver_executed_but_not_converged`

## Next Actions

- `diagnose_main_wing_solver_nonconvergence_before_cfd_claims`
- `run_bounded_main_wing_iteration_sweep_after_reference_gate_is_clean`
- `preserve_synthetic_su2_as_wiring_evidence_only`

## Notes

- Synthetic mesh/SU2 stages prove route wiring only; they are not real aircraft CFD evidence.
- A materialized SU2 handoff is not a solver run, and a solver run is not convergence.
- HPA standard flow is V=6.5 m/s; V=10 artifacts are legacy mismatch evidence only.
