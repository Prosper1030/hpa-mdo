# root_dae31_section CheckMesh Report

- status: `checkmesh_failed`
- case dir: `output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0_swept_cgrid_structured_hexa/openfoam_cases/root_dae31_section`
- custom quality: `pass`
- checkMesh: `fail`
- boundary faces: `{'wing_upper': 96, 'wing_lower': 95, 'tip_left': 12288, 'tip_right': 12288, 'te_wall': 1, 'closure_wall': 0, 'farfield': 192}`
- max skewness: `19010.2`
- highly skew faces: `285`
- mesh-quality errors: `{'non-orthogonality > 65  degrees': 643, 'faces with face pyramid volume < 1e-13': 24, 'faces with face-decomposition tet quality < 1e-15': 306, 'faces with concavity > 80  degrees': 0, 'faces with skewness > 7   (internal) or 20  (boundary)': 30, 'faces with interpolation weights (0..1)  < 0.02': 39, 'faces with volume ratio of neighbour cells < 0.01': 0, 'faces with face twist < 0.02': 1, 'faces on cells with determinant < 0.001': 8908}`
- checkMesh summary lines:

```text
Checking topology...
Checking geometry...
  <<Writing 527 cells with high aspect ratio to set highAspectRatioCells
    Mesh non-orthogonality Max: 179.918 average: 16.6347
 ***Number of non-orthogonality errors: 383.
 ***Max skewness = 19010.2, 285 highly skew faces detected which may impair the quality of the results
Checking faces in error :
    non-orthogonality > 65  degrees                        : 643
    faces with skewness > 7   (internal) or 20  (boundary) : 30
Failed 7 mesh checks.
```
