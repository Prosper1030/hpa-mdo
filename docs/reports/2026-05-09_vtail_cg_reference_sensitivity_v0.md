# V-tail / CG Reference Sizing Sensitivity V0

Candidate: `current_avl_compromise_conservative_closed`
Runner status: `completed`
Engineering verdict: `blocked_by_missing_cg_or_reference_moment`

## Scope

This is a bounded current-pathfinder V-tail sizing / aft-position / authority
sensitivity plus a CG / x_ac reference audit. It deliberately does not run rib
or rear-spar sensitivity, ASWing-lite, FEM, or tail-airfoil NSGA2.

## Required Math

```text
V_V = S_V l_V / (S_W b_W)
C_n_beta > C_n_beta_min
exists delta_V such that C_n(beta, delta_V) = 0
C_n_deltaV ~= [C_n(+Delta delta_V) - C_n(-Delta delta_V)] / (2 Delta delta_V)
C_l,V ~ Y_V z_V / (q S_W b_W)
SM ~= (x_np - x_cg) / cbar_W
SM ~= -C_m_alpha / C_L_alpha only if referenced about CG and convention verified
```

## Sensitivity Grid

- Output dir: `/Volumes/Samsung SSD/hpa-mdo/output/current_pathfinder_vtail_sensitivity_v0`
- Deck count: `45`
- S_V multipliers: `[1.0, 1.5, 2.0, 2.5, 3.0]`
- Aft shifts m: `[0.0, 0.5, 1.0]`
- z shifts m: `[0.0]`

## Case Summary

| case | V_V | C_n_beta | C_n_deltaV | C_l_beta | C_l_deltaV | signs | yaw-roll | status | warnings |
|---|---:|---:|---:|---:|---:|---|---|---|---|
| `sv1p0_xaft0p0_z0p0` | `0.010145` | `0.002236` | `0.035237` | `-0.239945` | `-0.001432` | `Cnb=expected_positive; CndV=finite_control_authority` | `Clb/Cnb=107.309928; ClDV/CnDV=0.04065; notes=['roll_sideslip_derivative_large_relative_to_yaw_stability']` | `completed` | `['low_V_V_directional_authority_risk', 'very_small_C_n_beta_return_to_tail_sizing']` |
| `sv1p0_xaft0p5_z0p0` | `0.010877` | `0.004683` | `0.037529` | `-0.24016` | `-0.001719` | `Cnb=expected_positive; CndV=finite_control_authority` | `Clb/Cnb=51.283365; ClDV/CnDV=0.045802; notes=['roll_sideslip_derivative_large_relative_to_yaw_stability']` | `completed` | `['low_V_V_directional_authority_risk', 'very_small_C_n_beta_return_to_tail_sizing']` |
| `sv1p0_xaft1p0_z0p0` | `0.011609` | `0.007156` | `0.040107` | `-0.240299` | `-0.002005` | `Cnb=expected_positive; CndV=finite_control_authority` | `Clb/Cnb=33.580073; ClDV/CnDV=0.05; notes=['roll_sideslip_derivative_large_relative_to_yaw_stability']` | `completed` | `['low_V_V_directional_authority_risk']` |
| `sv1p5_xaft0p0_z0p0` | `0.01541` | `0.009811` | `0.042685` | `-0.240304` | `-0.002005` | `Cnb=expected_positive; CndV=finite_control_authority` | `Clb/Cnb=24.493324; ClDV/CnDV=0.04698; notes=['roll_sideslip_derivative_large_relative_to_yaw_stability']` | `completed` | `[]` |
| `sv1p5_xaft0p5_z0p0` | `0.016508` | `0.012724` | `0.045837` | `-0.24054` | `-0.002005` | `Cnb=expected_positive; CndV=finite_control_authority` | `Clb/Cnb=18.904433; ClDV/CnDV=0.04375; notes=[]` | `completed` | `[]` |
| `sv1p5_xaft1p0_z0p0` | `0.017606` | `0.015688` | `0.048701` | `-0.240694` | `-0.002292` | `Cnb=expected_positive; CndV=finite_control_authority` | `Clb/Cnb=15.342555; ClDV/CnDV=0.047059; notes=[]` | `completed` | `[]` |
| `sv2p0_xaft0p0_z0p0` | `0.020802` | `0.014649` | `0.047842` | `-0.240551` | `-0.002005` | `Cnb=expected_positive; CndV=finite_control_authority` | `Clb/Cnb=16.420984; ClDV/CnDV=0.041916; notes=[]` | `completed` | `[]` |
| `sv2p0_xaft0p5_z0p0` | `0.022267` | `0.017859` | `0.050993` | `-0.240789` | `-0.002292` | `Cnb=expected_positive; CndV=finite_control_authority` | `Clb/Cnb=13.482782; ClDV/CnDV=0.044944; notes=[]` | `completed` | `[]` |
| `sv2p0_xaft1p0_z0p0` | `0.023731` | `0.021131` | `0.054431` | `-0.240947` | `-0.002578` | `Cnb=expected_positive; CndV=finite_control_authority` | `Clb/Cnb=11.402537; ClDV/CnDV=0.047368; notes=[]` | `completed` | `[]` |
| `sv2p5_xaft0p0_z0p0` | `0.026323` | `0.017875` | `0.050993` | `-0.240728` | `-0.002292` | `Cnb=expected_positive; CndV=finite_control_authority` | `Clb/Cnb=13.467301; ClDV/CnDV=0.044944; notes=[]` | `completed` | `[]` |
| `sv2p5_xaft0p5_z0p0` | `0.028154` | `0.021287` | `0.054431` | `-0.24096` | `-0.002578` | `Cnb=expected_positive; CndV=finite_control_authority` | `Clb/Cnb=11.319585; ClDV/CnDV=0.047368; notes=[]` | `completed` | `[]` |
| `sv2p5_xaft1p0_z0p0` | `0.029984` | `0.024763` | `0.057869` | `-0.241117` | `-0.002578` | `Cnb=expected_positive; CndV=finite_control_authority` | `Clb/Cnb=9.736987; ClDV/CnDV=0.044554; notes=[]` | `completed` | `[]` |
| `sv3p0_xaft0p0_z0p0` | `0.031972` | `0.020101` | `0.053285` | `-0.240858` | `-0.002578` | `Cnb=expected_positive; CndV=finite_control_authority` | `Clb/Cnb=11.982389; ClDV/CnDV=0.048387; notes=[]` | `completed` | `['large_vtail_area_screening_only']` |
| `sv3p0_xaft0p5_z0p0` | `0.034169` | `0.023658` | `0.057009` | `-0.241082` | `-0.002578` | `Cnb=expected_positive; CndV=finite_control_authority` | `Clb/Cnb=10.190295; ClDV/CnDV=0.045226; notes=[]` | `completed` | `['large_vtail_area_screening_only']` |
| `sv3p0_xaft1p0_z0p0` | `0.036365` | `0.027276` | `0.060447` | `-0.241236` | `-0.002865` | `Cnb=expected_positive; CndV=finite_control_authority` | `Clb/Cnb=8.844259; ClDV/CnDV=0.047393; notes=[]` | `completed` | `['large_vtail_area_screening_only']` |

