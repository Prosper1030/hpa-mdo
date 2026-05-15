# Mesh Quality Report

## layers_0

- status: `pass`
- counts: `{'points': 251178, 'faces': 676740, 'internal_faces': 641658, 'cells': 212987}`
- checkMesh log: `/Volumes/Samsung SSD/hpa-mdo/output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0_phase3_delivery/openfoam_cases/layers_0/log.checkMesh`
- boundary patches: `{'FoamFile': {'type': None, 'nFaces': None, 'startFace': None}, 'farfield': {'type': 'patch', 'nFaces': 16896, 'startFace': 641658}, 'wing_upper': {'type': 'wall', 'nFaces': 9687, 'startFace': 658554}, 'wing_lower': {'type': 'wall', 'nFaces': 8383, 'startFace': 668241}, 'tip_left': {'type': 'wall', 'nFaces': 15, 'startFace': 676624}, 'tip_right': {'type': 'wall', 'nFaces': 15, 'startFace': 676639}, 'te_wall': {'type': 'wall', 'nFaces': 83, 'startFace': 676654}, 'closure_wall': {'type': 'wall', 'nFaces': 3, 'startFace': 676737}}`
- summary lines:
```text
Checking topology...
Checking geometry...
    Max aspect ratio = 6.91302 OK.
    Mesh non-orthogonality Max: 64.9101 average: 7.76538
    Non-orthogonality check OK.
 ***Max skewness = 6.08499, 4 highly skew faces detected which may impair the quality of the results
Checking faces in error :
    non-orthogonality >  65 degrees                        : 0
    faces with skewness >   7 (internal) or  20 (boundary) : 0
Failed 1 mesh checks.
```
- snappy/layer lines:
```text
$ openfoam -c 'cd /tmp/hpa_mdo_openfoam_phase3/openfoam_cases_layers_0 && snappyHexMesh -overwrite'
Case   : /tmp/hpa_mdo_openfoam_phase3/openfoam_cases_layers_0
1     wall                wing_upper
2     wall                wing_lower
--> FOAM Warning : Displacement (-0.000456797 3.94938e-05 -5.74973e-05) at mesh point 195157 coord (0.0305842 -17.0172 2.6295) points through the surrounding patch faces
--> FOAM Warning : Displacement (-0.000788444 -8.27717e-05 -0.000412532) at mesh point 195157 coord (0.0301274 -17.0172 2.62945) points through the surrounding patch faces
--> FOAM Warning : Displacement (-0.00173296 -0.0010225 -0.00167199) at mesh point 195157 coord (0.0293389 -17.0173 2.62903) points through the surrounding patch faces
--> FOAM Warning : Displacement (-0.000562456 -0.000766285 -0.00205976) at mesh point 195157 coord (0.027606 -17.0183 2.62736) points through the surrounding patch faces
--> FOAM Warning : Displacement (-0.000649199 -0.000587382 -0.00239584) at mesh point 243877 coord (0.0226627 -17.0557 2.63003) points through the surrounding patch faces
--> FOAM Warning : Displacement (-0.00342743 8.32449e-05 0.000288498) at mesh point 247225 coord (0.0077994 -17.0564 2.60328) points through the surrounding patch faces
--> FOAM Warning : Displacement (-0.00252318 -0.000150027 -0.000387182) at mesh point 247225 coord (0.00486291 -17.0563 2.60352) points through the surrounding patch faces
--> FOAM Warning : Displacement (-0.00312176 -0.000251516 -0.000668888) at mesh point 247225 coord (0.00486291 -17.0563 2.60352) points through the surrounding patch faces
--> FOAM Warning : Displacement (-0.00377986 -0.00037302 -0.00100719) at mesh point 247225 coord (0.00486291 -17.0563 2.60352) points through the surrounding patch faces
--> FOAM Warning : Displacement (-0.00449749 -0.000514538 -0.00140209) at mesh point 247225 coord (0.00486291 -17.0563 2.60352) points through the surrounding patch faces
```

## layers_3

