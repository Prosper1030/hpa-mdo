# Fine Solver Report

Verdict: `fine_2000_accepted_by_force_window`

- case: `/Volumes/Samsung SSD/hpa-mdo/output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0_hpa_solver_campaign_repair/fine_current_setup/openfoam_cases/fine/fullwing_artificial_tip_symmetry`
- setup lock: same locked geometry family, AoA, rho, V, turbulence model, boundary-condition convention, artificial-tip closure treatment, force definitions, fvSchemes/fvSolution, potentialFoam startup, and latest-time simpleFoam continuation as Coarse and Medium.
- full-wing cells: `6090240`; maxNonOrtho `82.9339`; maxSkew `3.46267`; strict checkMesh clean `True`
- final primary row: Time `2000.0`, CD `0.03320877`, CL `1.160934`, CmPitch `-0.1322822`
- final total_physical row: CD `0.03326556`, CL `1.160927`, CmPitch `-0.1322138`
- residual status: `available`, not diverging: `True`
- continuity final-200 max abs global: `3.13076e-08`
- pressure field: `{'status': 'available', 'finite': True, 'count': 6090240, 'min': -38.5329, 'max': 23.0129}`
- velocity field: `{'status': 'available', 'finite': True, 'count': 6090240, 'component_min': [-1.38793, -1.9334, -2.4589], 'component_max': [10.3249, 1.9334, 7.53042], 'mag_min': 0.0013005079552840114, 'mag_max': 10.582260511381724}`
- yPlus status: `available`

## Solver Segments

| segment | returncode | timed out | runaway guard | elapsed_s | max RSS bytes | log |
|---|---:|---|---|---:|---:|---|
| `initial_500` | `0` | `False` | `False` | `10706.02` | `7654244352` | `output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0_hpa_solver_campaign_repair/fine_current_setup/openfoam_cases/fine/fullwing_artificial_tip_symmetry/log.simpleFoam_500` |
| `continue_1000` | `0` | `False` | `False` | `10983.83` | `7557857280` | `output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0_hpa_solver_campaign_repair/fine_current_setup/openfoam_cases/fine/fullwing_artificial_tip_symmetry/log.simpleFoam_1000` |
| `continue_1500` | `0` | `False` | `False` | `10446.53` | `7651983360` | `output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0_hpa_solver_campaign_repair/fine_current_setup/openfoam_cases/fine/fullwing_artificial_tip_symmetry/log.simpleFoam_1500` |
| `continue_2000` | `0` | `False` | `False` | `8531.73` | `7661715456` | `output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0_hpa_solver_campaign_repair/fine_current_setup/openfoam_cases/fine/fullwing_artificial_tip_symmetry/log.simpleFoam_2000` |

## Residuals

| field | count | first initial | last initial | max initial | first final | last final |
|---|---:|---:|---:|---:|---:|---:|
| `Ux` | 2500 | 0.600491 | 3.78955e-06 | 0.600491 | 0.0205495 | 1.55855e-07 |
| `Uy` | 2500 | 0.135394 | 3.4429e-05 | 0.170247 | 0.00377242 | 1.42869e-06 |
| `Uz` | 2500 | 0.172331 | 1.407e-05 | 0.232208 | 0.00433315 | 6.96522e-07 |
| `p` | 7500 | 0.247563 | 5.88273e-06 | 0.496673 | 0.023021 | 8.74674e-07 |
| `nuTilda` | 2500 | 1.0 | 0.000130027 | 1.0 | 0.0579651 | 3.94305e-06 |

## Pressure / Viscous Split

Source: numerically latest OpenFOAM `forces_*/*/force.dat` row at Time `2000`; pressure + viscous equals the corresponding forceCoeffs total within rounding.

| group | Time | CD_pressure | CD_viscous | CL_pressure | CL_viscous |
|---|---:|---:|---:|---:|---:|
| `primary` | 2000.0 | 0.02289776540555616 | 0.010311002938930494 | 1.1603729006808738 | 0.0005617271036593883 |
| `total_physical` | 2000.0 | 0.02295001410767383 | 0.010315548220166119 | 1.1603681114257476 | 0.0005587680163683976 |
| `te_wall` | 2000.0 | 5.224553546304786e-05 | 4.546056072012514e-06 | -4.788763010035349e-06 | -2.9590457866698254e-06 |
