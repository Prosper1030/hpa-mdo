# Old XFOIL + AVL Wing CD Breakdown

## Scope

This audit uses the old conservative-best Tier2/XFOIL + AVL artifact as the old wing-only reference. It does not update design power.

Primary sources:

- `output/go_mode_main_wing_candidate/current_avl_compromise_conservative_closed_tier2_airfoil/tier2_loaded_shape_selected_avl_recheck.csv`
- `output/go_mode_main_wing_candidate/current_avl_compromise_conservative_closed_tier2_airfoil/tier2_loaded_shape_profile_drag.csv`
- `output/go_mode_main_wing_candidate/current_avl_compromise_conservative_closed_tier2_airfoil/runs/conservative_best/avl_run/concept_trim.ft`
- `output/go_mode_main_wing_candidate/current_avl_compromise_conservative_closed_tier2_airfoil/runs/conservative_best/avl_run/concept_spanwise.fs`
- `scripts/tier2_loaded_shape_airfoil_mvp.py`
- `src/hpa_mdo/airfoils/database.py`
- `tools/julia/xfoil_worker/xfoil_worker.jl`

## CD accounting

The old user-facing wing-only estimate near `0.0221` is:

| Component | CD | Notes |
|---|---:|---|
| XFOIL/Tier2 clean profile drag | 0.009368851 | Integrated from local `Re`, local AVL `cl`, and selected airfoils |
| AVL induced drag | 0.012761300 | From `concept_trim.ft`, `CDind` |
| Old wing-only CD | 0.022130151 | `profile_cd + CDi`; this is the user's `CD_wing_old ~= 0.0221` |
| Non-wing reserve in old screening closure | 0.003889879 | `CDA_nonwing / Sref`; not wing-only |
| Old screening `CD_total` | 0.026020031 | `CDi + profile_cd + non-wing reserve` |

Important: the old `CD_total=0.026020031` is not the same quantity as old wing-only `CD_wing_old=0.022130151`. The old full screening value includes a non-wing reserve. The OpenFOAM wing CD must not be combined with the AVL induced term.

## Transition and XFOIL settings

The old profile integration did not request roughness explicitly. In `src/hpa_mdo/airfoils/database.py`, a query with `roughness_mode=None` selects clean polar points when available. In `scripts/tier2_loaded_shape_airfoil_mvp.py`, the profile integration calls `AirfoilQuery(... allow_extrapolation=False)` without setting roughness mode.

The XFOIL worker roughness controls are:

| Mode | Ncrit | xtrip upper/lower |
|---|---:|---|
| clean | 9.0 | `(1.0, 1.0)` |
| rough/dirty | 5.0 | `(0.05, 0.05)` |
| fallback other | 7.0 | `(0.30, 0.30)` |

The accepted old profile drag is therefore a clean/natural-transition XFOIL integration, not a forced-transition or fully turbulent profile-drag estimate.

As a no-new-CFD cross-check, the same station `Re` and `cl` queries were re-integrated against the existing Tier2 rough polars:

| Existing XFOIL basis | Integrated profile CD | Warnings |
|---|---:|---|
| clean/default | 0.009368851 | none |
| rough (`Ncrit=5`, `xtrip=0.05/0.05`) | 0.023487768 | none |

This bracket is central to the gap: clean XFOIL is very low, while the existing rough XFOIL profile estimate alone is larger than the CFD-inferred profile/form residual.

## Spanwise XFOIL profile contribution

The table below is the clean/default profile integration. `dCD_profile` is the full-wing trapezoidal contribution normalized by `Sref=33.420059598 m^2`.

