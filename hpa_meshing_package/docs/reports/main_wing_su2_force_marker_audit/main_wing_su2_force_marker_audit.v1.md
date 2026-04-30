# Main Wing SU2 Force Marker Audit v1

This report reads existing SU2 handoff artifacts only; it does not execute SU2.

- audit_status: `warn`
- production_default_changed: `False`
- su2_handoff_path: `/Volumes/Samsung SSD/hpa-mdo/hpa_meshing_package/docs/reports/main_wing_openvsp_reference_su2_handoff_probe/artifacts/su2_handoff.json`
- runtime_cfg_path: `/Volumes/Samsung SSD/hpa-mdo/hpa_meshing_package/docs/reports/main_wing_openvsp_reference_su2_handoff_probe/artifacts/su2_runtime.cfg`

## Checks

| check | status |
|---|---|
| `force_surface_provenance` | `pass` |
| `runtime_cfg_markers` | `pass` |
| `mesh_marker_counts` | `pass` |
| `flow_reference_consistency` | `pass` |

## Flow Reference Observed

- `velocity_mps`: `6.5`
- `cfg_velocity_x_mps`: `6.5`
- `ref_area_m2`: `35.175`
- `cfg_ref_area_m2`: `35.175`
- `ref_length_m`: `1.0425`
- `cfg_ref_length_m`: `1.0425`
- `wall_boundary_condition`: `euler`
- `solver`: `INC_NAVIER_STOKES`

## Engineering Flags

- `main_wing_solver_wall_bc_is_euler_smoke_not_viscous`
- `main_wing_reference_geometry_warn`

## Blocking Reasons


## Next Actions

- `record_euler_wall_as_solver_smoke_scope_not_viscous_cfd`
- `resolve_reference_moment_origin_before_force_claims`
- `compare_surface_force_outputs_against_vspaero_panel_reference`

## Limitations

- This audit reads existing handoff/config/mesh-marker artifacts only and does not run SU2.
- Euler wall boundary conditions are valid smoke-route evidence, not viscous CFD readiness.
- A marker audit cannot prove coefficient correctness without surface force output comparison.
