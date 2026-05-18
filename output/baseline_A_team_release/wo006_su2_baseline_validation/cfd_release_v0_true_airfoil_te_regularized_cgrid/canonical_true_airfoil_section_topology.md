# Canonical True-Airfoil Section Topology

No canonical passing topology is selected.

The bounded TE-gap matrix is complete, but at least one required section still fails
`checkMesh -allTopology -allGeometry -meshQuality`.

Best failed variant: `{'variant': 'gap_0p02', 'failed_section_count': 3, 'max_non_orthogonality_deg': 80.1567, 'max_skewness': 2.27372, 'small_determinant_cell_count_sum': 4029}`

Failure mechanism:

`gap_0p00 dae31_root_section: status=custom_mesh_failed failedChecks=11 maxNonOrtho=80.1567 maxSkew=2.64245e+145 smallDet=2049 openCells=0 negativeVolumes=0 pyramidErrors=0; gap_0p00 cst_tip_section: status=checkmesh_failed failedChecks=1 maxNonOrtho=68.9838 maxSkew=2.27372 smallDet=814 openCells=0 negativeVolumes=0 pyramidErrors=0; gap_0p00 morph_dae31_to_cst_tip_section: status=checkmesh_failed failedChecks=1 maxNonOrtho=74.4841 maxSkew=1.97911 smallDet=1166 openCells=0 negativeVolumes=0 pyramidErrors=0; gap_0p02 dae31_root_section: status=checkmesh_failed failedChecks=1 maxNonOrtho=80.1567 maxSkew=1.97896 smallDet=2049 openCells=0 negativeVolumes=0 pyramidErrors=0; gap_0p02 cst_tip_section: status=checkmesh_failed failedChecks=1 maxNonOrtho=68.9838 maxSkew=2.27372 smallDet=814 openCells=0 negativeVolumes=0 pyramidErrors=0; gap_0p02 morph_dae31_to_cst_tip_section: status=checkmesh_failed failedChecks=1 maxNonOrtho=74.4841 maxSkew=2.16351 smallDet=1166 openCells=0 negativeVolumes=0 pyramidErrors=0; gap_0p05 dae31_root_section: status=checkmesh_failed failedChecks=1 maxNonOrtho=80.1567 maxSkew=2.45064 smallDet=2049 openCells=0 negativeVolumes=0 pyramidErrors=0; gap_0p05 cst_tip_section: status=checkmesh_failed failedChecks=1 maxNonOrtho=68.9838 maxSkew=2.27372 smallDet=814 openCells=0 negativeVolumes=0 pyramidErrors=0; gap_0p05 morph_dae31_to_cst_tip_section: status=checkmesh_failed failedChecks=1 maxNonOrtho=74.4841 maxSkew=2.84184 smallDet=1166 openCells=0 negativeVolumes=0 pyramidErrors=0; gap_0p10 dae31_root_section: status=checkmesh_failed failedChecks=14 maxNonOrtho=99.8153 maxSkew=29.4905 smallDet=2049 openCells=10 negativeVolumes=0 pyramidErrors=5; gap_0p10 cst_tip_section: status=checkmesh_failed failedChecks=1 maxNonOrtho=68.9838 maxSkew=2.27372 smallDet=814 openCells=0 negativeVolumes=0 pyramidErrors=0; gap_0p10 morph_dae31_to_cst_tip_section: status=checkmesh_failed failedChecks=3 maxNonOrtho=74.4841 maxSkew=4.2021 smallDet=1166 openCells=0 negativeVolumes=0 pyramidErrors=0`

## Section Status Table

| variant | section | status | maxNonOrtho | maxSkew | small determinant cells |
|---|---|---:|---:|---:|---:|
| gap_0p00 | dae31_root_section | custom_mesh_failed | 80.1567 | 2.64245e+145 | 2049 |
| gap_0p00 | cst_tip_section | checkmesh_failed | 68.9838 | 2.27372 | 814 |
| gap_0p00 | morph_dae31_to_cst_tip_section | checkmesh_failed | 74.4841 | 1.97911 | 1166 |
| gap_0p02 | dae31_root_section | checkmesh_failed | 80.1567 | 1.97896 | 2049 |
| gap_0p02 | cst_tip_section | checkmesh_failed | 68.9838 | 2.27372 | 814 |
| gap_0p02 | morph_dae31_to_cst_tip_section | checkmesh_failed | 74.4841 | 2.16351 | 1166 |
| gap_0p05 | dae31_root_section | checkmesh_failed | 80.1567 | 2.45064 | 2049 |
| gap_0p05 | cst_tip_section | checkmesh_failed | 68.9838 | 2.27372 | 814 |
| gap_0p05 | morph_dae31_to_cst_tip_section | checkmesh_failed | 74.4841 | 2.84184 | 1166 |
| gap_0p10 | dae31_root_section | checkmesh_failed | 99.8153 | 29.4905 | 2049 |
| gap_0p10 | cst_tip_section | checkmesh_failed | 68.9838 | 2.27372 | 814 |
| gap_0p10 | morph_dae31_to_cst_tip_section | checkmesh_failed | 74.4841 | 4.2021 | 1166 |
