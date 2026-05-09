# Tail / CG / Trim / Stability Screening V1

Candidate: `current_avl_compromise_conservative_closed`
Verdict: `ready_for_tail_aware_rib_rear_spar_sensitivity`
Runner status: `completed`

## Screening Contract

- CG range: `[0.68, 0.75]` m
- Moment reference: AVL `Xref` is explicitly set to each row CG.
- Xnp use gate: `Xnp = Xref - Cma/CLa*Cref` must close within tolerance.
- This is screening evidence, not measured CG, tail polar, FEM, or hardware sign-off.

## Selected Geometry

- H-tail: `{'S_H_m2': 4.5, 'span_m': 4.0, 'mean_chord_m': 1.125, 'x_le_m': 8.0, 'x_ac_H_m': 8.28125, 'l_H_m': 8.034973, 'V_H': 1.077895}`
- V-tail: `{'S_V_m2': 3.36, 'height_or_span_m': 2.4, 'mean_chord_m': 1.4, 'x_le_m': 8.0, 'x_ac_V_m': 8.35, 'l_V_m': 8.103723, 'V_V': 0.023731}`

## Margins

- Worst static margin: `0.088378` MAC
- Max |delta_H|: `9.326502` deg
- Worst H-tail deflection reserve: `5.673498` deg
- Max |delta_V| at beta screen: `3.931878` deg
- Worst V-tail deflection reserve: `16.068122` deg

## CG Rows

| CG x m | status | SM | alpha deg | delta_H deg | Cn_beta | delta_V deg | blockers |
|---:|---|---:|---:|---:|---:|---:|---|
| `0.68` | `pass_screening` | `0.158254` | `-0.508691` | `7.98285` | `0.016896` | `-3.931878` | `[]` |
| `0.72` | `pass_screening` | `0.118325` | `-0.567954` | `8.750639` | `0.016471` | `-3.854389` | `[]` |
| `0.75` | `pass_screening` | `0.088378` | `-0.612404` | `9.326502` | `0.016153` | `-3.779974` | `[]` |

## Tail Drag / Mass Treatment

`{'status': 'screening_delta_not_charged_to_candidate_truth', 'tail_profile_cd0_assumption': 0.01, 'baseline_tail_mass_kg_assumption': 2.4, 'baseline_tail_area_m2': 5.28, 'selected_tail_area_m2': 7.86, 'selected_tail_mass_kg_estimate': 3.572727, 'tail_mass_delta_kg_estimate': 1.172727, 'tail_cd0_increment_estimate': 0.002352, 'tail_profile_power_increment_w_estimate': 13.33234, 'cg_coupling_warning': 'Selected tail mass is aft of the wing reference. Keep the next sensitivity inside the recommended CG range or rerun this screen with the aft-shifted CG; do not silently add tail mass and keep the same stability claim.', 'engineering_read': 'Use as a screening penalty in the next sensitivity. It is not a measured tail structural mass, pivot mass, or full trim-induced drag model.'}`

## Mass / CG Clue

`{'status': 'estimated_clue_not_promoted_truth', 'path': '/Volumes/Samsung SSD/hpa-mdo/configs/blackcat_004.yaml', 'point_mass_total_kg': 83.95, 'point_mass_cg_x_m': 0.810822, 'target_total_mass_kg': 96.0, 'remainder_mass_kg': 12.05, 'remainder_x_m_assumption': 0.35, 'target_total_cg_x_m_clue': 0.752979, 'engineering_read': 'This tracked M14 estimate suggests the current CG may be around the upper screening range, but it is not a current pathfinder measured CG manifest.'}`

## Engineering Read

This establishes a bounded screening basis for tail-aware rib / rear-spar
sensitivity only if that next study carries CG as an explicit input range and
charges the screening tail drag/mass penalty. It does not prove the aircraft
is final-design feasible.
