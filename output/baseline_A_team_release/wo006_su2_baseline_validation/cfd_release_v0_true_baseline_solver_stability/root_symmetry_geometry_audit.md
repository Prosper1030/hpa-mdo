# Root Symmetry Geometry Audit

- exact_original_patch_name: `tip_left`
- original_polyMesh_boundary_type: `patch`
- corrected_patch_name: `root_symmetry`
- polyMesh_boundary_patch_type: `symmetryPlane`
- field_bc_types: `{'U': 'symmetryPlane', 'p': 'symmetryPlane', 'nut': 'symmetryPlane', 'nuTilda': 'symmetryPlane'}`
- root_symmetry_face_count: `12800`
- root_symmetry_vertex_y_min_m: `0.0`
- root_symmetry_vertex_y_max_m: `0.0`
- max_abs_y_deviation_from_zero_m: `0.0`
- normal_direction_statistics: `{'count': 12800, 'x': {'min': 0.0, 'max': 0.0, 'mean': 0.0}, 'y': {'min': -1.0, 'max': -1.0, 'mean': -1.0}, 'z': {'min': 0.0, 'max': 0.0, 'mean': 0.0}, 'abs_y': {'min': 1.0, 'max': 1.0, 'mean': 1.0}, 'dominant_direction': '-y'}`
- all_faces_lie_on_single_y0_plane: `True`
- role_contamination_audit: `{'solid_root_cap_faces_detected': False, 'farfield_faces_detected_as_mislabeled_patch': False, 'te_or_collar_faces_detected_as_mislabeled_patch': False, 'ambiguous_geometry': False, 'interpretation': 'root patch is a planar y=0 domain cut through the C-grid volume, which is geometrically consistent with a symmetryPlane; no non-planar wall/farfield/TE patch mixture was detected by coordinate and normal checks', 'center_extent': {'x': {'min': -11.250910630685, 'max': 11.230298833885}, 'y': {'min': 0.0, 'max': 0.0}, 'z': {'min': -12.2142682294, 'max': 10.422630428140002}}}`
- root_symmetry_excluded_from_force_functionObjects: `True`
- polyMesh_patch_type_compatibility: `{'test_required': False, 'result': 'not_required_corrected_polyMesh_patch_type_is_symmetryPlane'}`
