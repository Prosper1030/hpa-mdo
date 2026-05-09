# Tail-Aware Rib / Rear-Spar Sensitivity

Candidate: `current_avl_compromise_conservative_closed`
Verdict: `ready_for_tail_aware_aeroelastic_closure`

## Selected Basis

- case: `finite_rib_rear_0p50_selected_screening_basis`
- rib spacing / bay: `0.3` m target; max materialized subbay `0.297063` m
- rib count basis: `121` full-wing ribs/stations
- rear spar participation: `bounded_50pct_screening`
- warping knockdown: `0.50246`
- EI/GJ ratios vs finite-rib rear=1.0 upper bound: `EI 0.599`, `GJ 0.568`
- structural / aircraft mass deltas: rib `3.029671` kg, tail `1.172727` kg, rear spar `0.0` kg
- CG status: `final_cg_screening_row_remains_available_with_rebalance`; uncompensated CG `0.801026` m; required forward rebalance `0.091302` m on `56.0` kg
- tail margins: SM `0.088378` MAC, delta_H reserve `5.673498` deg, C_n_beta min `0.016153`
- load remap: `conserved`
- closure ranking: `no_change_conservative_best_remains_screening_closed`

## Structural Cases

| case | status | blockers | rear scale | link | tip m | angle deg | link force N | wire N | EI ratio | GJ ratio |
|---|---|---|---:|---|---:|---:|---:|---:|---:|---:|
| joint_only_current_rear_1p00_not_selectable | `blocked` | `('physical_rib_station_basis_missing', 'finite_rib_link_basis_missing', 'rear_spar_participation_above_selection_bound', 'spar_pair_angle_delta_exceeds_screening_limit')` | 1.00 | `joint_only_offset_rigid` | 0.517 | 13.392 | 3055.2 | 1191.8 | 1.000 | 1.000 |
| finite_rib_rear_0p30_stress_case | `blocked` | `('rear_spar_participation_below_reasonable_screening_bound',)` | 0.30 | `dense_finite_rib` | 0.821 | 6.990 | 616.1 | 1498.9 | 0.403 | 0.361 |
| finite_rib_rear_0p50_selected_screening_basis | `pass_screening_sensitivity` | `()` | 0.50 | `dense_finite_rib` | 0.631 | 5.234 | 626.7 | 1194.3 | 0.599 | 0.568 |
| finite_rib_rear_0p65_confirmation | `pass_screening_sensitivity` | `()` | 0.65 | `dense_finite_rib` | 0.546 | 5.368 | 734.6 | 1042.2 | 0.732 | 0.709 |
| finite_rib_rear_1p00_upper_bound | `blocked` | `('rear_spar_participation_above_selection_bound',)` | 1.00 | `dense_finite_rib` | 0.425 | 5.054 | 934.5 | 817.6 | 1.000 | 1.000 |

## Engineering Boundary

- This is an engineering-screening basis for the next aeroelastic closure, not final FEM or hardware certification.
- The 0.30 m rib bay is only accepted because this report ties it to physical station count and mass bookkeeping.
- The selected rear-spar participation is bounded below the rigid 1.0 upper-bound case.
- Uncompensated tail/rib mass moves CG aft of the committed range; the selected basis requires explicit final-CG management before closure claims.
