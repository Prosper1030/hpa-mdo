# Section Failed Check Localization

Phase 0 baseline evidence was captured before the bounded TE-gap matrix was accepted.
Previous available logs: `/Volumes/Samsung SSD/hpa-mdo/output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0_true_airfoil_cgrid_section_rescue`.

The live matrix below localizes every generated section/variant case. Coordinates are
reported in local section `x/chord, z/chord`; region tags separate TE upper cusp,
TE lower cusp, TE wake collar, LE curvature, outer farfield, radial first layer,
and morph correspondence.

## dae31_root_section

### gap_0p00

- status: `custom_mesh_failed`
- failed check names: `['custom_duplicate_points', 'highly_skew_faces', 'short_edges_allGeometry', 'small_cell_determinant_allGeometry', 'small_face_pyramid_volume', 'zero_or_negative_face_area']`
- failed check count: `11`
- failed cell/face counts: negative volumes `0`, open cells `0`, oriented pyramids `0`, small determinant cells `2049`, small interpolation weights `0`
- maxNonOrtho: `80.1567` at `radial first layer x/c=0.034829851742253476 z/c=-0.017186596379388557`
- maxSkew proxy: `2.64245e+145` at `radial first layer x/c=0.03506644653294866 z/c=-0.01714138546973725`
- cell sets:
  - `underdeterminedCells` count `2049`, centroid (0.46215988853540196, 0.04323704538882591), regions `{'radial first layer': 2048, 'LE curvature': 1}`
- face sets:
  - `nonOrthoFaces` count `904`, centroid (0.0594430278658973, -0.0177114280892338), regions `{'radial first layer': 904}`
  - `lowQualityTetFaces` count `24`, centroid (1.0000082843785874, -7.361651349296117e-18), regions `{'TE wake collar': 24}`

### gap_0p02

- status: `checkmesh_failed`
- failed check names: `['short_edges_allGeometry', 'small_cell_determinant_allGeometry']`
- failed check count: `1`
- failed cell/face counts: negative volumes `0`, open cells `0`, oriented pyramids `0`, small determinant cells `2049`, small interpolation weights `0`
- maxNonOrtho: `80.1567` at `radial first layer x/c=0.034829851742253476 z/c=-0.017186596379388557`
- maxSkew proxy: `1.97896` at `TE lower cusp x/c=1.0061515768548202 z/c=-0.00778939417381472`
- cell sets:
  - `underdeterminedCells` count `2049`, centroid (0.46215988853540196, 0.04323704538882591), regions `{'radial first layer': 2048, 'LE curvature': 1}`
- face sets:
  - `nonOrthoFaces` count `904`, centroid (0.0594430278658973, -0.0177114280892338), regions `{'radial first layer': 904}`

### gap_0p05

- status: `checkmesh_failed`
- failed check names: `['short_edges_allGeometry', 'small_cell_determinant_allGeometry']`
- failed check count: `1`
- failed cell/face counts: negative volumes `0`, open cells `0`, oriented pyramids `0`, small determinant cells `2049`, small interpolation weights `0`
- maxNonOrtho: `80.1567` at `radial first layer x/c=0.034829851742253476 z/c=-0.017186596379388557`
- maxSkew proxy: `2.45064` at `TE lower cusp x/c=1.0061515865672517 z/c=-0.00793929097198423`
- cell sets:
  - `underdeterminedCells` count `2049`, centroid (0.46215988853540196, 0.04323704538882591), regions `{'radial first layer': 2048, 'LE curvature': 1}`
- face sets:
  - `nonOrthoFaces` count `906`, centroid (0.06151936908279391, -0.017672952526343898), regions `{'radial first layer': 904, 'TE lower cusp': 2}`

### gap_0p10

