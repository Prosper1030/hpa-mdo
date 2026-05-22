# Grid-Independence Aero Comparison

Verdict: `medium_fine_grid_converged_for_locked_OpenFOAM_wing_drag`

All three rungs use the locked WO-006 HPA setup: same geometry family, AoA, rho, V, turbulence model, boundary conditions, artificial closure treatment, force definitions, fvSchemes/fvSolution, and potentialFoam/simpleFoam startup workflow.

## Final Coefficients

| grid | cells | CL_primary | CD_primary | CD_total_physical | CmPitch | yPlus mean/p95/max | force window accepted |
|---|---:|---:|---:|---:|---:|---|---|
| coarse | 1335552 | 1.159865 | 0.03565319 | 0.03571427 | -0.1309061 | 0.825 / 1.577 / 3.129 | `True` |
| medium | 3136000 | 1.158639 | 0.03369494 | 0.03375281 | -0.1313859 | 0.811 / 1.547 / 3.137 | `True` |
| fine | 6090240 | 1.160934 | 0.03320877 | 0.03326556 | -0.1322822 | 0.803 / 1.523 / 3.122 | `True` |

## Final-100 Force-Window Drift

| grid | CD_total_physical | CD_primary | CL_primary | CmPitch |
|---|---:|---:|---:|---:|
| coarse | 0.265% | 0.261% | 0.219% | 0.248% |
| medium | 0.583% | 0.575% | 0.398% | 0.475% |
| fine | 0.524% | 0.518% | 0.326% | 0.409% |

## Mesh-to-Mesh Deltas

| pair | dCL_primary | dCD_primary | dCD_total_physical | dCmPitch abs rel | interpretation |
|---|---:|---:|---:|---:|---|
| Coarse -> Medium | -0.106% | -5.492% | -5.492% | 0.367% | coarse is outside the Medium/Fine drag-asymptotic band |
| Medium -> Fine | 0.198% | -1.443% | -1.444% | 0.682% | passes requested CL/CD/Cm grid-stability thresholds |

## Pressure / Viscous Split

| grid | group | CD_pressure | CD_viscous | CL_pressure | CL_viscous |
|---|---|---:|---:|---:|---:|
| coarse | `primary` | 0.02513524 | 0.01051795 | 1.15933678 | 0.00052906 |
| coarse | `total_physical` | 0.02519168 | 0.01052258 | 1.15933083 | 0.00052616 |
| medium | `primary` | 0.02331655 | 0.01037839 | 1.15808100 | 0.00055767 |
| medium | `total_physical` | 0.02336967 | 0.01038314 | 1.15807621 | 0.00055480 |
| fine | `primary` | 0.02289777 | 0.01031100 | 1.16037290 | 0.00056173 |
| fine | `total_physical` | 0.02295001 | 0.01031555 | 1.16036811 | 0.00055877 |

## Engineering Reading

- Medium and Fine both pass the same 2000-iteration final-100 force-window gate, with residuals not diverging and yPlus valid.
- Medium -> Fine `CD_total_physical` changes by `-1.444%`, which is inside the requested 2-3% preferred band and far below the 5% fail marker.
- Coarse -> Medium drag changes by about `-5.49%`, so Coarse should be treated as a lower-resolution sanity rung, not as part of a three-point extrapolation.
- The grid-stable locked OpenFOAM physical-wing drag is centered near Fine `CD_total_physical=0.03326556` / `CD_primary=0.03320877`, not `CD≈0.0315`.
