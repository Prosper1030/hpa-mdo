# Mesh Quality Ladder Report

## layers_0

- acceptance: `accepted` []
- cells: `212987`
- points: `251178`
- max skewness: `6.08499`
- custom mesh-quality error count: `0`
- checkMesh quality basis: `pass_with_smoke_skew_warning`
- non-orthogonality / skew summary:
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
- layer coverage:
```json
{
  "status": "missing_layer_lines",
  "log": "/Volumes/Samsung SSD/hpa-mdo/output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0_phase3_openfoam_ladder/openfoam_cases/layers_0/log.snappyHexMesh",
  "patches": {},
  "addition_iterations": []
}
```

## layers_3

- acceptance: `rejected` ['mesh_quality_not_smoke_acceptable', 'custom_mesh_quality_errors_present']
- cells: `232934`
- points: `272425`
- max skewness: `6.08499`
- custom mesh-quality error count: `2`
- checkMesh quality basis: `failed_checkmesh`
- non-orthogonality / skew summary:
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
- layer coverage:
```json
{
  "status": "available",
  "log": "/Volumes/Samsung SSD/hpa-mdo/output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0_phase3_openfoam_ladder/openfoam_cases/layers_3/log.snappyHexMesh",
  "patches": {
    "wing_upper": {
      "faces": 9687,
      "reported_layers": 3.0,
      "reported_values": [
        0.799,
        0.00924,
        20.1
      ],
      "source": "final snappyHexMesh layer table"
    },
    "wing_lower": {
      "faces": 8383,
      "reported_layers": 3.0,
      "reported_values": [
        1.46,
        0.0189,
        42.1
      ],
      "source": "final snappyHexMesh layer table"
    }
  },
  "addition_iterations": [
    {
      "added_cells": 43487,
      "candidate_cells": 54210,
      "percent": 80.2195
    },
    {
      "added_cells": 23088,
      "candidate_cells": 54210,
      "percent": 42.5899
    },
    {
      "added_cells": 20741,
      "candidate_cells": 54210,
      "percent": 38.2605
    },
    {
      "added_cells": 20162,
      "candidate_cells": 54210,
      "percent": 37.1924
    },
    {
      "added_cells": 20072,
      "candidate_cells": 54210,
      "percent": 37.0264
    },
    {
      "added_cells": 20009,
      "candidate_cells": 54210,
      "percent": 36.9102
    },
    {
      "added_cells": 19985,
      "candidate_cells": 54210,
      "percent": 36.8659
    },
    {
      "added_cells": 19963,
      "candidate_cells": 54210,
      "percent": 36.8253
    },
    {
      "added_cells": 19955,
      "candidate_cells": 54210,
      "percent": 36.8106
    },
    {
      "added_cells": 19947,
      "candidate_cells": 54210,
      "percent": 36.7958
    }
  ]
}
```

## layers_8

- acceptance: `accepted` []
- cells: `238014`
- points: `278526`
- max skewness: `6.08499`
- custom mesh-quality error count: `0`
- checkMesh quality basis: `pass_with_smoke_skew_warning`
- non-orthogonality / skew summary:
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
- layer coverage:
```json
{
  "status": "available",
  "log": "/Volumes/Samsung SSD/hpa-mdo/output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0_phase3_openfoam_ladder/openfoam_cases/layers_8/log.snappyHexMesh",
  "patches": {
    "wing_upper": {
      "faces": 9687,
      "reported_layers": 8.0,
      "reported_values": [
        1.08,
        0.0211,
        25.4
      ],
      "source": "final snappyHexMesh layer table"
    },
    "wing_lower": {
      "faces": 8383,
      "reported_layers": 8.0,
      "reported_values": [
        1.74,
        0.0374,
        45.7
      ],
      "source": "final snappyHexMesh layer table"
    }
  },
  "addition_iterations": [
    {
      "added_cells": 59015,
      "candidate_cells": 144560,
      "percent": 40.8239
    },
    {
      "added_cells": 29697,
      "candidate_cells": 144560,
      "percent": 20.543
    },
    {
      "added_cells": 26607,
      "candidate_cells": 144560,
      "percent": 18.4055
    },
    {
      "added_cells": 25527,
      "candidate_cells": 144560,
      "percent": 17.6584
    },
    {
      "added_cells": 25201,
      "candidate_cells": 144560,
      "percent": 17.4329
    },
    {
      "added_cells": 25094,
      "candidate_cells": 144560,
      "percent": 17.3589
    },
    {
      "added_cells": 25055,
      "candidate_cells": 144560,
      "percent": 17.3319
    },
    {
      "added_cells": 25027,
      "candidate_cells": 144560,
      "percent": 17.3125
    }
  ]
}
```

