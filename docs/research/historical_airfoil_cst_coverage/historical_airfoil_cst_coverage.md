# Historical Airfoil CST Coverage Audit

Read-only audit of current seedless CST coverage for historical low-Reynolds airfoils.

## Method

- CST class exponents: `N1 = 0.5`, `N2 = 1.0`.
- Bernstein degrees fitted: `n = 4, 5, 6, 7`.
- Fit method: linear least squares for upper coefficients, lower coefficients, and trailing-edge thickness in the same form used by `generate_cst_coordinates`.
- Trailing-edge fit is constrained non-negative; if the unconstrained least-squares solution wants a small negative TE on a closed-TE airfoil, coefficients are refit with `TE = 0`.
- Error metric: vertical coordinate residual on normalized `.dat` points, reported as percent chord.

## Source Status

| Airfoil | Repo .dat? | Audit source | Source path |
| ------- | --------- | ------------ | ----------- |
| FX 76-MP-140 | Yes | repo:data/airfoils/fx76mp140.dat | `data/airfoils/fx76mp140.dat` |
| DAE11 | No | [MIT Drela HPA airfoil index](https://web.mit.edu/drela/Public/web/hpa/airfoils/dae11.dat) | `docs/research/historical_airfoil_cst_coverage/airfoils/dae11.dat` |
| DAE21 | No | [MIT Drela HPA airfoil index](https://web.mit.edu/drela/Public/web/hpa/airfoils/dae21.dat) | `docs/research/historical_airfoil_cst_coverage/airfoils/dae21.dat` |
| DAE31 | No | [MIT Drela HPA airfoil index](https://web.mit.edu/drela/Public/web/hpa/airfoils/dae31.dat) | `docs/research/historical_airfoil_cst_coverage/airfoils/dae31.dat` |
| DAE41 | No | [MIT Drela HPA airfoil index](https://web.mit.edu/drela/Public/web/hpa/airfoils/dae41.dat) | `docs/research/historical_airfoil_cst_coverage/airfoils/dae41.dat` |

## Coverage Table

| Airfoil | n | RMS error %c | Max error %c | Fits root bounds? | Fits outboard bounds? | Which coefficients exceed bounds? |
| ------- | - | ------------ | ------------ | ----------------- | --------------------- | --------------------------------- |
| FX 76-MP-140 | 4 | 0.0853 | 0.1878 | N/A | N/A | root: degree_mismatch: fit has 5 coefficients, bounds have 7<br>outboard: degree_mismatch: fit has 5 coefficients, bounds have 7 |
| FX 76-MP-140 | 5 | 0.0384 | 0.0900 | N/A | N/A | root: degree_mismatch: fit has 6 coefficients, bounds have 7<br>outboard: degree_mismatch: fit has 6 coefficients, bounds have 7 |
| FX 76-MP-140 | 6 | 0.0336 | 0.0880 | No | No | root: upper[3]=0.331897 > 0.320000; upper[4]=0.589002 > 0.200000; upper[5]=0.249189 > 0.120000; upper[6]=0.403292 > 0.040000; lower[1]=0.036463 > -0.040000; lower[3]=0.112067 > -0.020000; lower[5]=0.082112 > 0.020000; lower[6]=0.252677 > 0.005000<br>outboard: upper[1]=0.394489 > 0.380000; upper[3]=0.331897 > 0.280000; upper[4]=0.589002 > 0.180000; upper[5]=0.249189 > 0.100000; upper[6]=0.403292 > 0.035000; lower[1]=0.036463 > -0.030000; lower[3]=0.112067 > -0.020000; lower[5]=0.082112 > 0.020000; lower[6]=0.252677 > 0.005000 |
| FX 76-MP-140 | 7 | 0.0187 | 0.0504 | N/A | N/A | root: degree_mismatch: fit has 8 coefficients, bounds have 7<br>outboard: degree_mismatch: fit has 8 coefficients, bounds have 7 |
| DAE11 | 4 | 0.1072 | 0.2814 | N/A | N/A | root: degree_mismatch: fit has 5 coefficients, bounds have 7<br>outboard: degree_mismatch: fit has 5 coefficients, bounds have 7 |
| DAE11 | 5 | 0.0706 | 0.2359 | N/A | N/A | root: degree_mismatch: fit has 6 coefficients, bounds have 7<br>outboard: degree_mismatch: fit has 6 coefficients, bounds have 7 |
| DAE11 | 6 | 0.0552 | 0.1979 | No | No | root: upper[3]=0.555449 > 0.320000; upper[4]=0.281998 > 0.200000; upper[5]=0.256423 > 0.120000; upper[6]=0.143946 > 0.040000; lower[1]=0.086571 > -0.040000; lower[3]=0.232362 > -0.020000; lower[4]=-0.142734 < -0.120000; lower[5]=0.178743 > 0.020000; lower[6]=0.005850 > 0.005000; te_thickness=0.000112 < 0.001000<br>outboard: upper[1]=0.412914 > 0.380000; upper[3]=0.555449 > 0.280000; upper[4]=0.281998 > 0.180000; upper[5]=0.256423 > 0.100000; upper[6]=0.143946 > 0.035000; lower[1]=0.086571 > -0.030000; lower[3]=0.232362 > -0.020000; lower[4]=-0.142734 < -0.100000; lower[5]=0.178743 > 0.020000; lower[6]=0.005850 > 0.005000; te_thickness=0.000112 < 0.001000 |
| DAE11 | 7 | 0.0526 | 0.1953 | N/A | N/A | root: degree_mismatch: fit has 8 coefficients, bounds have 7<br>outboard: degree_mismatch: fit has 8 coefficients, bounds have 7 |
| DAE21 | 4 | 0.0848 | 0.2392 | N/A | N/A | root: degree_mismatch: fit has 5 coefficients, bounds have 7<br>outboard: degree_mismatch: fit has 5 coefficients, bounds have 7 |
| DAE21 | 5 | 0.0538 | 0.1706 | N/A | N/A | root: degree_mismatch: fit has 6 coefficients, bounds have 7<br>outboard: degree_mismatch: fit has 6 coefficients, bounds have 7 |
| DAE21 | 6 | 0.0478 | 0.1451 | No | No | root: upper[4]=0.475202 > 0.200000; upper[5]=0.167789 > 0.120000; upper[6]=0.239342 > 0.040000; lower[1]=0.094269 > -0.040000; lower[3]=0.182120 > -0.020000; lower[5]=0.107973 > 0.020000; lower[6]=0.122998 > 0.005000; te_thickness=0.000000 < 0.001000<br>outboard: upper[3]=0.298144 > 0.280000; upper[4]=0.475202 > 0.180000; upper[5]=0.167789 > 0.100000; upper[6]=0.239342 > 0.035000; lower[1]=0.094269 > -0.030000; lower[3]=0.182120 > -0.020000; lower[5]=0.107973 > 0.020000; lower[6]=0.122998 > 0.005000; te_thickness=0.000000 < 0.001000 |
| DAE21 | 7 | 0.0392 | 0.1535 | N/A | N/A | root: degree_mismatch: fit has 8 coefficients, bounds have 7<br>outboard: degree_mismatch: fit has 8 coefficients, bounds have 7 |
| DAE31 | 4 | 0.0879 | 0.3007 | N/A | N/A | root: degree_mismatch: fit has 5 coefficients, bounds have 7<br>outboard: degree_mismatch: fit has 5 coefficients, bounds have 7 |
| DAE31 | 5 | 0.0615 | 0.2233 | N/A | N/A | root: degree_mismatch: fit has 6 coefficients, bounds have 7<br>outboard: degree_mismatch: fit has 6 coefficients, bounds have 7 |
| DAE31 | 6 | 0.0511 | 0.1802 | No | No | root: upper[4]=0.423764 > 0.200000; upper[5]=0.298715 > 0.120000; upper[6]=0.230621 > 0.040000; lower[1]=0.133720 > -0.040000; lower[3]=0.270414 > -0.020000; lower[5]=0.174917 > 0.020000; lower[6]=0.097008 > 0.005000; te_thickness=0.000000 < 0.001000<br>outboard: upper[3]=0.309223 > 0.280000; upper[4]=0.423764 > 0.180000; upper[5]=0.298715 > 0.100000; upper[6]=0.230621 > 0.035000; lower[1]=0.133720 > -0.030000; lower[3]=0.270414 > -0.020000; lower[5]=0.174917 > 0.020000; lower[6]=0.097008 > 0.005000; te_thickness=0.000000 < 0.001000 |
| DAE31 | 7 | 0.0385 | 0.1415 | N/A | N/A | root: degree_mismatch: fit has 8 coefficients, bounds have 7<br>outboard: degree_mismatch: fit has 8 coefficients, bounds have 7 |
| DAE41 | 4 | 0.0306 | 0.1045 | N/A | N/A | root: degree_mismatch: fit has 5 coefficients, bounds have 7<br>outboard: degree_mismatch: fit has 5 coefficients, bounds have 7 |
| DAE41 | 5 | 0.0199 | 0.0734 | N/A | N/A | root: degree_mismatch: fit has 6 coefficients, bounds have 7<br>outboard: degree_mismatch: fit has 6 coefficients, bounds have 7 |
| DAE41 | 6 | 0.0174 | 0.0600 | No | No | root: upper[4]=0.253830 > 0.200000; upper[5]=0.191304 > 0.120000; upper[6]=0.129841 > 0.040000; lower[3]=-0.001383 > -0.020000; lower[6]=0.011098 > 0.005000; te_thickness=0.000000 < 0.001000<br>outboard: upper[4]=0.253830 > 0.180000; upper[5]=0.191304 > 0.100000; upper[6]=0.129841 > 0.035000; lower[3]=-0.001383 > -0.020000; lower[6]=0.011098 > 0.005000; te_thickness=0.000000 < 0.001000 |
| DAE41 | 7 | 0.0129 | 0.0427 | N/A | N/A | root: degree_mismatch: fit has 8 coefficients, bounds have 7<br>outboard: degree_mismatch: fit has 8 coefficients, bounds have 7 |

## Coefficient Details

| Airfoil | n | TE thickness | Upper coefficients | Lower coefficients |
| ------- | - | ------------ | ------------------ | ------------------ |
| FX 76-MP-140 | 4 | 0.002457 | `[0.247614, 0.399643, 0.329557, 0.505814, 0.290573]` | `[-0.134508, 0.044851, 0.001173, -0.016170, 0.255926]` |
| FX 76-MP-140 | 5 | 0.001799 | `[0.229569, 0.448078, 0.183940, 0.626173, 0.284959, 0.377842]` | `[-0.142998, 0.045126, -0.060680, 0.093380, -0.036922, 0.283648]` |
| FX 76-MP-140 | 6 | 0.001343 | `[0.233013, 0.394489, 0.317836, 0.331897, 0.589002, 0.249189, 0.403292]` | `[-0.147546, 0.036463, -0.085616, 0.112067, -0.049178, 0.082112, 0.252677]` |
| FX 76-MP-140 | 7 | 0.000974 | `[0.223681, 0.424645, 0.179891, 0.624675, 0.074542, 0.797112, 0.103541, 0.464959]` | `[-0.149559, 0.021246, -0.083772, 0.086749, -0.027305, 0.041339, 0.081262, 0.255302]` |
| DAE11 | 4 | 0.001530 | `[0.221693, 0.358243, 0.356471, 0.393328, 0.079779]` | `[-0.112477, 0.060322, -0.059250, 0.117751, 0.040146]` |
| DAE11 | 5 | 0.000344 | `[0.204599, 0.408758, 0.183697, 0.605559, 0.134038, 0.190352]` | `[-0.121334, 0.065494, -0.100025, 0.124375, 0.011263, 0.075913]` |
| DAE11 | 6 | 0.000112 | `[0.197377, 0.412914, 0.158419, 0.555449, 0.281998, 0.256423, 0.143946]` | `[-0.131072, 0.086571, -0.182641, 0.232362, -0.142734, 0.178743, 0.005850]` |
| DAE11 | 7 | 0.000617 | `[0.197384, 0.381690, 0.232386, 0.381027, 0.445454, 0.264061, 0.249519, 0.133595]` | `[-0.136352, 0.087984, -0.204345, 0.241432, -0.163958, 0.154730, 0.032156, 0.058364]` |
| DAE21 | 4 | 0.000231 | `[0.248035, 0.324353, 0.356289, 0.368278, 0.161530]` | `[-0.100261, 0.074930, -0.023616, 0.118827, 0.099419]` |
| DAE21 | 5 | 0.000509 | `[0.237362, 0.354582, 0.243830, 0.490760, 0.221307, 0.211689]` | `[-0.112574, 0.097200, -0.111428, 0.201025, -0.021872, 0.169394]` |
| DAE21 | 6 | 0.000000 | `[0.240624, 0.318811, 0.323892, 0.298144, 0.475202, 0.167789, 0.239342]` | `[-0.118351, 0.094269, -0.127734, 0.182120, -0.017213, 0.107973, 0.122998]` |
| DAE21 | 7 | 0.000169 | `[0.239092, 0.316301, 0.296573, 0.356662, 0.315773, 0.434975, 0.152184, 0.246168]` | `[-0.126149, 0.114658, -0.220361, 0.342781, -0.268451, 0.327648, -0.065123, 0.187458]` |
| DAE31 | 4 | 0.000000 | `[0.237039, 0.348340, 0.265698, 0.460901, 0.187573]` | `[-0.115987, 0.107698, -0.034172, 0.163528, 0.085987]` |
| DAE31 | 5 | 0.000770 | `[0.229866, 0.356072, 0.233090, 0.426835, 0.340094, 0.213389]` | `[-0.129565, 0.126618, -0.118797, 0.232737, -0.005780, 0.168293]` |
| DAE31 | 6 | 0.000000 | `[0.230733, 0.330889, 0.286501, 0.309223, 0.423764, 0.298715, 0.230621]` | `[-0.138559, 0.133720, -0.170458, 0.270414, -0.070197, 0.174917, 0.097008]` |
| DAE31 | 7 | 0.000073 | `[0.224925, 0.349615, 0.200506, 0.483087, 0.130453, 0.580134, 0.180250, 0.268694]` | `[-0.146951, 0.149164, -0.250660, 0.395527, -0.266249, 0.329872, -0.022867, 0.164265]` |
| DAE41 | 4 | 0.000000 | `[0.203003, 0.243800, 0.221693, 0.258075, 0.118392]` | `[-0.124129, -0.050251, -0.086040, -0.033324, -0.001465]` |
| DAE41 | 5 | 0.000113 | `[0.201401, 0.242464, 0.215554, 0.255445, 0.214709, 0.125022]` | `[-0.129533, -0.039872, -0.127569, 0.008673, -0.087150, 0.029362]` |
| DAE41 | 6 | 0.000000 | `[0.201906, 0.233089, 0.231347, 0.224515, 0.253830, 0.191304, 0.129841]` | `[-0.131993, -0.041152, -0.134709, -0.001383, -0.083607, -0.026947, 0.011098]` |
| DAE41 | 7 | 0.000051 | `[0.201419, 0.231423, 0.223460, 0.242905, 0.218049, 0.251591, 0.173977, 0.132183]` | `[-0.135362, -0.032213, -0.175361, 0.068208, -0.194514, 0.066463, -0.097695, 0.039102]` |

## Judgment

- `n=6` geometry fit is adequate for all audited airfoils; worst max error is 0.1979%c on DAE11.
- Current seedless bounds are too narrow for the historical set after `n=6` fitting.
- Repeated exceedance pattern: trailing-edge minimum is above the fitted near-sharp historical TE; upper aft coefficients and lower aft/positive-camber coefficients also exceed the current envelope.

## Proposed Bounds Patch Only

Not applied. This widens the existing `n=6` default bounds just enough to contain the fitted historical envelope plus a small 0.01 coefficient margin.

Engineering note: a bounds-only patch is not the full production change. The current seedless validation constraint also has `te_thickness_min = 0.001`, so historical near-sharp trailing edges would still need a separate constraint decision before they can survive feasible-candidate filtering.

```diff
- _ROOT_SEEDLESS_CST_BOUNDS = SeedlessCSTCoefficientBounds(...)
+ _ROOT_SEEDLESS_CST_BOUNDS = SeedlessCSTCoefficientBounds(
+     upper_min=(0.050000, 0.100000, 0.100000, 0.060000, 0.020000, 0.005000, 0.003000),
+     upper_max=(0.300000, 0.422914, 0.400000, 0.565449, 0.599002, 0.308715, 0.413292),
+     lower_min=(-0.220000, -0.280000, -0.250000, -0.200000, -0.152734, -0.060000, -0.020000),
+     lower_max=(-0.020000, 0.143720, -0.040000, 0.280414, 0.020000, 0.188743, 0.262677),
+     te_thickness_min=0.000000,
+     te_thickness_max=0.004000,
+ )
- _OUTBOARD_SEEDLESS_CST_BOUNDS = SeedlessCSTCoefficientBounds(...)
+ _OUTBOARD_SEEDLESS_CST_BOUNDS = SeedlessCSTCoefficientBounds(
+     upper_min=(0.040000, 0.080000, 0.080000, 0.040000, 0.020000, 0.005000, 0.002000),
+     upper_max=(0.280000, 0.422914, 0.360000, 0.565449, 0.599002, 0.308715, 0.413292),
+     lower_min=(-0.180000, -0.240000, -0.220000, -0.160000, -0.152734, -0.050000, -0.018000),
+     lower_max=(-0.020000, 0.143720, -0.030000, 0.280414, 0.020000, 0.188743, 0.262677),
+     te_thickness_min=0.000000,
+     te_thickness_max=0.003500,
+ )
```

## GPT Discussion Summary

- Repo already had `data/airfoils/fx76mp140.dat`; DAE11/21/31/41 were absent and were added only as audit reference data under `docs/research/historical_airfoil_cst_coverage/airfoils/` from the MIT Drela HPA airfoil index.
- Using the project CST form (`N1=0.5`, `N2=1.0`) and least-squares fitting, `n=6` is geometrically sufficient for the audited FX/DAE set if max vertical residual below `0.2%c` is the gate.
- The present `_ROOT_SEEDLESS_CST_BOUNDS` and `_OUTBOARD_SEEDLESS_CST_BOUNDS` are not broad enough to include those historical `n=6` fits, especially TE thickness and several aft/positive lower coefficients.
- Because coefficients are already out of bounds, this is a bounds-envelope issue before it is a `sample_count=96` issue. If bounds are widened and similar shapes are still not sampled, then the sparse 96-point Sobol draw becomes the next suspect.
