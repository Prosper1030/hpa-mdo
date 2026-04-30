# Component Family Route Readiness v1

- target_pipeline: `vsp_or_esp_to_gmsh_to_su2_for_hpa_main_wing_tail_fairing`
- primary_decision: `switch_to_component_family_route_architecture`
- product_line_rule: Do not promote a component family by making one shell_v4 fixture pass; promote it only after provider, meshing, mesh_handoff, su2_handoff, and convergence artifacts exist.

## Route Matrix

| component | status | route role | default route | SU2 | BL policy | Gmsh boundary policy |
| --- | --- | --- | --- | --- | --- | --- |
| `aircraft_assembly` | `formal_v1` | `current_product_line` | `gmsh_thin_sheet_aircraft_assembly` | `baseline_productized` | `not_required_for_baseline` | `baseline_gmsh_backend_boundary_recovery` |
| `main_wing` | `experimental` | `experimental_and_diagnostic` | `gmsh_thin_sheet_surface` | `handoff_materialized_force_marker_owned_solver_not_run` | `promotion_only_when_hpa_mdo_owns_handoff_topology` | `not_allowed_as_owned_boundary_handoff` |
| `tail_wing` | `registered_not_productized` | `registered_future_route` | `gmsh_thin_sheet_surface` | `handoff_materialized_force_marker_owned_solver_not_run` | `not_default` | `core_tetra_only_after_owned_boundary_handoff` |
| `horizontal_tail` | `registered_not_productized` | `registered_future_route` | `gmsh_thin_sheet_surface` | `blocked_until_route_smoke` | `not_default` | `core_tetra_only_after_owned_boundary_handoff` |
| `vertical_tail` | `registered_not_productized` | `registered_future_route` | `gmsh_thin_sheet_surface` | `blocked_until_route_smoke` | `not_default` | `core_tetra_only_after_owned_boundary_handoff` |
| `fairing_solid` | `registered_not_productized` | `registered_future_route` | `gmsh_closed_solid_volume` | `handoff_materialized_force_marker_owned_solver_not_run` | `not_default` | `baseline_gmsh_backend_boundary_recovery` |
| `fairing_vented` | `registered_not_productized` | `registered_future_route` | `gmsh_perforated_solid_volume` | `blocked_until_route_smoke` | `not_default` | `baseline_gmsh_backend_boundary_recovery` |

## Promotion Gates

- `provider_materialized_or_formal_source_available`
- `geometry_family_classifier_resolved`
- `route_specific_mesh_smoke_completed`
- `mesh_handoff_v1_written`
- `su2_handoff_v1_written`
- `convergence_gate_v1_reported`
- `bl_transition_contract_passed_only_for_bl_promotions`

## shell_v4 Policy

- `role`: `diagnostic_regression_branch`
- `root_last3_policy`: `not_a_product_route`
- `root_last4_policy`: `overlap_non_regression_only`
- `promotion_rule`: `no_full_prelaunch_until_handoff_topology_is_owned`

## Gmsh Source Policy

- `primary_use`: `forensics_and_instrumentation`
- `do_not_use_as`: `primary_product_repair_path`
- `fork_threshold`: `only_after_reproducible_cross_fixture_gmsh_bug`

## Blocking Reasons

### `main_wing`
- `shell_v4_root_last3_is_not_product_route`
- `explicit_bl_to_core_handoff_topology_not_owned`
- `main_wing_real_geometry_smoke_missing`
- `main_wing_solver_not_run`
- `convergence_gate_not_run`

### `tail_wing`
- `tail_real_geometry_mesh_handoff_not_run`
- `tail_wing_solver_not_run`
- `convergence_gate_not_run`

### `horizontal_tail`
- `horizontal_tail_backend_not_productized`
- `tail_specific_geometry_smoke_missing`

### `vertical_tail`
- `vertical_tail_backend_not_productized`
- `tail_specific_geometry_smoke_missing`

### `fairing_solid`
- `fairing_real_geometry_smoke_missing`
- `fairing_solver_not_run`
- `convergence_gate_not_run`

### `fairing_vented`
- `fairing_vented_backend_not_productized`
- `perforation_ownership_and_marker_contract_missing`