| eta | y_m | chord_m | Re | cl_AVL | airfoil | cd_XFOIL | dCD_profile |
|---:|---:|---:|---:|---:|---|---:|---:|
| 0.00000 | 0.000 | 1.2568 | 568130 | 1.2989 | dae31 | 0.00912 | 0.000004 |
| 0.00066 | 0.011 | 1.2564 | 567962 | 1.2989 | dae31 | 0.00912 | 0.000035 |
| 0.00591 | 0.102 | 1.2536 | 566696 | 1.2876 | dae31 | 0.00900 | 0.000091 |
| 0.01637 | 0.281 | 1.2481 | 564210 | 1.2894 | dae31 | 0.00903 | 0.000151 |
| 0.03193 | 0.548 | 1.2398 | 560458 | 1.2930 | dae31 | 0.00909 | 0.000209 |
| 0.05245 | 0.900 | 1.2288 | 555485 | 1.2982 | dae31 | 0.00917 | 0.000265 |
| 0.07772 | 1.334 | 1.2154 | 549427 | 1.3049 | dae31 | 0.00927 | 0.000319 |
| 0.10750 | 1.845 | 1.1995 | 542240 | 1.3130 | dae31 | 0.00939 | 0.000369 |
| 0.14151 | 2.429 | 1.1814 | 534058 | 1.3225 | dae31 | 0.00954 | 0.000398 |
| 0.17620 | 3.025 | 1.1627 | 525604 | 1.3293 | dae31 | 0.00966 | 0.000400 |
| 0.21078 | 3.618 | 1.1437 | 517015 | 1.3323 | dae31 | 0.00974 | 0.000411 |
| 0.24798 | 4.257 | 1.1233 | 507793 | 1.3355 | dae31 | 0.00982 | 0.000434 |
| 0.28743 | 4.934 | 1.1017 | 498029 | 1.3384 | dae31 | 0.00991 | 0.000453 |
| 0.32876 | 5.644 | 1.0790 | 487767 | 1.3408 | dae31 | 0.01002 | 0.000501 |
| 0.37770 | 6.484 | 1.0515 | 475336 | 1.3371 | dae31 | 0.01007 | 0.000573 |
| 0.43407 | 7.451 | 1.0194 | 460825 | 1.3255 | dae31 | 0.01003 | 0.000597 |
| 0.49126 | 8.433 | 0.9868 | 446088 | 1.3120 | dae31 | 0.01000 | 0.000552 |
| 0.54308 | 9.323 | 0.9565 | 432390 | 1.2917 | dae31 | 0.00990 | 0.000475 |
| 0.58901 | 10.111 | 0.9289 | 419914 | 1.2632 | dae31 | 0.00974 | 0.000424 |
| 0.63429 | 10.888 | 0.9017 | 407618 | 1.2301 | dae31 | 0.00961 | 0.000398 |
| 0.67846 | 11.646 | 0.8751 | 395593 | 1.1859 | dae31 | 0.00949 | 0.000372 |
| 0.72139 | 12.383 | 0.8484 | 383523 | 1.0858 | dae31 | 0.00930 | 0.000341 |
| 0.76265 | 13.092 | 0.8218 | 371499 | 0.9313 | dae31 | 0.00934 | 0.000316 |
| 0.80155 | 13.760 | 0.7968 | 360197 | 0.7787 | cst_tip_nsga2_g05_child_0032_70ef8136 | 0.01255 | 0.000405 |
| 0.84145 | 14.444 | 0.7701 | 348127 | 0.6734 | cst_tip_nsga2_g05_child_0032_70ef8136 | 0.01228 | 0.000388 |
| 0.88150 | 15.132 | 0.7422 | 335515 | 0.6205 | cst_tip_nsga2_g05_child_0032_70ef8136 | 0.00902 | 0.000249 |
| 0.91386 | 15.688 | 0.7189 | 324982 | 0.5766 | cst_tip_nsga2_g05_child_0032_70ef8136 | 0.00617 | 0.000131 |
| 0.93889 | 16.117 | 0.6999 | 316393 | 0.5317 | cst_tip_nsga2_g05_child_0032_70ef8136 | 0.00392 | 0.000064 |
| 0.95934 | 16.468 | 0.6828 | 308663 | 0.4785 | cst_tip_nsga2_g05_child_0032_70ef8136 | 0.00195 | 0.000025 |
| 0.97525 | 16.741 | 0.6680 | 301973 | 0.4103 | cst_tip_nsga2_g05_child_0032_70ef8136 | 0.00030 | 0.000003 |
| 0.98731 | 16.948 | 0.6568 | 296910 | 0.3187 | cst_tip_nsga2_g05_child_0032_70ef8136 | 0.00094 | 0.000006 |
| 0.99542 | 17.087 | 0.6493 | 293519 | 0.2031 | cst_tip_nsga2_g05_child_0032_70ef8136 | 0.00185 | 0.000008 |
| 0.99949 | 17.157 | 0.6455 | 291801 | 0.0706 | cst_tip_nsga2_g05_child_0032_70ef8136 | 0.00270 | 0.000004 |
| 1.00000 | 17.166 | 0.6450 | 291577 | 0.0706 | cst_tip_nsga2_g05_child_0032_70ef8136 | 0.00277 | 0.000000 |

## Engineering notes

- The profile drag contribution is dominated by the high-lift inboard and mid-span DAE31 stations. The DAE31 portion contributes `CD=0.008085455`; the tip CST portion contributes only `CD=0.001283396`.
- Several outboard clean XFOIL values are extremely low, including `cd=0.00030` at `eta=0.975`. Those values may be valid only under a clean laminar-bucket assumption. They should not be treated as rough, tripped, or manufacturing-realistic drag without a transition/roughness check.
- The old AVL induced term is a finite-wing inviscid induced drag term only. The old XFOIL profile term is a two-dimensional section profile drag integration. Mixing those is legitimate for the old low-order method, but adding AVL induced drag to OpenFOAM drag would double-count.
