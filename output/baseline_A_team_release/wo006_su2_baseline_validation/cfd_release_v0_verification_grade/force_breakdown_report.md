# Force Breakdown Report

Primary force patches are fixed as `wing_upper + wing_lower`; diagnostic patches remain separate as `tip_left`, `tip_right`, `te_wall`, and `closure_wall`. The diagnostic CD contribution remains tiny relative to total CD, so the high CD is not explained by tip/TE/closure contamination.

| case | CD_primary | CL_primary | CD_total | CD_tip_left | CD_tip_right | CD_te_wall | CD_closure_wall | CD_diag_sum | Cd(f)/Cd(r) note |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `wall_function_target` | 0.07596562 | 0.8922962 | 0.07600988 | 2.86862300e-06 | 2.92751900e-06 | 3.84433700e-05 | 2.06211900e-08 | 4.42601332e-05 | 0.4857152 / -0.4097495 |
| `intermediate_target` | 0.09213965 | 0.6566135 | 0.09219328 | 2.82955200e-06 | 2.83001800e-06 | 4.90562800e-05 | -1.08576500e-06 | 5.36300850e-05 | -0.00989171 / 0.1020314 |
| `wall_resolved_target` | 0.07326929 | 0.9215704 | 0.07332259 | 2.86418600e-06 | 2.86406900e-06 | 4.68564100e-05 | 7.15507200e-07 | 5.33001722e-05 | 0.05063048 / 0.0226388 |

## Pressure / Viscous Split

Pressure and viscous force contributions are not available from the current `forceCoeffs` outputs. The OpenFOAM columns `Cd(f)` and `Cd(r)` are front/rear axle coefficients in `forceCoeffs.H`, not pressure/viscous coefficients. Therefore this report does not reinterpret them as pressure drag or skin-friction drag.

For the closest high-yPlus case, `wall_resolved_target`, the last-row primary values are `CD_primary=0.07326929`, `CL_primary=0.9215704`, and `CD_total=0.07332259`, with diagnostic CD sum about `5.33e-05`. These values are useful only as high-yPlus sanity evidence.