## layers_12

- acceptance: `rejected` ['force_window_not_stable_enough']
- cells: `240218`
- points: `281033`
- max skewness: `6.08499`
- custom mesh-quality error count: `0`
- checkMesh quality basis: `pass_with_smoke_skew_warning`
- non-orthogonality / skew summary:
```text
Checking topology...
Checking geometry...
    Max aspect ratio = 15.3931 OK.
    Mesh non-orthogonality Max: 64.935 average: 9.45567
    Non-orthogonality check OK.
 ***Max skewness = 6.08499, 2 highly skew faces detected which may impair the quality of the results
Checking faces in error :
    non-orthogonality >  65 degrees                        : 0
    faces with skewness >   7 (internal) or  20 (boundary) : 0
Failed 1 mesh checks.
```
- layer coverage:
```json
{
  "status": "available",
  "log": "/Volumes/Samsung SSD/hpa-mdo/output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0_phase3_openfoam_ladder/openfoam_cases/layers_12/log.snappyHexMesh",
  "patches": {
    "wing_upper": {
      "faces": 9687,
      "reported_layers": 12.0,
      "reported_values": [
        1.15,
        0.0283,
        27.6
      ],
      "source": "final snappyHexMesh layer table"
    },
    "wing_lower": {
      "faces": 8383,
      "reported_layers": 12.0,
      "reported_values": [
        1.92,
        0.0483,
        47.7
      ],
      "source": "final snappyHexMesh layer table"
    }
  },
  "addition_iterations": [
    {
      "added_cells": 56150,
      "candidate_cells": 216840,
      "percent": 25.8947
    },
    {
      "added_cells": 30524,
      "candidate_cells": 216840,
      "percent": 14.0767
    },
    {
      "added_cells": 27893,
      "candidate_cells": 216840,
      "percent": 12.8634
    },
    {
      "added_cells": 27303,
      "candidate_cells": 216840,
      "percent": 12.5913
    },
    {
      "added_cells": 27237,
      "candidate_cells": 216840,
      "percent": 12.5609
    },
    {
      "added_cells": 27231,
      "candidate_cells": 216840,
      "percent": 12.5581
    }
  ]
}
```

## layers_16

- acceptance: `accepted` []
- cells: `241143`
- points: `281984`
- max skewness: `6.08499`
- custom mesh-quality error count: `0`
- checkMesh quality basis: `pass_with_smoke_skew_warning`
- non-orthogonality / skew summary:
```text
Checking topology...
Checking geometry...
    Max aspect ratio = 13.4588 OK.
    Mesh non-orthogonality Max: 64.8815 average: 9.81373
    Non-orthogonality check OK.
 ***Max skewness = 6.08499, 2 highly skew faces detected which may impair the quality of the results
Checking faces in error :
    non-orthogonality >  65 degrees                        : 0
    faces with skewness >   7 (internal) or  20 (boundary) : 0
Failed 1 mesh checks.
```
- layer coverage:
```json
{
  "status": "available",
  "log": "/Volumes/Samsung SSD/hpa-mdo/output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0_phase3_openfoam_ladder/openfoam_cases/layers_16/log.snappyHexMesh",
  "patches": {
    "wing_upper": {
      "faces": 9687,
      "reported_layers": 16.0,
      "reported_values": [
        1.16,
        0.0323,
        27.0
      ],
      "source": "final snappyHexMesh layer table"
    },
    "wing_lower": {
      "faces": 8383,
      "reported_layers": 16.0,
      "reported_values": [
        2.02,
        0.0578,
        49.0
      ],
      "source": "final snappyHexMesh layer table"
    }
  },
  "addition_iterations": [
    {
      "added_cells": 54250,
      "candidate_cells": 289120,
      "percent": 18.7638
    },
    {
      "added_cells": 31856,
      "candidate_cells": 289120,
      "percent": 11.0183
    },
    {
      "added_cells": 28870,
      "candidate_cells": 289120,
      "percent": 9.98547
    },
    {
      "added_cells": 28339,
      "candidate_cells": 289120,
      "percent": 9.80181
    },
    {
      "added_cells": 28156,
      "candidate_cells": 289120,
      "percent": 9.73852
    }
  ]
}
```

## layers_24

