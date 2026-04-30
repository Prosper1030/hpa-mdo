# Main Wing SU2 Surface Topology Audit v1

This report reads the existing Gmsh mesh only; it does not execute SU2.

- audit_status: `thin_surface_like_with_local_topology_defects`
- mesh_path: `/Volumes/Samsung SSD/hpa-mdo/hpa_meshing_package/docs/reports/main_wing_real_mesh_handoff_probe/artifacts/real_mesh_probe/artifacts/mesh/mesh.msh`
- reference_area_m2: `35.175`
- production_default_changed: `False`

## Edge Topology

- `surface_triangle_count`: `2424`
- `unique_edge_count`: `3637`
- `boundary_edge_count`: `4`
- `nonmanifold_edge_count`: `2`
- `boundary_edge_fraction`: `0.00109981`
- `nonmanifold_edge_fraction`: `0.000549904`
- `sample_boundary_edges`: `[[252, 253], [251, 252], [360, 361], [359, 360]]`
- `sample_nonmanifold_edges`: `[{"edge": [251, 253], "use_count": 3}, {"edge": [359, 361], "use_count": 3}]`

## Area Evidence

- `surface_area_m2`: `42.4321`
- `projected_abs_lift_axis_area_m2`: `37.8478`
- `reference_area_m2`: `35.175`
- `surface_area_to_reference_area_ratio`: `1.20631`
- `projected_abs_area_to_reference_area_ratio`: `1.07599`
- `single_sheet_area_like`: `True`
- `double_sided_closed_area_like`: `False`

## Bounding Box

- `status`: `available`
- `x_min`: `0.0144031`
- `x_max`: `1.30233`
- `y_min`: `-16.5`
- `y_max`: `16.5`
- `z_min`: `-0.0680367`
- `z_max`: `0.796158`
- `x_extent`: `1.28793`
- `y_extent`: `33`
- `z_extent`: `0.864195`

## Engineering Findings

- `open_boundary_edges_present`
- `open_boundary_edges_localized_low_fraction`
- `nonmanifold_edges_present`
- `thin_or_single_sheet_surface_area_evidence_observed`
- `main_wing_surface_edges_mostly_manifold`
- `thin_surface_like_area_with_local_topology_defects`

## Blocking Reasons

- none

## Next Actions

- `localize_main_wing_open_boundary_and_nonmanifold_edges`
- `inspect_openvsp_export_surface_thickness_before_more_solver_iterations`
- `decide_main_wing_product_route_lifting_surface_vs_closed_thickness_cfd_geometry`

## Limitations

- This audit reads the existing Gmsh mesh only; it does not repair topology.
- Area-ratio labels are engineering evidence, not a proof of aerodynamic equivalence.
- A thin/single-sheet-like surface remains route risk until OpenVSP export semantics are confirmed.
