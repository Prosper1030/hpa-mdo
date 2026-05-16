# cst_tip_section CheckMesh Report

- status: `checkmesh_failed`
- case dir: `output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0_swept_cgrid_structured_hexa/openfoam_cases/cst_tip_section`
- custom quality: `pass`
- checkMesh: `fail`
- boundary faces: `{'wing_upper': 96, 'wing_lower': 95, 'tip_left': 12288, 'tip_right': 12288, 'te_wall': 1, 'closure_wall': 0, 'farfield': 192}`
- max skewness: `22.3157`
- highly skew faces: `5`
- mesh-quality errors: `{'non-orthogonality > 65  degrees': 169, 'faces with face pyramid volume < 1e-13': 1, 'faces with face-decomposition tet quality < 1e-15': 40, 'faces with concavity > 80  degrees': 0, 'faces with skewness > 7   (internal) or 20  (boundary)': 0, 'faces with interpolation weights (0..1)  < 0.02': 40, 'faces with volume ratio of neighbour cells < 0.01': 0, 'faces with face twist < 0.02': 0, 'faces on cells with determinant < 0.001': 4467}`
- checkMesh summary lines:

```text
Checking topology...
Checking geometry...
  <<Writing 3 cells with high aspect ratio to set highAspectRatioCells
    Mesh non-orthogonality Max: 154.64 average: 9.61047
 ***Number of non-orthogonality errors: 21.
 ***Max skewness = 22.3157, 5 highly skew faces detected which may impair the quality of the results
Checking faces in error :
    non-orthogonality > 65  degrees                        : 169
    faces with skewness > 7   (internal) or 20  (boundary) : 0
Failed 7 mesh checks.
```
