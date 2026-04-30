# Main Wing Station Seam Repair Decision v1

This decision gate decides whether station topology repair must precede more solver budget.

- repair_decision_status: `station_seam_repair_required_before_solver_budget`
- topology_fixture_path: `/Volumes/Samsung SSD/hpa-mdo/hpa_meshing_package/docs/reports/main_wing_openvsp_section_station_topology_fixture/main_wing_openvsp_section_station_topology_fixture.v1.json`
- solver_report_path: `/Volumes/Samsung SSD/hpa-mdo/hpa_meshing_package/docs/reports/main_wing_openvsp_reference_solver_smoke_probe_iter80/main_wing_real_solver_smoke_probe.v1.json`
- production_default_changed: `False`

## Topology Fixture Observed

- `topology_fixture_status`: `real_defect_station_fixture_materialized`
- `station_fixture_count`: `2`
- `total_boundary_edge_count`: `4`
- `total_nonmanifold_edge_count`: `2`
- `candidate_curve_tags`: `[36, 50]`
- `source_section_indices`: `[3, 4]`
- `all_cases_violate_canonical_station_topology_contract`: `True`

## Solver Context Observed

- `solver_execution_status`: `solver_executed`
- `convergence_gate_status`: `fail`
- `run_status`: `solver_executed_but_not_converged`
- `observed_velocity_mps`: `6.5`
- `main_wing_lift_acceptance_status`: `fail`
- `minimum_acceptable_cl`: `1.0`
- `final_cl`: `0.263161913`
- `final_coefficients`: `{"cl": 0.263161913, "cd": 0.02496911575, "cm": -0.2096803732, "cm_axis": "CMy"}`

## Decision Rationale

- `station_topology_contract_violated_by_real_fixture`
- `boundary_or_nonmanifold_station_edges_are_geometry_route_risk`
- `solver_budget_is_not_primary_next_gate_while_station_fixture_fails`
- `solver_execution_is_not_convergence_evidence`

## Repair Candidate Requirements

- `eliminate_boundary_and_nonmanifold_edges_at_station_curve_tags_36_50`
- `preserve_main_wing_force_marker_ownership`
- `preserve_openvsp_section_profile_scale_for_curve_tags_36_50`
- `rerun_station_fixture_and_gmsh_defect_trace_before_solver_budget_claims`
- `do_not_use_surface_id_patch_as_route_repair`

## Blocking Reasons

- `station_seam_repair_required_before_solver_budget`

## Next Actions

- `prototype_station_seam_repair_against_minimal_fixture`
- `run_main_wing_gmsh_defect_entity_trace_on_repair_candidate`
- `keep_solver_budget_source_backed_after_geometry_topology_gate`

## Limitations

- This is a decision gate only; it does not modify Gmsh, OpenVSP, or SU2 inputs.
- A required repair decision is a route blocker, not evidence that the geometry has been repaired.
- Solver execution remains non-convergence evidence unless the convergence and CL gates pass under source-backed settings.