- acceptance: `accepted` []
- cells: `239988`
- points: `280664`
- max skewness: `6.08499`
- custom mesh-quality error count: `0`
- checkMesh quality basis: `pass_with_smoke_skew_warning`
- non-orthogonality / skew summary:
```text
Checking topology...
Checking geometry...
    Max aspect ratio = 16.1845 OK.
    Mesh non-orthogonality Max: 64.833 average: 10.0937
    Non-orthogonality check OK.
 ***Max skewness = 6.08499, 2 highly skew faces detected which may impair the quality of the results
Checking faces in error :
    non-orthogonality >  65 degrees                        : 0
    faces with skewness >   7 (internal) or  20 (boundary) : 0
Failed 1 mesh checks.
```
- layer coverage:
```json
{
  "status": "available",
  "log": "/Volumes/Samsung SSD/hpa-mdo/output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0_phase3_openfoam_ladder/openfoam_cases/layers_24/log.snappyHexMesh",
  "patches": {
    "wing_upper": {
      "faces": 9687,
      "reported_layers": 24.0,
      "reported_values": [
        1.02,
        0.0313,
        23.6
      ],
      "source": "final snappyHexMesh layer table"
    },
    "wing_lower": {
      "faces": 8383,
      "reported_layers": 24.0,
      "reported_values": [
        2.04,
        0.0642,
        49.1
      ],
      "source": "final snappyHexMesh layer table"
    }
  },
  "addition_iterations": [
    {
      "added_cells": 51591,
      "candidate_cells": 433680,
      "percent": 11.8961
    },
    {
      "added_cells": 31645,
      "candidate_cells": 433680,
      "percent": 7.29685
    },
    {
      "added_cells": 28047,
      "candidate_cells": 433680,
      "percent": 6.46721
    },
    {
      "added_cells": 27470,
      "candidate_cells": 433680,
      "percent": 6.33416
    },
    {
      "added_cells": 27191,
      "candidate_cells": 433680,
      "percent": 6.26983
    },
    {
      "added_cells": 27057,
      "candidate_cells": 433680,
      "percent": 6.23893
    },
    {
      "added_cells": 27019,
      "candidate_cells": 433680,
      "percent": 6.23017
    },
    {
      "added_cells": 27011,
      "candidate_cells": 433680,
      "percent": 6.22833
    },
    {
      "added_cells": 27001,
      "candidate_cells": 433680,
      "percent": 6.22602
    }
  ]
}
```

## layers_12_low_yplus_factor_0p44

- acceptance: `rejected` ['solver_failed', 'force_window_not_stable_enough', 'yplus_report_missing']
- cells: `233448`
- points: `273415`
- max skewness: `6.08499`
- custom mesh-quality error count: `0`
- checkMesh quality basis: `pass_with_smoke_skew_warning`
- non-orthogonality / skew summary:
```text
Checking topology...
Checking geometry...
    Max aspect ratio = 27.8201 OK.
    Mesh non-orthogonality Max: 64.9922 average: 8.38959
    Non-orthogonality check OK.
 ***Max skewness = 6.08499, 4 highly skew faces detected which may impair the quality of the results
Checking faces in error :
    non-orthogonality >  65 degrees                        : 0
    faces with skewness >   7 (internal) or  20 (boundary) : 0
Failed 1 mesh checks.
```
- layer coverage:
```json
{
  "status": "available",
  "log": "/Volumes/Samsung SSD/hpa-mdo/output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0_phase3_openfoam_ladder/openfoam_cases/layers_12_low_yplus_factor_0p44/log.snappyHexMesh",
  "patches": {
    "wing_upper": {
      "faces": 9687,
      "reported_layers": 12.0,
      "reported_values": [
        0.78,
        0.00816,
        18.1
      ],
      "source": "final snappyHexMesh layer table"
    },
    "wing_lower": {
      "faces": 8383,
      "reported_layers": 12.0,
      "reported_values": [
        1.54,
        0.0181,
        41.3
      ],
      "source": "final snappyHexMesh layer table"
    }
  },
  "addition_iterations": [
    {
      "added_cells": 61499,
      "candidate_cells": 216840,
      "percent": 28.3615
    },
    {
      "added_cells": 23193,
      "candidate_cells": 216840,
      "percent": 10.6959
    },
    {
      "added_cells": 21072,
      "candidate_cells": 216840,
      "percent": 9.71776
    },
    {
      "added_cells": 20639,
      "candidate_cells": 216840,
      "percent": 9.51808
    },
    {
      "added_cells": 20534,
      "candidate_cells": 216840,
      "percent": 9.46966
    },
    {
      "added_cells": 20515,
      "candidate_cells": 216840,
      "percent": 9.46089
    },
    {
      "added_cells": 20485,
      "candidate_cells": 216840,
      "percent": 9.44706
    },
    {
      "added_cells": 20477,
      "candidate_cells": 216840,
      "percent": 9.44337
    },
    {
      "added_cells": 20469,
      "candidate_cells": 216840,
      "percent": 9.43968
    },
    {
      "added_cells": 20461,
      "candidate_cells": 216840,
      "percent": 9.43599
    }
  ]
}
```

