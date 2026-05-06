# Phase 7 monotone-chord evaluation

Generated: 2026-05-06T11:14:53.926045+00:00

Scope: diagnostic comparison only. This pass used the already-exported Policy A/C original and monotone AVL/VSP geometries, reran a quick AVL trim to CL_req, reused the prior VSPAERO CL/CDi parity values from the Phase 7 parity audit, and re-integrated profile drag against the existing full-polar archive. It did not touch the running Tier 2 full-alpha database job, ranking, hard gates, Fourier settings, or CST/NSGA state.

## Geometry and aero summary
| policy | variant | chord_monotone_nonincreasing | max_positive_chord_jump_m | Sref_m2 | computed_area_m2 | AR | MAC_m | loaded_tip_z_m | alpha_at_CL_req_deg | CDi | e_CDi | target_vs_avl_rms | target_vs_avl_outer_delta | profile_cd | CD0_total_est | mission_drag_budget_band | min_stall_margin | max_station_utilization | local_cl_max_all_zones |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Policy A | original | no | 0.02548702 | 33.420058 | 33.420058 | 35.269413 | 0.99196609 | 1.05058163 | 4.83981000 | 0.01250230 | 0.98569309 | 0.05739733 | 0.11935750 | 0.01109720 | 0.01498708 | target | 1.16980041 | 0.90880614 | 1.34670000 |
| Policy A | monotone | yes | 0.00000000 | 33.420058 | 33.420058 | 35.269413 | 0.99175285 | 1.05058163 | 4.83035000 | 0.01248900 | 0.98674279 | 0.05501337 | 0.11844724 | 0.01109332 | 0.01498319 | target | 1.20421537 | 0.90706123 | 1.34760000 |
| Policy C | original | no | 0.02548702 | 33.420058 | 33.420058 | 35.269413 | 0.99196609 | 1.05058163 | 4.42230000 | 0.01250350 | 0.98559849 | 0.04845631 | 0.10305154 | 0.01152798 | 0.01541786 | target | 1.23371390 | 0.90382365 | 1.36430000 |
| Policy C | monotone | yes | 0.00000000 | 33.420058 | 33.420058 | 35.269413 | 0.99175285 | 1.05058163 | 4.41213000 | 0.01249480 | 0.98628475 | 0.04610497 | 0.10210611 | 0.01152483 | 0.01541471 | target | 1.26714558 | 0.90121742 | 1.36510000 |

## Monotone minus original deltas
| policy | delta_max_positive_chord_jump_m_monotone_minus_original | delta_CDi_monotone_minus_original | delta_e_CDi_monotone_minus_original | delta_target_vs_avl_rms_monotone_minus_original | delta_target_vs_avl_outer_delta_monotone_minus_original | delta_profile_cd_monotone_minus_original | delta_CD0_total_est_monotone_minus_original | delta_local_cl_max_all_zones_monotone_minus_original | delta_vsp_CDi_at_CL_req_monotone_minus_original |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Policy A | -0.02548702 | -0.00001330 | 0.00104970 | -0.00238396 | -0.00091026 | -0.00000389 | -0.00000389 | 0.00090000 | -0.00001881 |
| Policy C | -0.02548702 | -0.00000870 | 0.00068626 | -0.00235135 | -0.00094543 | -0.00000315 | -0.00000315 | 0.00080000 | -0.00001607 |

## Engineering read
- The original inverse-chord planform has two positive chord jumps, with the largest bump about 0.0255 m. Relative to roughly 0.94-0.97 m local chord, this is a small aerodynamic perturbation but a visible manufacturing/inspection blemish.
- The monotone variants preserve span, Sref, loaded tip z, airfoil assignment, and relative twist. The only intended change is a smoothed non-increasing chord distribution with nearly identical area.
- AVL CDi/e_CDi changes are below practical significance in this diagnostic pass. In both Policy A and Policy C, monotone chord is effectively neutral and slightly favorable in induced drag.
- Existing VSPAERO thin/VLM parity values show the same direction: monotone chord slightly lowers CDi at CL_req. VSPAERO CDo/CDtot are still excluded from the mission profile-drag budget.
- Profile-drag changes from the existing sidecar database are tiny. Local Cl risk does not increase in a meaningful way; the root/mid1/tip max Cl movements are small compared with the DAE11 and CST safe-clmax margins already audited.
