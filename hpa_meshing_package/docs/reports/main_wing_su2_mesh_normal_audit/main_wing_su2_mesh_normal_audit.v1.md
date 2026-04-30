# Main Wing SU2 Mesh Normal Audit v1

This report reads the existing Gmsh mesh only; it does not execute SU2.

- normal_audit_status: `pass`
- mesh_path: `/Volumes/Samsung SSD/hpa-mdo/hpa_meshing_package/docs/reports/main_wing_real_mesh_handoff_probe/artifacts/real_mesh_probe/artifacts/mesh/mesh.msh`
- physical_group_tag: `2`
- main_wing_surface_entity_count: `32`
- surface_triangle_count: `2424`
- production_default_changed: `False`

## Normal Orientation

- `status`: `pass`
- `valid_triangle_count`: `2424`
- `missing_node_triangle_count`: `0`
- `z_positive_fraction`: `0.511964`
- `z_negative_fraction`: `0.483911`
- `z_near_zero_fraction`: `0.00412541`
- `area_weighted_mean_normal`: `[1.0143938927015298e-18, -0.0008604344522536509, -1.261221222764421e-17]`
- `area_weighted_abs_z_mean`: `0.891962`
- `min_normal`: `[-0.9999452769580452, -1.0, -0.9999626426937179]`
- `max_normal`: `[0.513631443714756, 1.0, 0.9999802566224099]`
- `total_surface_area`: `42.4321`

## Engineering Findings

- `main_wing_surface_normals_mixed_upper_lower`
- `single_global_normal_flip_not_supported`
- `main_wing_normals_mostly_lift_axis_oriented`

## Blocking Reasons

- none

## Next Actions

- `compare_openvsp_panel_wake_model_against_su2_thin_sheet_wall_semantics`
- `inspect_wing_surface_pairing_and_lifting_surface_export`
- `check_upper_lower_surface_incidence_against_panel_geometry`

## Limitations

- This audit reads the existing Gmsh mesh only; it does not repair normals.
- Mixed upper/lower normals are expected for a closed or paired thin wing surface.
- Normal orientation alone cannot prove SU2 and VSPAERO lifting semantics match.
