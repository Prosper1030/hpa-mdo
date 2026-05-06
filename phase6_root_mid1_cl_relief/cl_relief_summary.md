# Root/Mid1 Cl Relief Sweep

## Baseline

Policy C is the mission-grade sidecar baseline: `root:cst_root_nsga2_g05_child_0019_00cc4dca|mid1:cst_mid1_nsga2_g06_child_0001_a86879e2|mid2:clarkysm|tip:clarkysm`.

| zone | Cl_min | Cl_p50 | Cl_p90 | Cl_max | eta_at_Cl_max |
|---|---:|---:|---:|---:|---:|
| root | 1.279500 | 1.314301 | 1.342142 | 1.349103 | 0.160000 |
| mid1 | 1.282542 | 1.321744 | 1.353105 | 1.360945 | 0.350000 |

DAE11 safe_clmax basis from the gap-fill audit is `1.487165`. Baseline Policy C root/mid1 max Cl is `1.360945`, so the actual Policy C AVL sidecar has `0.126220` Cl of DAE11 safe-clmax headroom.

Important distinction: the earlier `1.565775` root/mid1 requirement came from the full-polar/archive envelope used to grade DAE11, not from the current Policy C AVL sidecar distribution. Under Policy C actual AVL loading, root/mid1 demand is already below the DAE11 safe-clmax basis.

## Sweep Results

| variant | root/mid1 Cl_max | e_CDi | rms | outer_delta | profile_cd | CD0_total | band | stall_margin | max_util | DAE11 envelope pass |
|---|---:|---:|---:|---:|---:|---:|---|---:|---:|---|
| baseline_policy_c_geometry | 1.360945 | 0.986348 | 0.043662 | 0.090443 | 0.011397 | 0.015287 | target | 3.045471 | 0.824123 | True |
| local_chord_plus_3pct_root_mid1 | 1.338722 | 0.984304 | 0.045576 | 0.081424 | 0.011165 | 0.015000 | target | 3.203780 | 0.810346 | True |
| local_chord_plus_6pct_root_mid1 | 1.313956 | 0.981802 | 0.049153 | 0.071701 | 0.010949 | 0.014724 | target | 3.371432 | 0.796081 | True |
| inboard_twist_minus_0p5deg | 1.342781 | 0.986435 | 0.048542 | 0.104304 | 0.011444 | 0.015334 | target | 2.823211 | 0.811572 | True |
| inboard_twist_minus_1p0deg | 1.324717 | 0.984740 | 0.057219 | 0.120983 | 0.011505 | 0.015394 | target | 2.601934 | 0.799083 | True |
| local_cl_schedule_relief_small | 1.304807 | 0.982878 | 0.042952 | 0.068779 | 0.011063 | 0.014869 | target | 3.108356 | 0.789027 | True |
| local_cl_schedule_relief_strong | 1.266040 | 0.975668 | 0.052762 | 0.093503 | 0.010926 | 0.014698 | target | 3.021282 | 0.764471 | True |
| fourier_r3_more_negative | 1.358262 | 0.984029 | 0.043892 | 0.091381 | 0.011410 | 0.015319 | target | 3.025309 | 0.821896 | True |
| fourier_r3_r5_outer_shift | 1.293779 | 0.966072 | 0.041798 | 0.073448 | 0.011152 | 0.015008 | target | 2.890533 | 0.780366 | True |

## Findings

- Best Cl relief: `local_cl_schedule_relief_strong` with root/mid1 Cl_max `1.266040` (-0.094905 vs baseline).
- Best Policy C profile Cd: `local_cl_schedule_relief_strong` with profile_cd `0.010926` (-0.000470 vs baseline).
- DAE11 envelope check: the following variants drop root/mid1 Cl below the DAE11 safe_clmax basis: `baseline_policy_c_geometry`, `local_chord_plus_3pct_root_mid1`, `local_chord_plus_6pct_root_mid1`, `inboard_twist_minus_0p5deg`, `inboard_twist_minus_1p0deg`, `local_cl_schedule_relief_small`, `local_cl_schedule_relief_strong`, `fourier_r3_more_negative`, `fourier_r3_r5_outer_shift`.
- DAE11 archive sidecar source quality remains `not_mission_grade_sidecar` in this study because no archive re-score or quality-gate change was made. The envelope-pass flag only answers whether the previous safe-clmax margin failure would be removed by the variant Cl demand.
- Local chord and inverse-chord Cl-schedule relief reduce Policy C profile Cd; inboard twist relief lowers Cl but slightly worsens profile Cd and target-match metrics. The mild pure Fourier r3 change barely relieves root/mid1 Cl, while the stronger r3/r5 plus control shift relieves Cl at a visible e_CDi cost.
- This is a shadow/no-ranking study. All AVL and profile-drag outputs are diagnostics and do not alter main aircraft ranking or hard gates.
