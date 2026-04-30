# Component Family Route Smoke Matrix v1

This is a pre-mesh dispatch smoke matrix. It does not execute Gmsh, BL runtime, or SU2.

- target_pipeline: `vsp_or_esp_to_gmsh_to_su2_for_hpa_main_wing_tail_fairing`
- execution_mode: `pre_mesh_dispatch_smoke`
- report_status: `completed`
- no_gmsh_execution: `True`
- no_su2_execution: `True`

## Matrix

| component | smoke | family | route | productization | mesh_handoff | SU2 | promotion |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `aircraft_assembly` | `dispatch_smoke_pass` | `thin_sheet_aircraft_assembly` | `gmsh_thin_sheet_aircraft_assembly` | `formal_v1` | `not_run` | `not_run` | `not_a_promotion_gate` |
| `main_wing` | `dispatch_smoke_pass` | `thin_sheet_lifting_surface` | `gmsh_thin_sheet_surface` | `experimental` | `not_run` | `not_run` | `blocked_before_solver_convergence` |
| `tail_wing` | `dispatch_smoke_pass` | `thin_sheet_lifting_surface` | `gmsh_thin_sheet_surface` | `registered_not_productized` | `not_run` | `not_run` | `blocked_before_solver_convergence` |
| `horizontal_tail` | `dispatch_smoke_pass` | `thin_sheet_lifting_surface` | `gmsh_thin_sheet_surface` | `registered_not_productized` | `not_run` | `not_run` | `blocked_before_mesh_handoff` |
| `vertical_tail` | `dispatch_smoke_pass` | `thin_sheet_lifting_surface` | `gmsh_thin_sheet_surface` | `registered_not_productized` | `not_run` | `not_run` | `blocked_before_mesh_handoff` |
| `fairing_solid` | `dispatch_smoke_pass` | `closed_solid` | `gmsh_closed_solid_volume` | `registered_not_productized` | `not_run` | `not_run` | `blocked_before_solver_convergence` |
| `fairing_vented` | `dispatch_smoke_pass` | `perforated_solid` | `gmsh_perforated_solid_volume` | `registered_not_productized` | `not_run` | `not_run` | `blocked_before_mesh_handoff` |

## Scope Policy

- `root_last3_policy`: `excluded_not_product_route`
- `root_last4_policy`: `excluded_overlap_non_regression_only`
- `bl_runtime_policy`: `not_executed`
- `gmsh_policy`: `not_executed`
- `su2_policy`: `not_executed`

## Limitations

- This is a report-only component-family smoke matrix.
- It checks route architecture coverage for VSP/ESP -> Gmsh -> SU2 handoff planning.
- A pass here means the route skeleton is visible and internally classified.
- It is not a production mesh pass, solver pass, BL promotion, or CFD credibility claim.

## Next Actions

- `replace synthetic fairing fixture with real fairing geometry before solver claims`
- `replace synthetic main_wing fixture with real ESP/VSP geometry before solver claims`
- `run real tail_wing mesh handoff from ESP/VSP geometry before solver claims`
- `keep BL prelaunch excluded until handoff topology ownership passes`
