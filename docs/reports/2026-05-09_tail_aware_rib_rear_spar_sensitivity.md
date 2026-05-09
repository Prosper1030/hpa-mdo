# Tail-Aware Rib / Rear-Spar Sensitivity

Candidate: `current_avl_compromise_conservative_closed`
Verdict: `ready_for_tail_aware_aeroelastic_closure`

## Selected Basis

- case: `finite_rib_rear_0p50_selected_screening_basis`
- rib family: `balsa_sheet_3mm`; density `160.0` kg/m3; trust `baseline_legacy_screening`
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
- material source note: Existing repo baseline: balsa_sheet_3mm at 0.30 m target spacing; keep as the current pathfinder reference, not a final rib drawing.

## Material Family Sensitivity

Verdict: `foam_only_families_do_not_clear_current_aeroelastic_closure`

| family | density kg/m3 | thickness mm | mass kg | knockdown | GJ vs balsa | projected twist deg | closure verdict | trust |
|---|---:|---:|---:|---:|---:|---:|---|---|
| balsa_sheet_3mm | 160.000 | 3.00 | 3.030 | 0.502 | 1.000 | 5.414 | `baseline_not_ready_for_current_aeroelastic_closure` | `baseline_legacy_screening` |
| eps_hd_foam_cnc_10mm | 30.000 | 10.00 | 1.894 | 0.080 | 0.163 | 33.158 | `foam_only_not_selectable_for_current_aeroelastic_closure` | `low_screening_supplier_coupon_required` |
| xps_high_compressive_cnc_10mm | 32.000 | 10.00 | 2.020 | 0.080 | 0.163 | 33.158 | `foam_only_not_selectable_for_current_aeroelastic_closure` | `low_screening_supplier_coupon_required` |
| structural_foam_cnc_10mm | 60.000 | 10.00 | 3.787 | 0.291 | 0.581 | 9.320 | `foam_only_not_selectable_for_current_aeroelastic_closure` | `medium_screening_datasheet_like_supplier_coupon_required` |

Future note: Foam-only EPS/XPS/structural foam remain low-stiffness references; capped/hybrid foam and rear-spar shear-transfer scenarios are separate rework candidates.

Engineering read: foam-only families are evaluated as CNC-cut rib proxies only. No balsa leading edge, glass cap, or carbon cap stiffness credit is included in this v1 sensitivity.

## Stiffness Rework Candidates

Verdict: `ready_for_hybrid_rib_stiffness_rework`

| family | role | rear scale | GJ vs balsa | projected direct deg | projected bounded deg | candidate verdict |
|---|---|---:|---:|---:|---:|---|
| balsa_sheet_3mm | balsa_baseline | 0.50 | 1.000 | 5.414 | 3.256 | `candidate_rework_still_needs_more_stiffness_or_mapping` |
| balsa_sheet_3mm | balsa_baseline | 0.65 | 1.249 | 4.336 | 2.608 | `candidate_for_tail_aware_closure_rerun` |
| balsa_sheet_3mm | balsa_baseline | 0.75 | 1.404 | 3.856 | 2.320 | `candidate_for_tail_aware_closure_rerun` |
| eps_balsa_cap_hybrid_10mm | capped_hybrid_foam_rib | 0.50 | 1.628 | 3.326 | 2.001 | `candidate_for_tail_aware_closure_rerun` |
| eps_balsa_cap_hybrid_10mm | capped_hybrid_foam_rib | 0.65 | 2.033 | 2.663 | 1.602 | `candidate_for_tail_aware_closure_rerun` |
| eps_balsa_cap_hybrid_10mm | capped_hybrid_foam_rib | 0.75 | 2.286 | 2.368 | 1.424 | `candidate_for_tail_aware_closure_rerun` |
| structural_foam_glass_face_10mm | structural_foam_caps_faces | 0.50 | 1.834 | 2.952 | 1.776 | `candidate_for_tail_aware_closure_rerun` |
| structural_foam_glass_face_10mm | structural_foam_caps_faces | 0.65 | 2.290 | 2.364 | 1.422 | `candidate_for_tail_aware_closure_rerun` |
| structural_foam_glass_face_10mm | structural_foam_caps_faces | 0.75 | 2.576 | 2.102 | 1.264 | `candidate_for_tail_aware_closure_rerun` |

Engineering read: these are next-rerun stiffness families, not closure results. Foam-only rows above remain low-stiffness references and are not promoted by this table.

## Structural Cases

| case | status | blockers | rear scale | link | tip m | angle deg | link force N | wire N | EI ratio | GJ ratio |
|---|---|---|---:|---|---:|---:|---:|---:|---:|---:|
| joint_only_current_rear_1p00_not_selectable | `blocked` | `('physical_rib_station_basis_missing', 'finite_rib_link_basis_missing', 'rear_spar_participation_above_selection_bound', 'spar_pair_angle_delta_exceeds_screening_limit')` | 1.00 | `joint_only_offset_rigid` | 0.517 | 13.392 | 3055.2 | 1191.8 | 1.000 | 1.000 |
| finite_rib_rear_0p30_stress_case | `blocked` | `('rear_spar_participation_below_reasonable_screening_bound',)` | 0.30 | `dense_finite_rib` | 0.821 | 6.990 | 616.1 | 1498.9 | 0.403 | 0.361 |
| finite_rib_rear_0p50_selected_screening_basis | `pass_screening_sensitivity` | `()` | 0.50 | `dense_finite_rib` | 0.631 | 5.234 | 626.7 | 1194.3 | 0.599 | 0.568 |
| finite_rib_rear_0p65_confirmation | `pass_screening_sensitivity` | `()` | 0.65 | `dense_finite_rib` | 0.546 | 5.368 | 734.6 | 1042.2 | 0.732 | 0.709 |
| finite_rib_rear_0p75_shear_transfer_rework | `pass_screening_sensitivity` | `()` | 0.75 | `dense_finite_rib` | 0.503 | 5.329 | 796.8 | 963.3 | 0.814 | 0.797 |
| finite_rib_rear_1p00_upper_bound | `blocked` | `('rear_spar_participation_above_selection_bound',)` | 1.00 | `dense_finite_rib` | 0.425 | 5.054 | 934.5 | 817.6 | 1.000 | 1.000 |

## Engineering Boundary

- This is an engineering-screening basis for the next aeroelastic closure, not final FEM or hardware certification.
- The 0.30 m rib bay is only accepted because this report ties it to physical station count and mass bookkeeping.
- The selected rear-spar participation is bounded below the rigid 1.0 upper-bound case.
- Uncompensated tail/rib mass moves CG aft of the committed range; the selected basis requires explicit final-CG management before closure claims.
