# Baseline Debug Mesh Report

- case status: `custom_mesh_quality_failed`
- case directory: `output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0_structured_hexa_verification/openfoam_cases/debug_attempt_06_section_scaled_far20`
- custom mesh status: `fail`
- nodes: `173266`
- cells: `168960`
- faces: `511104`
- boundary face counts: `{'wing_upper': 1536, 'wing_lower': 1504, 'tip_left': 576, 'tip_right': 576, 'te_wall': 28, 'closure_wall': 4, 'farfield': 4224}`
- first layer height: `5e-05` m
- min signed volume: `-1.4218089475855606`
- max signed volume: `23.459023087053062`
- volume percentiles: `{'min': -1.4218089475855606, 'p05': 1.27923780329446e-09, 'p50': 2.4081556794444233e-06, 'p95': 0.4390735530246003, 'max': 23.459023087053062}`
- aspect-ratio proxy percentiles: `{'min': 1.1421544875002878, 'p05': 3.531017526254968, 'p50': 269.0295158681335, 'p95': 25162.794003012248, 'max': 206207.9302058359}`
- checkMesh status: `None`
- checkMesh quality basis: `None`
- checkMesh counts: `None`

```text
not available
```

## Bounded Debug Attempts

| attempt | mapping | smooth | farfield chords | custom status | checkMesh | non-positive custom volumes | min signed volume |
|---|---|---:|---:|---|---|---:|---:|
| `debug_attempt_01_normal_smooth4_far20` | `normal` | 4 | 20.0 | `fail` | `None` | 496 | `-0.610645246` |
| `debug_attempt_02_normal_smooth0_far20` | `normal` | 0 | 20.0 | `fail` | `None` | 458 | `-0.805162953` |
| `debug_attempt_03_normal_smooth8_far20` | `normal` | 8 | 20.0 | `fail` | `None` | 551 | `-0.532865567` |
| `debug_attempt_04_generic_radial_smooth2_far20` | `generic_radial` | 2 | 20.0 | `pass` | `fail` | 0 | `9.59408038e-13` |
| `debug_attempt_05_generic_radial_smooth4_far20` | `generic_radial` | 4 | 20.0 | `fail` | `None` | 3 | `-0.0061302654` |
| `debug_attempt_06_section_scaled_far20` | `section_scaled` | 4 | 20.0 | `fail` | `None` | 603 | `-1.42180895` |