## layers_8_refined_surface_plus1

- acceptance: `rejected` ['mesh_quality_not_smoke_acceptable', 'custom_mesh_quality_errors_present']
- cells: `514157`
- points: `631238`
- max skewness: `5.4911`
- custom mesh-quality error count: `8`
- checkMesh quality basis: `failed_checkmesh`
- non-orthogonality / skew summary:
```text
Checking topology...
Checking geometry...
    Max aspect ratio = 18.0036 OK.
    Mesh non-orthogonality Max: 64.9977 average: 11.5371
    Non-orthogonality check OK.
 ***Max skewness = 5.4911, 15 highly skew faces detected which may impair the quality of the results
Checking faces in error :
    non-orthogonality >  65 degrees                        : 0
    faces with skewness >   7 (internal) or  20 (boundary) : 0
Failed 2 mesh checks.
```
- layer coverage:
```json
{
  "status": "available",
  "log": "/Volumes/Samsung SSD/hpa-mdo/output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0_phase3_openfoam_ladder/openfoam_cases/layers_8_refined_surface_plus1/log.snappyHexMesh",
  "patches": {
    "wing_upper": {
      "faces": 37199,
      "reported_layers": 8.0,
      "reported_values": [
        1.7,
        0.0169,
        39.4
      ],
      "source": "final snappyHexMesh layer table"
    },
    "wing_lower": {
      "faces": 32469,
      "reported_layers": 8.0,
      "reported_values": [
        2.06,
        0.0229,
        53.7
      ],
      "source": "final snappyHexMesh layer table"
    }
  },
  "addition_iterations": [
    {
      "added_cells": 347688,
      "candidate_cells": 557344,
      "percent": 62.383
    },
    {
      "added_cells": 149115,
      "candidate_cells": 557344,
      "percent": 26.7546
    },
    {
      "added_cells": 136920,
      "candidate_cells": 557344,
      "percent": 24.5665
    },
    {
      "added_cells": 132679,
      "candidate_cells": 557344,
      "percent": 23.8056
    },
    {
      "added_cells": 130768,
      "candidate_cells": 557344,
      "percent": 23.4627
    },
    {
      "added_cells": 130211,
      "candidate_cells": 557344,
      "percent": 23.3628
    },
    {
      "added_cells": 129995,
      "candidate_cells": 557344,
      "percent": 23.324
    },
    {
      "added_cells": 129949,
      "candidate_cells": 557344,
      "percent": 23.3158
    }
  ]
}
```

## layers_8_kOmegaSST_same_mesh

- acceptance: `rejected` ['force_window_not_stable_enough']
- cells: `238014`
- points: `278526`
- max skewness: `6.08499`
- custom mesh-quality error count: `0`
- checkMesh quality basis: `pass_with_smoke_skew_warning`
- non-orthogonality / skew summary:
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
- layer coverage:
```json
{
  "status": "available",
  "log": "/Volumes/Samsung SSD/hpa-mdo/output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0_phase3_openfoam_ladder/openfoam_cases/layers_8/log.snappyHexMesh",
  "patches": {
    "wing_upper": {
      "faces": 9687,
      "reported_layers": 8.0,
      "reported_values": [
        1.08,
        0.0211,
        25.4
      ],
      "source": "final snappyHexMesh layer table"
    },
    "wing_lower": {
      "faces": 8383,
      "reported_layers": 8.0,
      "reported_values": [
        1.74,
        0.0374,
        45.7
      ],
      "source": "final snappyHexMesh layer table"
    }
  },
  "addition_iterations": [
    {
      "added_cells": 59015,
      "candidate_cells": 144560,
      "percent": 40.8239
    },
    {
      "added_cells": 29697,
      "candidate_cells": 144560,
      "percent": 20.543
    },
    {
      "added_cells": 26607,
      "candidate_cells": 144560,
      "percent": 18.4055
    },
    {
      "added_cells": 25527,
      "candidate_cells": 144560,
      "percent": 17.6584
    },
    {
      "added_cells": 25201,
      "candidate_cells": 144560,
      "percent": 17.4329
    },
    {
      "added_cells": 25094,
      "candidate_cells": 144560,
      "percent": 17.3589
    },
    {
      "added_cells": 25055,
      "candidate_cells": 144560,
      "percent": 17.3319
    },
    {
      "added_cells": 25027,
      "candidate_cells": 144560,
      "percent": 17.3125
    }
  ]
}
```