- status: `fail`
- counts: `{'points': 272425, 'faces': 737796, 'internal_faces': 702714, 'cells': 232934}`
- checkMesh log: `/Volumes/Samsung SSD/hpa-mdo/output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0_phase3_delivery/openfoam_cases/layers_3/log.checkMesh`
- boundary patches: `{'FoamFile': {'type': None, 'nFaces': None, 'startFace': None}, 'farfield': {'type': 'patch', 'nFaces': 16896, 'startFace': 702714}, 'wing_upper': {'type': 'wall', 'nFaces': 9687, 'startFace': 719610}, 'wing_lower': {'type': 'wall', 'nFaces': 8383, 'startFace': 729297}, 'tip_left': {'type': 'wall', 'nFaces': 15, 'startFace': 737680}, 'tip_right': {'type': 'wall', 'nFaces': 15, 'startFace': 737695}, 'te_wall': {'type': 'wall', 'nFaces': 83, 'startFace': 737710}, 'closure_wall': {'type': 'wall', 'nFaces': 3, 'startFace': 737793}}`
- summary lines:
```text
Checking topology...
Checking geometry...
    Max aspect ratio = 32.1404 OK.
    Mesh non-orthogonality Max: 64.9701 average: 8.39223
    Non-orthogonality check OK.
 ***Max skewness = 6.08499, 4 highly skew faces detected which may impair the quality of the results
Checking faces in error :
    non-orthogonality >  65 degrees                        : 0
    faces with skewness >   7 (internal) or  20 (boundary) : 0
Failed 2 mesh checks.
```
- snappy/layer lines:
```text
$ openfoam -c 'cd /tmp/hpa_mdo_openfoam_phase3/openfoam_cases_layers_3 && snappyHexMesh -overwrite'
Case   : /tmp/hpa_mdo_openfoam_phase3/openfoam_cases_layers_3
1     wall                wing_upper
2     wall                wing_lower
--> FOAM Warning : Displacement (-0.000456797 3.94938e-05 -5.74973e-05) at mesh point 195157 coord (0.0305842 -17.0172 2.6295) points through the surrounding patch faces
--> FOAM Warning : Displacement (-0.000788444 -8.27717e-05 -0.000412532) at mesh point 195157 coord (0.0301274 -17.0172 2.62945) points through the surrounding patch faces
--> FOAM Warning : Displacement (-0.00173296 -0.0010225 -0.00167199) at mesh point 195157 coord (0.0293389 -17.0173 2.62903) points through the surrounding patch faces
--> FOAM Warning : Displacement (-0.000562456 -0.000766285 -0.00205976) at mesh point 195157 coord (0.027606 -17.0183 2.62736) points through the surrounding patch faces
--> FOAM Warning : Displacement (-0.000649199 -0.000587382 -0.00239584) at mesh point 243877 coord (0.0226627 -17.0557 2.63003) points through the surrounding patch faces
--> FOAM Warning : Displacement (-0.00342743 8.32449e-05 0.000288498) at mesh point 247225 coord (0.0077994 -17.0564 2.60328) points through the surrounding patch faces
--> FOAM Warning : Displacement (-0.00252318 -0.000150027 -0.000387182) at mesh point 247225 coord (0.00486291 -17.0563 2.60352) points through the surrounding patch faces
--> FOAM Warning : Displacement (-0.00312176 -0.000251516 -0.000668888) at mesh point 247225 coord (0.00486291 -17.0563 2.60352) points through the surrounding patch faces
--> FOAM Warning : Displacement (-0.00377986 -0.00037302 -0.00100719) at mesh point 247225 coord (0.00486291 -17.0563 2.60352) points through the surrounding patch faces
--> FOAM Warning : Displacement (-0.00449749 -0.000514538 -0.00140209) at mesh point 247225 coord (0.00486291 -17.0563 2.60352) points through the surrounding patch faces
Shrinking and layer addition phase
Handling cells with warped patch faces ...
patch      faces    layers avg thickness[m]
wing_upper 9687     3      0.0133    0.039
wing_lower 8383     3      0.0136    0.0384
Layer addition iteration 0
Layer addition iteration 1
Layer addition iteration 2
Layer addition iteration 3
Layer addition iteration 4
Layer addition iteration 5
Layer addition iteration 6
Layer addition iteration 7
Layer addition iteration 8
Layer addition iteration 9
Mesh with layers : cells:232934  faces:737796  points:272425
patch      faces        layers        overall thickness
wing_upper 9687     3        0.799    0.00924   20.1
wing_lower 8383     3        1.46     0.0189    42.1
Layers added in = 10.15 s.
```

## layers_8

