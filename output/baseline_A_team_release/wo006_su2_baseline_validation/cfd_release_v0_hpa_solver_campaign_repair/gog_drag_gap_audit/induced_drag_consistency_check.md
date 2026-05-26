# Induced Drag Consistency Check

## Scope

This report checks whether the old-vs-CFD drag gap can be explained by induced drag accounting. It cannot. The evidence points to profile/form/transition accounting, not a missing induced term.

## Geometry and AVL reference

| Quantity | Value |
|---|---:|
| Sref | 33.420059598 m^2 |
| Bref | 34.332286 m |
| Aspect ratio `b^2/S` | 35.269412 |
| AVL `CLtot` | 1.16853 |
| AVL `CDind` | 0.0127613 |
| AVL Trefftz `CLff` | 1.16460 |
| AVL Trefftz `CDff` | 0.0127986 |
| AVL Trefftz `e` | 0.9564 |

The Trefftz-plane consistency check is:

```text
CDi = CLff^2 / (pi * AR * e)
    = 1.16460^2 / (pi * 35.269412 * 0.9564)
    = 0.0127987
```

This matches AVL `CDff=0.0127986`.

Using total-force `CLtot=1.16853` with the strip-force `CDind=0.0127613` implies `e=0.96569`. The difference is a definition/detail difference between the total and Trefftz references, not evidence of a 50% drag-accounting problem.

## AVL induced spanwise contribution

The table below uses the half-wing AVL strip areas and local induced `cd`, doubled and normalized by `Sref`. Sum: `CDi=0.01276163`, matching the AVL `CDind=0.0127613` within rounding.

| strip | y_m | chord_m | area_half_m2 | cl_AVL | ai_deg | cd_i_local | dCDi |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 0.011 | 1.2564 | 0.05680 | 1.2989 | 0.0344 | 0.01200 | 0.000041 |
| 2 | 0.102 | 1.2536 | 0.16940 | 1.2876 | 0.0324 | 0.01620 | 0.000164 |
| 3 | 0.281 | 1.2481 | 0.27920 | 1.2894 | 0.0304 | 0.01660 | 0.000277 |
| 4 | 0.548 | 1.2398 | 0.38460 | 1.2930 | 0.0286 | 0.01670 | 0.000384 |
| 5 | 0.900 | 1.2288 | 0.48380 | 1.2982 | 0.0273 | 0.01670 | 0.000484 |
| 6 | 1.334 | 1.2154 | 0.57530 | 1.3049 | 0.0263 | 0.01660 | 0.000572 |
| 7 | 1.845 | 1.1995 | 0.65790 | 1.3130 | 0.0257 | 0.01650 | 0.000650 |
| 8 | 2.429 | 1.1814 | 0.73050 | 1.3225 | 0.0254 | 0.01670 | 0.000730 |
| 9 | 3.025 | 1.1627 | 0.66300 | 1.3293 | 0.0249 | 0.01650 | 0.000655 |
| 10 | 3.618 | 1.1437 | 0.70700 | 1.3323 | 0.0241 | 0.01600 | 0.000677 |
| 11 | 4.257 | 1.1233 | 0.74150 | 1.3355 | 0.0235 | 0.01580 | 0.000701 |
| 12 | 4.934 | 1.1017 | 0.76640 | 1.3384 | 0.0234 | 0.01580 | 0.000725 |
| 13 | 5.644 | 1.0790 | 0.78180 | 1.3408 | 0.0239 | 0.01620 | 0.000758 |
| 14 | 6.484 | 1.0515 | 1.01300 | 1.3371 | 0.0233 | 0.01580 | 0.000958 |
| 15 | 7.451 | 1.0194 | 1.00140 | 1.3255 | 0.0220 | 0.01480 | 0.000887 |
| 16 | 8.433 | 0.9868 | 0.97880 | 1.3120 | 0.0219 | 0.01460 | 0.000855 |
| 17 | 9.323 | 0.9565 | 0.76860 | 1.2917 | 0.0222 | 0.01450 | 0.000667 |
| 18 | 10.111 | 0.9289 | 0.73920 | 1.2632 | 0.0227 | 0.01450 | 0.000641 |
| 19 | 10.888 | 0.9017 | 0.70370 | 1.2301 | 0.0250 | 0.01530 | 0.000644 |
| 20 | 11.646 | 0.8751 | 0.66290 | 1.1859 | 0.0314 | 0.01690 | 0.000670 |
| 21 | 12.383 | 0.8484 | 0.63310 | 1.0858 | 0.0250 | 0.01230 | 0.000466 |
| 22 | 13.092 | 0.8218 | 0.58190 | 0.9313 | 0.0055 | 0.00330 | 0.000115 |
| 23 | 13.760 | 0.7968 | 0.52830 | 0.7787 | -0.0132 | -0.00270 | -0.000085 |
| 24 | 14.444 | 0.7701 | 0.57650 | 0.6734 | -0.0157 | -0.00340 | -0.000117 |
| 25 | 15.132 | 0.7422 | 0.50370 | 0.6205 | -0.0052 | -0.00100 | -0.000030 |
| 26 | 15.688 | 0.7189 | 0.34730 | 0.5766 | 0.0023 | 0.00100 | 0.000021 |
| 27 | 16.117 | 0.6999 | 0.29180 | 0.5317 | 0.0098 | 0.00290 | 0.000051 |
| 28 | 16.468 | 0.6828 | 0.22010 | 0.4785 | 0.0189 | 0.00470 | 0.000062 |
| 29 | 16.741 | 0.6680 | 0.16960 | 0.4103 | 0.0293 | 0.00630 | 0.000064 |
| 30 | 16.948 | 0.6568 | 0.12030 | 0.3187 | 0.0389 | 0.00690 | 0.000050 |
| 31 | 17.087 | 0.6493 | 0.07180 | 0.2031 | 0.0458 | 0.00550 | 0.000024 |
| 32 | 17.157 | 0.6455 | 0.02390 | 0.0706 | 0.0558 | 0.00210 | 0.000003 |

## CFD induced estimate

OpenFOAM total drag already contains induced drag. It is a 3D finite-wing force integration, so AVL induced drag must not be added to `CD_total_physical`.

Accepted Fine CFD reference for this subtraction: `CL_primary=1.160934`, `CD_total_physical=0.03326556`.

Estimated induced drag at CFD lift:

| Assumed e | CDi at `CL=1.160934` | CFD residual `CD_total_physical - CDi` |
|---:|---:|---:|
| 1.00000 | 0.01216374 | 0.02110182 |
| 0.96569 | 0.01259593 | 0.02066963 |
| 0.95640 | 0.01271825 | 0.02054731 |
| 0.90000 | 0.01351526 | 0.01975030 |
| 0.85000 | 0.01431028 | 0.01895528 |

## Verdict

The induced-drag bookkeeping is internally consistent. The old AVL `CDi` is not suspicious enough to explain a `0.0111` CD gap. The OpenFOAM CD already contains induced drag, so adding AVL `CDi` to OpenFOAM would double-count induced drag.

The unresolved gap sits mostly in profile/form/transition/numerical drag after induced drag is accounted for.
