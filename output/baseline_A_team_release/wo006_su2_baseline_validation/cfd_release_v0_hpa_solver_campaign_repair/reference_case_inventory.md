# Reference Case Inventory

Verdict: `repo_reference_found_but_user_supplied_cd_exact_value_not_present`

- case path: `/Volumes/Samsung SSD/hpa-mdo/output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0_true_baseline_solver_stability/openfoam_cases/fullwing_mirror`
- role: `successful_reference_repo_artifact`
- cells: `1996800`
- bounding box min: `[-12.53532111, -17.166143, -13.6170243]`
- bounding box max: `[12.527466, 17.166143, 11.6207954]`
- Sref/Aref: `3.342006e+01`
- Cref/lRef: `1.003722e+00`
- magUInf: `6.500000e+00`
- rhoInf: `1.225`
- dragDir: `(9.999951e-01 0.000000e+00 3.141587e-03)`
- liftDir: `(-3.141587e-03 0.000000e+00 9.999951e-01)`
- inlet/farfield U: `uniform (6.49996792 0 0.0204203187)` / `uniform (6.49996792 0 0.0204203187)`
- turbulence model: `RAS` / `SpalartAllmaras`
- transport nu: `1.4607e-05`
- primary patches: `airfoil_upper airfoil_lower`
- total patches: `airfoil_upper airfoil_lower physical_tip_left physical_tip_right te_wall`
- iteration count: `500.0`
- final primary CD/CL/CmPitch: `0.03276165` / `1.133291` / `-0.1239779`
- final-100 primary drift under current gate: `{"Cd": {"last": 0.03276165, "rel_span": 0.0011472390667919775}, "Cl": {"last": 1.133291, "rel_span": 0.007112652621749207}, "CmPitch": {"last": -0.1239779, "rel_span": 0.01198243554997831}}`
- derived total_physical = primary + te_wall CD/CL: `0.0327769065` / `1.1332892391440001`

Search result: the exact user-supplied `CD_primary≈0.031817`,
`CD_total_physical≈0.031823`, `CL_primary≈1.130726` triple is not present
as an OpenFOAM force-history artifact in this checkout. The traceable
successful OpenFOAM reference with force history is the 500-iteration
`fullwing_mirror` case: `CD_primary=0.03276165`, `CL_primary=1.133291`.
The `0.031823` value appears in the drag/power audit as a user-supplied
OpenFOAM-like physical CD, not as the last row of a stored forceCoeffs file.

## Patch Inventory

| patch | type | nFaces | startFace | area_m2 |
|---|---|---:|---:|---:|
| `airfoil_upper` | `wall` | 14976 | 5946400 | 35.40458661450818 |
| `airfoil_lower` | `wall` | 14976 | 5961376 | 34.15232769345717 |
| `te_wall` | `wall` | 1248 | 5976352 | 0.01590426456517972 |
| `outlet` | `patch` | 1248 | 5977600 | 703.6576786172784 |
| `farfield` | `patch` | 29952 | 5978848 | 1645.4189616027772 |
| `physical_tip_right` | `wall` | 12800 | 6008800 | 124.13279721269896 |
| `physical_tip_left` | `wall` | 12800 | 6021600 | 124.13279721269896 |

## OpenFOAM Dictionaries

- controlDict startFrom/endTime/writeInterval: `latestTime` / `500` / `100`
- fvSchemes hash: `6022819ae776e286`
- fvSolution hash: `ee30236d999cdf9b`
- boundary hash: `0b1146e031a59f24`