- status: `pass`
- counts: `{'points': 278526, 'faces': 753996, 'internal_faces': 718914, 'cells': 238014}`
- checkMesh log: `/Volumes/Samsung SSD/hpa-mdo/output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0_phase3_delivery/openfoam_cases/layers_8/log.checkMesh`
- boundary patches: `{'FoamFile': {'type': None, 'nFaces': None, 'startFace': None}, 'farfield': {'type': 'patch', 'nFaces': 16896, 'startFace': 718914}, 'wing_upper': {'type': 'wall', 'nFaces': 9687, 'startFace': 735810}, 'wing_lower': {'type': 'wall', 'nFaces': 8383, 'startFace': 745497}, 'tip_left': {'type': 'wall', 'nFaces': 15, 'startFace': 753880}, 'tip_right': {'type': 'wall', 'nFaces': 15, 'startFace': 753895}, 'te_wall': {'type': 'wall', 'nFaces': 83, 'startFace': 753910}, 'closure_wall': {'type': 'wall', 'nFaces': 3, 'startFace': 753993}}`
- summary lines:
```text
Checking topology...
Checking geometry...
    Max aspect ratio = 26.0574 OK.
    Mesh non-orthogonality Max: 64.8869 average: 9.03251
    Non-orthogonality check OK.
 ***Max skewness = 6.08499, 2 highly skew faces detected which may impair the quality of the results
Checking faces in error :
    non-orthogonality >  65 degrees                        : 0
    faces with skewness >   7 (internal) or  20 (boundary) : 0
Failed 1 mesh checks.
```
- snappy/layer lines:
```text
$ openfoam -c 'cd /tmp/hpa_mdo_openfoam_phase3/openfoam_cases_layers_8 && snappyHexMesh -overwrite'
Case   : /tmp/hpa_mdo_openfoam_phase3/openfoam_cases_layers_8
1     wall                wing_upper
2     wall                wing_lower
--> FOAM Warning : Displacement (-0.000456797 3.94938e-05 -5.74973e-05) at mesh point 195157 coord (0.0305842 -17.0172 2.6295) points through the surrounding patch faces
--> FOAM Warning : Displacement (-0.000788444 -8.27717e-05 -0.000412532) at mesh point 195157 coord (0.0301274 -17.0172 2.62945) points through the surrounding patch faces
--> FOAM Warning : Displacement (-0.00173296 -0.0010225 -0.00167199) at mesh point 195157 coord (0.0293389 -17.0173 2.62903) points through the surrounding patch faces
--> FOAM Warning : Displacement (-0.000562456 -0.000766285 -0.00205976) at mesh point 195157 coord (0.027606 -17.0183 2.62736) points through the surrounding patch faces
--> FOAM Warning : Displacement (-0.000649199 -0.000587382 -0.00239584) at mesh point 243877 coord (0.0226627 -17.0557 2.63003) points through the surrounding patch faces
--> FOAM Warning : Displacement (-0.00342743 8.32449e-05 0.000288498) at mesh point 247225 coord (0.0077994 -17.0564 2.60328) points through the surrounding patch faces
--> FOAM Warning : Displacement (-0.00252318 -0.000150027 -0.000387182) at mesh point 247225 coord (0.00486291 -17.0563 2.60352) points through the surrounding patch faces
--> FOAM Warning : Displacement (-0.00312176 -0.000251516 -0.000668888) at mesh point 247225 coord (0.00486291 -17.0563 2.60352) points through the surrounding patch faces
--> FOAM Warning : Displacement (-0.00377986 -0.00037302 -0.00100719) at mesh point 247225 coord (0.00486291 -17.0563 2.60352) points through the surrounding patch faces
--> FOAM Warning : Displacement (-0.00449749 -0.000514538 -0.00140209) at mesh point 247225 coord (0.00486291 -17.0563 2.60352) points through the surrounding patch faces
Shrinking and layer addition phase
Handling cells with warped patch faces ...
patch      faces    layers avg thickness[m]
wing_upper 9687     8      0.00693   0.071
wing_lower 8383     8      0.00725   0.0699
Layer addition iteration 0
Layer addition iteration 1
Layer addition iteration 2
Layer addition iteration 3
Layer addition iteration 4
Layer addition iteration 5
Layer addition iteration 6
Layer addition iteration 7
Mesh with layers : cells:238014  faces:753996  points:278526
patch      faces        layers        overall thickness
wing_upper 9687     8        1.08     0.0211    25.4
wing_lower 8383     8        1.74     0.0374    45.7
Layers added in = 10.47 s.
```
