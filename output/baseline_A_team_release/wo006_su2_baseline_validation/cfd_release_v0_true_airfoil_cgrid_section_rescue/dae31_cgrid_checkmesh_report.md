# dae31_root_section C-Grid CheckMesh Report

- status: `checkmesh_failed`
- case dir: `output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0_true_airfoil_cgrid_section_rescue/openfoam_cases/dae31_root_section`
- custom quality: `pass`
- custom blockers: `[]`
- boundary faces: `{'airfoil_upper': 96, 'airfoil_lower': 96, 'te_wall': 8, 'outlet': 8, 'farfield': 192, 'tip_left': 16000, 'tip_right': 16000}`
- first layer height m: `5e-05`
- max skewness: `2.45064`
- max non-orthogonality deg: `80.1398`
- max aspect ratio: `None`
- high aspect cells: `None`
- determinant faces below section threshold: `0`
- failed check count: `None`
- strict primary gate: `{'status': 'smoke_only', 'log': 'output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0_true_airfoil_cgrid_section_rescue/openfoam_cases/dae31_root_section/log.checkMesh', 'mesh_ok': True, 'failed_check_count': None, 'max_non_orthogonality_deg': 80.1398, 'max_skewness': 2.45064, 'short_edge_count': None, 'min_cell_determinant': None, 'underdetermined_cell_count': None, 'fatal_error': False}`
- strict allTopology/allGeometry gate: `{'status': 'fail', 'log': 'output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0_true_airfoil_cgrid_section_rescue/openfoam_cases/dae31_root_section/log.checkMesh_allGeometry', 'mesh_ok': False, 'failed_check_count': 1, 'max_non_orthogonality_deg': 80.1398, 'max_skewness': 2.45064, 'short_edge_count': 14, 'min_cell_determinant': 5.81955e-05, 'underdetermined_cell_count': 1846, 'fatal_error': False}`
- section gate note: `maxNonOrtho=85 section-only tolerance; no solver is allowed from this section case.`
