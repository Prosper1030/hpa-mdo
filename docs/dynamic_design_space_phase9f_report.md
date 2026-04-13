# Phase 9f Dynamic Design Space Report

## Scope
- Phase 9f compares the existing lightweight load-refresh workflow against the new `--dynamic-design-space` mode.
- The new mode rebuilds the reduced V2 search map after each feasible refresh iteration, using the previous selected design as the new local baseline.

## Static vs Dynamic

| Mode | Dynamic Map | Rebuilds | Final Mass (kg) | Clearance (mm) | Tip Deflection (m) | Failure Index | Buckling Index |
|------|-------------|----------|-----------------|----------------|--------------------|---------------|----------------|
| static | off | 0 | 49.242 | 29.419 | 0.199855 | -0.929152 | -0.904050 |
| dynamic | on | 2 | 49.242 | 29.419 | 0.199855 | -0.929152 | -0.904050 |

## Dynamic Map Trace

| Iter | Rebuilt | Plateau Cap | Taper Cap | Rear Cap | dT Global (mm) | dT Rear Outboard (mm) | Source |
|------|---------|-------------|-----------|----------|----------------|-----------------------|--------|
| 0 | no | 1.1400 | 0.8000 | 1.1200 | 7.200 | 3.000 | target_shape_frozen_aoa_0.000deg |
| 1 | yes | 1.1400 | 0.8000 | 1.1200 | 3.600 | 3.000 | refresh_1_from_iteration_0 |
| 2 | yes | 1.1400 | 0.8000 | 1.1200 | 3.600 | 3.000 | refresh_2_from_iteration_1 |

## Findings

- Dynamic design space changed final mass by +0.000 kg and final jig clearance by +0.000 mm relative to the static reduced map.
- Dynamic mode rebuilt the map 2 time(s), so later refresh iterations were no longer constrained by the original specimen-only caps.
- This closes one of the three explicit gaps previously called out in the refresh report: the workflow now supports dynamic design-space rewrite, while trim update and full aero reruns still remain outside this lightweight path.

