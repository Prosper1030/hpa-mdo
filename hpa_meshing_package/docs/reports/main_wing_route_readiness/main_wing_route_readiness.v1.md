# main_wing route readiness v1

- overall_status: `solver_not_run`
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
| `solver_smoke` | `not_run` | `absent` | `` |
| `convergence_gate` | `not_run` | `absent` | `` |

## Blocking Reasons

- `main_wing_real_reference_geometry_warn`
- `main_wing_solver_not_run`
- `convergence_gate_not_run`

## Next Actions

- `run_main_wing_solver_smoke_from_real_su2_handoff`
- `run_solver_smoke_then_convergence_gate_after_real_su2_handoff`
- `preserve_synthetic_su2_as_wiring_evidence_only`

## Notes

- Synthetic mesh/SU2 stages prove route wiring only; they are not real aircraft CFD evidence.
- A materialized SU2 handoff is not a solver run, and a solver run is not convergence.
- HPA standard flow is V=6.5 m/s; V=10 artifacts are legacy mismatch evidence only.
