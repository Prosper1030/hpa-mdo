# Medium Solver Report

Verdict: `medium_2000_accepted_by_force_window`

- case: `/Volumes/Samsung SSD/hpa-mdo/output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0_hpa_solver_campaign_repair/medium_current_setup/openfoam_cases/medium/fullwing_artificial_tip_symmetry`
- setup lock: same locked geometry family, AoA, rho, V, turbulence model, boundary-condition convention, artificial-tip closure treatment, force definitions, fvSchemes/fvSolution, potentialFoam startup, and latest-time simpleFoam continuation as Coarse.
- full-wing cells: `3136000`; maxNonOrtho `83.135`; maxSkew `3.45693`; strict checkMesh clean `True`
- final primary row: Time `2000.0`, CD `0.03369494`, CL `1.158639`, CmPitch `-0.1313859`
- final total_physical row: CD `0.03375281`, CL `1.158631`, CmPitch `-0.131313`
- residual status: `available`, not diverging: `True`
- continuity final-200 max abs global: `4.18075e-08`
- pressure field: `{'status': 'available', 'finite': True, 'count': 3136000, 'min': -37.7765, 'max': 24.7913}`
- velocity field: `{'status': 'available', 'finite': True, 'count': 3136000, 'component_min': [-1.5638, -1.89604, -2.44923], 'component_max': [10.2868, 1.89603, 7.32655], 'mag_min': 0.0005236207268051944, 'mag_max': 10.553969283024088}`
- yPlus status: `available`

## Solver Segments

| segment | returncode | timed out | runaway guard | elapsed_s | log |
|---|---:|---|---|---:|---|
| `initial_500` | `0` | `False` | `False` | `5376.208568166941` | `/Volumes/Samsung SSD/hpa-mdo/output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0_hpa_solver_campaign_repair/medium_current_setup/openfoam_cases/medium/fullwing_artificial_tip_symmetry/log.simpleFoam_200` |
| `continue_1000` | `0` | `False` | `False` | `None` | `output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0_hpa_solver_campaign_repair/medium_current_setup/openfoam_cases/medium/fullwing_artificial_tip_symmetry/log.simpleFoam_1000` |
| `continue_1500` | `0` | `False` | `False` | `None` | `output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0_hpa_solver_campaign_repair/medium_current_setup/openfoam_cases/medium/fullwing_artificial_tip_symmetry/log.simpleFoam_1500` |
| `continue_2000` | `0` | `False` | `False` | `None` | `output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0_hpa_solver_campaign_repair/medium_current_setup/openfoam_cases/medium/fullwing_artificial_tip_symmetry/log.simpleFoam_2000` |

## Residuals

| field | count | first initial | last initial | max initial | first final | last final |
|---|---:|---:|---:|---:|---:|---:|
| `Ux` | 2000 | 0.55595 | 4.00548e-06 | 0.55595 | 0.0223301 | 1.5554e-07 |
| `Uy` | 2000 | 0.114765 | 4.5283e-05 | 0.161311 | 0.00327906 | 1.84625e-06 |
| `Uz` | 2000 | 0.14747 | 1.73099e-05 | 0.235377 | 0.0129824 | 8.40546e-07 |
| `p` | 6000 | 0.31126 | 8.66149e-06 | 0.483202 | 0.0257415 | 9.79757e-07 |
| `nuTilda` | 2000 | 1.0 | 0.000228124 | 1.0 | 0.0566967 | 6.76049e-06 |

## Pressure / Viscous Split

Source: numerically latest OpenFOAM `forces_*/*/force.dat` row at Time `2000`; pressure + viscous equals the corresponding forceCoeffs total within rounding.

| group | Time | CD_pressure | CD_viscous | CL_pressure | CL_viscous |
|---|---:|---:|---:|---:|---:|
| `primary` | 2000.0 | 0.023316549395616174 | 0.010378388454030791 | 1.1580809990787524 | 0.0005576684695090854 |
| `total_physical` | 2000.0 | 0.02336966529738376 | 0.010383138678447588 | 1.158076207099229 | 0.0005547991592772311 |
| `te_wall` | 2000.0 | 5.3118033215189925e-05 | 4.749863759822241e-06 | -4.812822341911211e-06 | -2.8692778793176332e-06 |
