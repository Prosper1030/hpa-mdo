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
| FX 76-MP-140 | 6 | 0.0336 | 0.0880 | Yes | No | outboard: upper[1]=0.394489 > 0.380000; upper[3]=0.331897 > 0.319223; upper[4]=0.589002 > 0.485202; upper[6]=0.403292 > 0.249342; lower[6]=0.252677 > 0.132998 |
| FX 76-MP-140 | 7 | 0.0187 | 0.0504 | N/A | N/A | root: degree_mismatch: fit has 8 coefficients, bounds have 7<br>outboard: degree_mismatch: fit has 8 coefficients, bounds have 7 |
| DAE11 | 4 | 0.1072 | 0.2814 | N/A | N/A | root: degree_mismatch: fit has 5 coefficients, bounds have 7<br>outboard: degree_mismatch: fit has 5 coefficients, bounds have 7 |
| DAE11 | 5 | 0.0706 | 0.2359 | N/A | N/A | root: degree_mismatch: fit has 6 coefficients, bounds have 7<br>outboard: degree_mismatch: fit has 6 coefficients, bounds have 7 |
| DAE11 | 6 | 0.0552 | 0.1979 | Yes | No | outboard: upper[1]=0.412914 > 0.380000; upper[3]=0.555449 > 0.319223; lower[4]=-0.142734 < -0.100000 |
| DAE11 | 7 | 0.0526 | 0.1953 | N/A | N/A | root: degree_mismatch: fit has 8 coefficients, bounds have 7<br>outboard: degree_mismatch: fit has 8 coefficients, bounds have 7 |
| DAE21 | 4 | 0.0848 | 0.2392 | N/A | N/A | root: degree_mismatch: fit has 5 coefficients, bounds have 7<br>outboard: degree_mismatch: fit has 5 coefficients, bounds have 7 |
| DAE21 | 5 | 0.0538 | 0.1706 | N/A | N/A | root: degree_mismatch: fit has 6 coefficients, bounds have 7<br>outboard: degree_mismatch: fit has 6 coefficients, bounds have 7 |
| DAE21 | 6 | 0.0478 | 0.1451 | Yes | Yes | - |
| DAE21 | 7 | 0.0392 | 0.1535 | N/A | N/A | root: degree_mismatch: fit has 8 coefficients, bounds have 7<br>outboard: degree_mismatch: fit has 8 coefficients, bounds have 7 |
| DAE31 | 4 | 0.0879 | 0.3007 | N/A | N/A | root: degree_mismatch: fit has 5 coefficients, bounds have 7<br>outboard: degree_mismatch: fit has 5 coefficients, bounds have 7 |
| DAE31 | 5 | 0.0615 | 0.2233 | N/A | N/A | root: degree_mismatch: fit has 6 coefficients, bounds have 7<br>outboard: degree_mismatch: fit has 6 coefficients, bounds have 7 |
| DAE31 | 6 | 0.0511 | 0.1802 | No | Yes | root: upper[5]=0.298715 > 0.266423; lower[1]=0.133720 > 0.104269; lower[3]=0.270414 > 0.242362 |
| DAE31 | 7 | 0.0385 | 0.1415 | N/A | N/A | root: degree_mismatch: fit has 8 coefficients, bounds have 7<br>outboard: degree_mismatch: fit has 8 coefficients, bounds have 7 |
| DAE41 | 4 | 0.0306 | 0.1045 | N/A | N/A | root: degree_mismatch: fit has 5 coefficients, bounds have 7<br>outboard: degree_mismatch: fit has 5 coefficients, bounds have 7 |
| DAE41 | 5 | 0.0199 | 0.0734 | N/A | N/A | root: degree_mismatch: fit has 6 coefficients, bounds have 7<br>outboard: degree_mismatch: fit has 6 coefficients, bounds have 7 |
| DAE41 | 6 | 0.0174 | 0.0600 | Yes | Yes | - |
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