## Directional Box Read

Some bounded variants have screening-level positive C_n_beta and finite C_n_deltaV, but this is not a pass/fail claim because no promoted C_n_beta_min, beta case, or yaw-roll coupling limit exists.
- `sv3p0_xaft1p0_z0p0`: V_V=`0.036365`, C_n_beta=`0.027276`, C_n_deltaV=`0.060447`
- `sv2p5_xaft1p0_z0p0`: V_V=`0.029984`, C_n_beta=`0.024763`, C_n_deltaV=`0.057869`
- `sv3p0_xaft0p5_z0p0`: V_V=`0.034169`, C_n_beta=`0.023658`, C_n_deltaV=`0.057009`
- `sv2p5_xaft0p5_z0p0`: V_V=`0.028154`, C_n_beta=`0.021287`, C_n_deltaV=`0.054431`
- `sv2p0_xaft1p0_z0p0`: V_V=`0.023731`, C_n_beta=`0.021131`, C_n_deltaV=`0.054431`

## CG / x_ac Reference Audit

- Overall: `blocked_by_missing_cg_or_reference_moment`
- Xref: `{'value_m': 0.246277, 'status': 'reference_only_not_aerodynamic_center', 'source': 'output/go_mode_main_wing_candidate/final_candidate_package/geometry_exports/avl_parity/current_avl_compromise_conservative_closed/current_avl_compromise_conservative_closed.avl:#Xref', 'engineering_read': 'AVL Xref is a coefficient reference, not x_ac_w or x_cg.'}`
- Xnp: `{'value_m': 0.694932, 'status': 'candidate_only_convention_not_verified', 'engineering_read': 'Neutral point candidate only. Use for static margin only after parser, axis, reference point, and sign convention are verified.'}`
- x_ac_w: `{'value_m': None, 'status': 'blocking_missing', 'engineering_read': 'Wing aerodynamic center remains missing unless explicit artifact exists.'}`
- x_cg: `{'value_m': None, 'status': 'blocking_missing', 'engineering_read': 'Aircraft CG/range remains missing unless explicit manifest exists.'}`
- moment reference: `{'status': 'reference_point_available_not_cg', 'engineering_read': 'Static margin cannot be claimed unless coefficients are referenced about CG, or x_np and x_cg are both available with verified convention.'}`
- mass manifest: `{'status': 'estimated_or_untracked_not_promoted', 'tracked_by_git': False, 'pilot_entry': {'m_kg': 56.0, 'xyz_m': [0.4, 0.0, -0.5], 'source': 'estimated'}, 'engineering_read': 'Estimated or ignored-output mass entries are useful clues, but they are not a promoted CG range or moment reference contract.'}`

## Engineering Read

The V-tail sensitivity is useful for seeing whether the current low V_V can be
moved in the right direction by bounded area/arm changes. Static margin and
longitudinal trim remain blocked until CG range, wing aerodynamic center or
verified neutral point convention, and moment reference are promoted. Passing
these script checks is not tailboom, pivot, hardware, manufacturing, or flight
sign-off.
