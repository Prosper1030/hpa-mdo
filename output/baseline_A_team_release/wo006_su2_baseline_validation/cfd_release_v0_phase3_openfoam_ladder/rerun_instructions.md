# OpenFOAM Ladder Rerun Instructions

Run the full bounded ladder from the repo root:

```bash
PYTHONPATH=src ./.venv/bin/python scripts/run_wo006_phase3_openfoam_ladder.py --clean
```

Accepted case configs are stored in `ladder_manifest.json` under `rerun_basis.case_config`; case files live under `openfoam_cases/`.

## Accepted Cases

### layers_0

- case_dir: `/Volumes/Samsung SSD/hpa-mdo/output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0_phase3_openfoam_ladder/openfoam_cases/layers_0`
- purpose: `baseline_no_layers`
- config: `{'case_id': 'layers_0', 'n_surface_layers': 0, 'expansion_ratio': 1.2, 'final_layer_thickness': 0.3, 'min_thickness': 0.05, 'feature_angle': 60, 'n_smooth_surface_normals': 1, 'n_smooth_normals': 3, 'n_smooth_thickness': 10, 'n_layer_iter': 50, 'refinement_delta': 0, 'max_local_cells': 500000, 'max_global_cells': 3000000, 'low_yplus_factor': None, 'purpose': 'baseline_no_layers'}`

### layers_8

- case_dir: `/Volumes/Samsung SSD/hpa-mdo/output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0_phase3_openfoam_ladder/openfoam_cases/layers_8`
- purpose: `route_smoke_reproduction`
- config: `{'case_id': 'layers_8', 'n_surface_layers': 8, 'expansion_ratio': 1.2, 'final_layer_thickness': 0.3, 'min_thickness': 0.05, 'feature_angle': 60, 'n_smooth_surface_normals': 1, 'n_smooth_normals': 3, 'n_smooth_thickness': 10, 'n_layer_iter': 50, 'refinement_delta': 0, 'max_local_cells': 500000, 'max_global_cells': 3000000, 'low_yplus_factor': None, 'purpose': 'route_smoke_reproduction'}`

### layers_16

- case_dir: `/Volumes/Samsung SSD/hpa-mdo/output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0_phase3_openfoam_ladder/openfoam_cases/layers_16`
- purpose: `layer_ladder`
- config: `{'case_id': 'layers_16', 'n_surface_layers': 16, 'expansion_ratio': 1.16, 'final_layer_thickness': 0.3, 'min_thickness': 0.025, 'feature_angle': 70, 'n_smooth_surface_normals': 3, 'n_smooth_normals': 5, 'n_smooth_thickness': 10, 'n_layer_iter': 90, 'refinement_delta': 0, 'max_local_cells': 500000, 'max_global_cells': 3000000, 'low_yplus_factor': None, 'purpose': 'layer_ladder'}`

### layers_24

- case_dir: `/Volumes/Samsung SSD/hpa-mdo/output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0_phase3_openfoam_ladder/openfoam_cases/layers_24`
- purpose: `layer_ladder`
- config: `{'case_id': 'layers_24', 'n_surface_layers': 24, 'expansion_ratio': 1.14, 'final_layer_thickness': 0.28, 'min_thickness': 0.012, 'feature_angle': 75, 'n_smooth_surface_normals': 4, 'n_smooth_normals': 6, 'n_smooth_thickness': 10, 'n_layer_iter': 120, 'refinement_delta': 0, 'max_local_cells': 500000, 'max_global_cells': 3000000, 'low_yplus_factor': None, 'purpose': 'layer_ladder'}`