- status: `checkmesh_failed`
- failed check names: `['highly_skew_faces', 'incorrectly_oriented_face_pyramids', 'non_orthogonality_over_threshold', 'open_cells', 'short_edges_allGeometry', 'small_cell_determinant_allGeometry', 'small_face_decomposition_tet_quality']`
- failed check count: `14`
- failed cell/face counts: negative volumes `0`, open cells `10`, oriented pyramids `5`, small determinant cells `2049`, small interpolation weights `0`
- maxNonOrtho: `99.8153` at `TE lower cusp x/c=1.0000387720738535 z/c=-0.0005484626690622186`
- maxSkew proxy: `29.4905` at `TE lower cusp x/c=1.0069574074696837 z/c=-0.009196324499137955`
- cell sets:
  - `underdeterminedCells` count `2049`, centroid (0.46215988853540196, 0.04323704538882591), regions `{'radial first layer': 2048, 'LE curvature': 1}`
- face sets:
  - `nonOrthoFaces` count `913`, centroid (0.06871530902177711, -0.01753757273571649), regions `{'radial first layer': 904, 'TE upper cusp': 4, 'TE lower cusp': 5}`
  - `lowQualityTetFaces` count `15`, centroid (0.9999259047275275, -7.013114387855902e-05), regions `{'TE upper cusp': 6, 'TE lower cusp': 9}`

## cst_tip_section

### gap_0p00

- status: `checkmesh_failed`
- failed check names: `['small_cell_determinant_allGeometry']`
- failed check count: `1`
- failed cell/face counts: negative volumes `0`, open cells `0`, oriented pyramids `0`, small determinant cells `814`, small interpolation weights `0`
- maxNonOrtho: `68.9838` at `radial first layer x/c=0.031204053513050924 z/c=-0.01477010364114351`
- maxSkew proxy: `2.27372` at `TE lower cusp x/c=1.0000242140901436 z/c=-0.0008818650350896379`
- cell sets:
  - `underdeterminedCells` count `814`, centroid (0.49453833949305465, 0.018039967126040723), regions `{'radial first layer': 814}`

### gap_0p02

- status: `checkmesh_failed`
- failed check names: `['small_cell_determinant_allGeometry']`
- failed check count: `1`
- failed cell/face counts: negative volumes `0`, open cells `0`, oriented pyramids `0`, small determinant cells `814`, small interpolation weights `0`
- maxNonOrtho: `68.9838` at `radial first layer x/c=0.031204053513050924 z/c=-0.01477010364114351`
- maxSkew proxy: `2.27372` at `TE lower cusp x/c=1.0000242140901436 z/c=-0.0008818650350896379`
- cell sets:
  - `underdeterminedCells` count `814`, centroid (0.49453833949305465, 0.018039967126040723), regions `{'radial first layer': 814}`

### gap_0p05

- status: `checkmesh_failed`
- failed check names: `['small_cell_determinant_allGeometry']`
- failed check count: `1`
- failed cell/face counts: negative volumes `0`, open cells `0`, oriented pyramids `0`, small determinant cells `814`, small interpolation weights `0`
- maxNonOrtho: `68.9838` at `radial first layer x/c=0.031204053513050924 z/c=-0.01477010364114351`
- maxSkew proxy: `2.27372` at `TE lower cusp x/c=1.0000242140901436 z/c=-0.0008818650350896379`
- cell sets:
  - `underdeterminedCells` count `814`, centroid (0.49453833949305465, 0.018039967126040723), regions `{'radial first layer': 814}`

### gap_0p10

- status: `checkmesh_failed`
- failed check names: `['small_cell_determinant_allGeometry']`
- failed check count: `1`
- failed cell/face counts: negative volumes `0`, open cells `0`, oriented pyramids `0`, small determinant cells `814`, small interpolation weights `0`
- maxNonOrtho: `68.9838` at `radial first layer x/c=0.031204053513050924 z/c=-0.01477010364114351`
- maxSkew proxy: `2.27372` at `TE lower cusp x/c=1.0000242140901436 z/c=-0.0008818650350896379`
- cell sets:
  - `underdeterminedCells` count `814`, centroid (0.49453833949305465, 0.018039967126040723), regions `{'radial first layer': 814}`

## morph_dae31_to_cst_tip_section

### gap_0p00