## Post-audit Bounds Patch

- Old bounds were too narrow in the aft upper CST coefficients, positive or less-negative lower coefficients, and near-sharp trailing-edge thickness. The old feasible-search `te_thickness_min = 0.001` also rejected several closed or near-closed historical airfoils before aerodynamic scoring.
- Root/mid1 coverage target: FX 76-MP-140, DAE11, DAE21.
- Outboard coverage target: DAE21, DAE31, DAE41.
- New bounds use the audited `n=6` coefficients with about `0.01` absolute coefficient margin only where the historical family was blocked or had less than that margin.
- Root/mid1 widened: `upper_max[1,3,4,5,6]`, `lower_min[4]`, `lower_max[1,3,5,6]`, and `te_thickness_min`.
- Outboard widened: `upper_max[3,4,5,6]`, `lower_max[1,3,5,6]`, and `te_thickness_min`.
- `n=7` is not the default because `n=6` already meets the `<0.2%c` geometry gate for all audited FX/DAE cases; `n=7` remains useful as a diagnostic or future margin study.
- `seedless_sample_count = 96` is now treated as smoke-scale only. A production seedless search should use at least `1024` Sobol samples per zone because the search has 15 dimensions before geometry filtering.
- Production recommendation: `n = 6`, `seedless_sample_count >= 1024` per zone, and `robust_reynolds_factors = [0.85, 1.0, 1.15]`.
- Engineering note: airfoil coverage search now allows near-sharp TE via `seedless_te_thickness_min`; any manufacturing trailing-edge thickness requirement should remain a separate build/manufacturing gate, not a search-space coverage gate.

Implemented controlled bounds:

```python
_ROOT_SEEDLESS_CST_BOUNDS = SeedlessCSTCoefficientBounds(
    upper_min=(0.05, 0.10, 0.10, 0.06, 0.02, 0.005, 0.003),
    upper_max=(0.30, 0.422914, 0.40, 0.565449, 0.599002, 0.266423, 0.413292),
    lower_min=(-0.22, -0.28, -0.25, -0.20, -0.152734, -0.06, -0.020),
    lower_max=(-0.02, 0.104269, -0.04, 0.242362, 0.02, 0.188743, 0.262677),
    te_thickness_min=0.0,
    te_thickness_max=0.0040,
)

_OUTBOARD_SEEDLESS_CST_BOUNDS = SeedlessCSTCoefficientBounds(
    upper_min=(0.04, 0.08, 0.08, 0.04, 0.02, 0.005, 0.002),
    upper_max=(0.28, 0.38, 0.36, 0.319223, 0.485202, 0.308715, 0.249342),
    lower_min=(-0.18, -0.24, -0.22, -0.16, -0.10, -0.05, -0.018),
    lower_max=(-0.02, 0.143720, -0.03, 0.280414, 0.02, 0.184917, 0.132998),
    te_thickness_min=0.0,
    te_thickness_max=0.0035,
)
```

## GPT Discussion Summary

- Repo already had `data/airfoils/fx76mp140.dat`; DAE11/21/31/41 were absent and were added only as audit reference data under `docs/research/historical_airfoil_cst_coverage/airfoils/` from the MIT Drela HPA airfoil index.
- Using the project CST form (`N1=0.5`, `N2=1.0`) and least-squares fitting, `n=6` is geometrically sufficient for the audited FX/DAE set if max vertical residual below `0.2%c` is the gate.
- Phase 3 applies controlled `n=6` bounds widening for the intended root/mid1 and outboard historical families rather than making all zones cover all audited airfoils.
- Seedless CST search now allows near-sharp TE via `seedless_te_thickness_min`; manufacturing TE thickness should be enforced separately if needed.
- Formal airfoil selection should use at least `1024` seedless samples per zone plus multipoint Reynolds robustness `[0.85, 1.0, 1.15]`; `96` samples and `[1.0]` are smoke-scale settings only.
