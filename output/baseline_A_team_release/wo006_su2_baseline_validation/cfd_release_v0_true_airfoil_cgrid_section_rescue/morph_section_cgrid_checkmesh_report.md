# morph_dae31_to_cst_tip_section C-Grid CheckMesh Report

- status: `checkmesh_failed`
- case dir: `output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0_true_airfoil_cgrid_section_rescue/openfoam_cases/morph_dae31_to_cst_tip_section`
- custom quality: `pass`
- custom blockers: `[]`
- boundary faces: `{'airfoil_upper': 96, 'airfoil_lower': 95, 'te_wall': 8, 'outlet': 8, 'farfield': 191, 'tip_left': 15920, 'tip_right': 15920}`
- first layer height m: `5e-05`
- max skewness: `2.47632`
- max non-orthogonality deg: `84.2988`
- max aspect ratio: `None`
- high aspect cells: `None`
- determinant faces below section threshold: `0`
- failed check count: `1`
- strict primary gate: `{'status': 'fail', 'log': 'output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0_true_airfoil_cgrid_section_rescue/openfoam_cases/morph_dae31_to_cst_tip_section/log.checkMesh', 'mesh_ok': False, 'failed_check_count': 1, 'max_non_orthogonality_deg': 84.2988, 'max_skewness': 2.47632, 'fatal_error': False}`
- strict allTopology/allGeometry gate: `{'status': 'fail', 'log': 'output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0_true_airfoil_cgrid_section_rescue/openfoam_cases/morph_dae31_to_cst_tip_section/log.checkMesh_allGeometry', 'mesh_ok': False, 'failed_check_count': None, 'max_non_orthogonality_deg': None, 'max_skewness': None, 'fatal_error': False}`
- section gate note: `maxNonOrtho=85 section-only tolerance; no solver is allowed from this section case.`