- status: `checkmesh_failed`
- failed check names: `['small_cell_determinant_allGeometry']`
- failed check count: `1`
- failed cell/face counts: negative volumes `0`, open cells `0`, oriented pyramids `0`, small determinant cells `1166`, small interpolation weights `0`
- maxNonOrtho: `74.4841` at `morph correspondence x/c=0.034470621519234745 z/c=-0.016381175040061563`
- maxSkew proxy: `1.97911` at `TE lower cusp x/c=1.0073094506446718 z/c=-0.009562224260329289`
- cell sets:
  - `underdeterminedCells` count `1166`, centroid (0.4923754846317458, 0.0332099965614563), regions `{'morph correspondence': 1166}`
- face sets:
  - `nonOrthoFaces` count `474`, centroid (0.04678061162972775, -0.018666164242648865), regions `{'morph correspondence': 474}`

### gap_0p02

- status: `checkmesh_failed`
- failed check names: `['small_cell_determinant_allGeometry']`
- failed check count: `1`
- failed cell/face counts: negative volumes `0`, open cells `0`, oriented pyramids `0`, small determinant cells `1166`, small interpolation weights `0`
- maxNonOrtho: `74.4841` at `morph correspondence x/c=0.034470621519234745 z/c=-0.016381175040061563`
- maxSkew proxy: `2.16351` at `TE lower cusp x/c=1.0000189639736943 z/c=-0.000499503839235461`
- cell sets:
  - `underdeterminedCells` count `1166`, centroid (0.4923754846317458, 0.0332099965614563), regions `{'morph correspondence': 1166}`
- face sets:
  - `nonOrthoFaces` count `474`, centroid (0.04678061162972775, -0.018666164242648865), regions `{'morph correspondence': 474}`

### gap_0p05

- status: `checkmesh_failed`
- failed check names: `['small_cell_determinant_allGeometry']`
- failed check count: `1`
- failed cell/face counts: negative volumes `0`, open cells `0`, oriented pyramids `0`, small determinant cells `1166`, small interpolation weights `0`
- maxNonOrtho: `74.4841` at `morph correspondence x/c=0.034470621519234745 z/c=-0.016381175040061563`
- maxSkew proxy: `2.84184` at `TE lower cusp x/c=1.0000189640604207 z/c=-0.0005745037698503362`
- cell sets:
  - `underdeterminedCells` count `1166`, centroid (0.4923754846317458, 0.0332099965614563), regions `{'morph correspondence': 1166}`
- face sets:
  - `nonOrthoFaces` count `474`, centroid (0.04678061162972775, -0.018666164242648865), regions `{'morph correspondence': 474}`

### gap_0p10

- status: `checkmesh_failed`
- failed check names: `['highly_skew_faces', 'small_cell_determinant_allGeometry']`
- failed check count: `3`
- failed cell/face counts: negative volumes `0`, open cells `0`, oriented pyramids `0`, small determinant cells `1166`, small interpolation weights `0`
- maxNonOrtho: `74.4841` at `morph correspondence x/c=0.034470621519234745 z/c=-0.016381175040061563`
- maxSkew proxy: `4.2021` at `TE upper cusp x/c=1.0000189642049664 z/c=0.0006995036542069478`
- cell sets:
  - `underdeterminedCells` count `1166`, centroid (0.4923754846317458, 0.0332099965614563), regions `{'morph correspondence': 1166}`
- face sets:
  - `nonOrthoFaces` count `474`, centroid (0.04678061162972775, -0.018666164242648865), regions `{'morph correspondence': 474}`

Interpretation:

- `gap_0p00` on DAE31 is the exact no-gap baseline and creates duplicate TE/collar
  points plus low-quality TE-collar face tets; it is not a viable production topology.
- `gap_0p02` and `gap_0p05` remove the explicit TE-collar low-quality face family,
  but all three sections still fail strict allGeometry on radial first-layer /
  morph-correspondence small determinant cells.
- `gap_0p10` over-regularizes DAE31: it reintroduces TE-cusp pyramid/open-cell
  failures, so increasing beyond the bounded 0.10% limit is not justified.
