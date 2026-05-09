# Full-Aircraft Tail AVL Audit V0

Candidate: `current_avl_compromise_conservative_closed`
Runner status: `completed`
Engineering verdict: `blocked_by_directional_stability_or_vtail_authority`

## Scope

This artifact instantiates the current pathfinder wing with all-moving H-tail
and V-tail geometry sweeps. It does not use AVL hinged CONTROL lines as the
production representation of the all-moving tails.

## Required Math

```text
r_H' = r_p,H + R_pitch(delta_H) * (r_H - r_p,H)
r_V' = r_p,V + R_yaw(delta_V) * (r_V - r_p,V)
C_m_deltaH ~= [C_m(+Delta delta_H) - C_m(-Delta delta_H)] / (2 Delta delta_H)
C_n_deltaV ~= [C_n(+Delta delta_V) - C_n(-Delta delta_V)] / (2 Delta delta_V)
CL(alpha, delta_H) = W / (q S)
Cm(alpha, delta_H, x_cg) = 0
C_m_alpha < 0
SM ~= -C_m_alpha / C_L_alpha, if referenced about CG and conventions verified
C_n_beta > C_n_beta_min
exists delta_V such that C_n(beta, delta_V) = 0
C_l,V ~ Y_V z_V / (q S_W b_W)
```

## Artifact Manifest

- Output dir: `/Volumes/Samsung SSD/hpa-mdo/output/current_pathfinder_tail_avl_audit_v0`
- Deck count: `9`

## Parser Note

- `C_n_beta` is extracted from AVL's stability-axis `z' mom. Cn'` row, not from
  the later spiral diagnostic ratio line `Clb Cnr / Clr Cnb = ...`.

## Longitudinal Trim Screening

- Status: `blocked_by_missing_cg_or_x_ac`
- CL_required: `1.141757`
- delta_H_required: `{'status': 'blocked_by_missing_cg_or_x_ac', 'reason': 'CG range or wing aerodynamic center is missing; Cm=0 cannot be claimed.'}`
- H-tail CL utilization: `{'status': 'missing_tail_CLmax', 'reason': 'No current H-tail safe CLmax polar is promoted.'}`
- C_m_deltaH: `-2.619993`

## Static Stability

- C_m_alpha: `-2.766096`
- Static margin: `{'status': 'missing_reference_moment_or_cg', 'reason': 'CG reference and wing AC are not promoted.'}`

## Directional / V-Tail Screening

- Status: `blocked_by_directional_stability_or_vtail_authority`
- V_V: `0.010145`
- C_n_beta: `0.002236`
- C_n_deltaV: `0.035237`
- C_l_beta: `-0.239945`
- C_l_deltaV: `-0.001432`
- yaw-roll coupling warning: `{'formula': 'C_l,V ~ Y_V z_V / (q S_W b_W)', 'status': 'warning_not_limit_checked'}`
- warnings: `['low_V_V_directional_authority_risk', 'very_small_C_n_beta_return_to_tail_sizing']`

## Tail Load Envelope Placeholder

`{'status': 'placeholder_not_sized', 'required_next_input': 'tail strip/surface loads, pivot moments, tail mass model'}`

## Blockers

- `reference.cg_range_x_m_or_reference.wing.x_ac_w_m`: CG range or wing aerodynamic center is missing.
- `directional_stability_or_vtail_authority`: Directional derivative or all-moving V-tail authority is missing or weak.

## Engineering Read

Passing tests or producing AVL derivatives is not aircraft sign-off. CG range,
wing aerodynamic center, reference moment convention, tail CL/CY limits, tail
drag/mass, tailboom loads, pivot loads, and hardware load paths remain outside
this v0 audit unless explicitly populated above.
