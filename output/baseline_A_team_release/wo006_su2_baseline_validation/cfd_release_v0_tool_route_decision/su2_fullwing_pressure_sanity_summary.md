# Track B - SU2 Full-Wing Pressure-Only Sanity

Status: `fail`

## Result

- case dir: `/Volumes/Samsung SSD/hpa-mdo/output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0_tool_route_decision/track_b_su2_fullwing_pressure`
- mesh cell count: `4043`
- marker audit: `pass`
- SU2 run status: `failed`
- dual quality: min orthogonality `12.4457`, max
  face-area aspect ratio `36586.8`, max
  sub-volume ratio `1453580.0`
- primary CD: `None`
- primary CL: `None`
- total CD: `None`
- previous half-wing Phase 2 pressure-only CD: `0.0177873`
- blockers: `['track_b_dual_face_area_aspect_ratio_pathological', 'track_b_dual_sub_volume_ratio_pathological', 'track_b_forces_breakdown_missing', 'track_b_primary_cd_missing', 'track_b_solver_not_completed']`
- warnings: `[]`

## Diagnostic Patch Forces

- tip_left: CD `None`, CL `None`
- tip_right: CD `None`, CL `None`
- te_wall: CD `None`, CL `None`
- closure_wall: CD `None`, CL `None`

## Engineering Boundary

This run checks full-wing geometry/reference/marker/force convention only. It is
pressure-only/slip-wall evidence, not wall-resolved viscous CD, yPlus, grid
ladder, or final aircraft drag truth.
