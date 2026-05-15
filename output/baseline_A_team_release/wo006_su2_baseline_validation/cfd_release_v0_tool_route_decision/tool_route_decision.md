# WO-006 CFD Tool Route Decision

## Answers

1. Did OpenFOAM full-wing rescue route mesh and run?
   - `False`. Local blocker:
     `['openfoam_executables_missing']`.
2. Is CD_primary reasonable or still pathological?
   - OpenFOAM: `not evaluated`.
   - SU2 pressure-only primary CD: `None` with gate
     `fail`.
3. Are tip/TE/closure patches contaminating total CD?
   - OpenFOAM: `not evaluated`.
   - SU2 pressure-only diagnostic total CD:
     `None`.
4. Does full-wing SU2 pressure-only sanity pass?
   - `False`. Blockers:
     `['track_b_dual_face_area_aspect_ratio_pathological', 'track_b_dual_sub_volume_ratio_pathological', 'track_b_forces_breakdown_missing', 'track_b_primary_cd_missing', 'track_b_solver_not_completed']`.
5. Should we continue with A/B/C/D?
   - Recommendation: `B_mature_external_mesher_to_su2`.

## Stopped Route

Do not continue the Phase 3 custom partial-BL SU2 hybrid core-fill route. That
means no discrete PLC core-fill, no receiver/cycle/cap patching, no large
discrete-shell Gmsh reconstruction, no meshpy/TetGen retries on the same `.poly`,
no SU2 hybrid writer repairs, and no new R-series / Phase-3 topology patches.

## Engineering Read

The custom partial-BL core-fill route is stopped. In this checkout, OpenFOAM cannot run because the executable toolchain is missing; SU2 full-wing pressure-only is the only live local route-decision run.

Test-passing software artifacts here are route-decision evidence only. They do
not sign off 3D viscous drag, BL yPlus, load paths, or aircraft performance.
