# Phase 6 Root/Mid Zone Requirement Sanity Audit

This audit keeps CST degree, seedless bounds, and stall defaults unchanged. It asks whether the current root/mid local CL demand is compatible with historical low-Re sections before changing the optimizer.

## Design Point Source

Production zone requirements are built from `SpanwiseLoad` and stations via `src/hpa_mdo/concept/zone_requirements.py::build_zone_requirements`, then attached to concept evaluation in `src/hpa_mdo/concept/pipeline.py`. This Phase 6 artifact uses the same representative station rows embedded by Phase 4/5 in `scripts/audit_seedless_selection_behavior.py::build_reference_zone_requirements` so the audit is reproducible without rerunning AVL.

| zone | y_range_m | re_min | re_max | cl_min | cl_mean | cl_max | cl_target_samples | xfoil_representative_re | xfoil_target_cl_samples | source_file_function |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| root | 0.000-2.778 | 4.5234e+05 | 5.4448e+05 | 1.1558 | 1.3027 | 1.3698 | 1.156, 1.370 | 4.8e+05 | 1.16, 1.37 | production: src/hpa_mdo/concept/zone_requirements.py::build_zone_requirements; phase6 artifact: scripts/audit_seedless_selection_behavior.py::build_reference_zone_requirements |
| mid1 | 6.077-9.029 | 3.7434e+05 | 3.9724e+05 | 1.396 | 1.4314 | 1.4657 | 1.466, 1.396 | 3.85e+05 | 1.40, 1.47 | production: src/hpa_mdo/concept/zone_requirements.py::build_zone_requirements; phase6 artifact: scripts/audit_seedless_selection_behavior.py::build_reference_zone_requirements |
| mid2 | 12.155-12.155 | 3.4814e+05 | 3.4814e+05 | 1.2235 | 1.2235 | 1.2235 | 1.224 | 3.5e+05 | 1.22 | production: src/hpa_mdo/concept/zone_requirements.py::build_zone_requirements; phase6 artifact: scripts/audit_seedless_selection_behavior.py::build_reference_zone_requirements |
| tip | 14.239-16.496 | 2.651e+05 | 3.2971e+05 | 0.66526 | 0.89607 | 1.0119 | 1.012, 0.807, 0.665 | 3.15e+05 | 0.67, 0.81, 1.01 | production: src/hpa_mdo/concept/zone_requirements.py::build_zone_requirements; phase6 artifact: scripts/audit_seedless_selection_behavior.py::build_reference_zone_requirements |

## Stall Gate Math

| item | current_formula_value | source_file_function | notes |
| --- | --- | --- | --- |
| safe_clmax source | raw usable_clmax comes from XFOIL full_alpha_sweep; robust aggregate uses min usable_clmax across successful Re/roughness conditions | src/hpa_mdo/concept/airfoil_selection.py::_aggregate_worker_condition_metrics | Phase 6 tables split clean and rough raw clmax before this min aggregation. |
| safe_clmax model | safe = max(0.10, adjusted_scale*raw - adjusted_delta - tip_3d_penalty); airfoil_observed adjusted_scale=0.92, adjusted_delta=0.04 | src/hpa_mdo/concept/stall_model.py::compute_safe_local_clmax | Config values are safe_clmax_scale=0.90 and safe_clmax_delta=0.05 before airfoil_observed adjustment. |
| local utilization gate | utilization = cl_target / safe_clmax; pass when utilization <= 0.75 | src/hpa_mdo/concept/airfoil_selection.py::_zone_candidate_metrics | worst_case_margin = case_limit - utilization; hard gate fails when margin < 0. |
| clean vs rough | production factors=(0.85, 1.0, 1.15), roughness_modes=('clean', 'rough') | src/hpa_mdo/concept/airfoil_selection.py::_zone_queries_for_candidates | Clean uses ncrit=9 xtrip=(1,1); rough uses ncrit=5 xtrip=(0.05,0.05). |
| XFOIL sweep range | full_alpha_sweep alpha = -4:0.5:alpha_max; alpha_max = min(18, max(12, 5 + 14*max_abs_cl_sample)) | tools/julia/xfoil_worker/xfoil_worker.jl::alpha_grid | Root/mid target CL pushes alpha_max to the 18 deg cap; clmax_is_lower_bound flags are reported. |
| target CL samples | XFOIL cl_samples are unique zone cl_target values rounded to 0.01; Re is a weighted representative zone Reynolds rounded to 5000 | src/hpa_mdo/concept/airfoil_selection.py::_zone_queries_for_candidates | Station Re min/max are retained in the requirement table but not queried one-by-one. |

## Phase 5 Seedless Feasibility Context

These rows are read from the existing Phase 5 artifact; Phase 6 does not rerun a seedless campaign.

| scale | zone | feasible_geometry_candidates | coarse_scored | robust_scored | hard_gate_pass_count | stall_pass_count | cm_pass_count | tc_pass_count | spar_pass_count | best_stall_margin | dominant_failures |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| medium | root | 511 | 64 | 16 | 0 | 0 | 62 | 64 | 64 | -0.08569119138746606 | stall:64; cm:2 |
| medium | mid1 | 512 | 64 | 16 | 0 | 0 | 61 | 64 | 64 | -0.181721771206369 | stall:64; cm:3 |
| medium | mid2 | 512 | 64 | 16 | 0 | 0 | 64 | 64 | 64 | -0.11218328950691636 | stall:64 |
| medium | tip | 512 | 64 | 16 | 1 | 1 | 64 | 64 | 64 | 0.016492084724282874 | stall:63 |

## Historical Root/Mid Stall Feasibility

| zone | airfoil | point | Re | cl_target | clean_clmax | rough_clmax | safe_clmax | utilization | required_utilization_limit | pass_fail | status | tc | tc_pass | mean_cm | cm_pass |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| root | FX 76-MP-140 | 1 | 5.4448e+05 | 1.1558 | 1.807 | 1.695 | 1.5194 | 0.76065 | 0.75 | fail | ok | 0.14065 | True | -0.20671 | False |
| root | FX 76-MP-140 | 2 | 4.5234e+05 | 1.3698 | 1.807 | 1.695 | 1.5194 | 0.90153 | 0.75 | fail | ok | 0.14065 | True | -0.20671 | False |
| root | DAE11 | 1 | 5.4448e+05 | 1.1558 | 1.6105 | 1.5358 | 1.3729 | 0.84181 | 0.75 | fail | ok | 0.12874 | False | -0.12535 | True |
| root | DAE11 | 2 | 4.5234e+05 | 1.3698 | 1.6105 | 1.5358 | 1.3729 | 0.99773 | 0.75 | fail | ok | 0.12874 | False | -0.12535 | True |
| root | DAE21 | 1 | 5.4448e+05 | 1.1558 | 1.6149 | 1.5983 | 1.4305 | 0.80795 | 0.75 | fail | ok | 0.11818 | False | -0.1431 | True |
| root | DAE21 | 2 | 4.5234e+05 | 1.3698 | 1.6149 | 1.5983 | 1.4305 | 0.95759 | 0.75 | fail | ok | 0.11818 | False | -0.1431 | True |
| root | DAE31 | 1 | 5.4448e+05 | 1.1558 | 1.639 | 1.6241 | 1.4542 | 0.79477 | 0.75 | fail | ok | 0.1109 | False | -0.15331 | True |
| root | DAE31 | 2 | 4.5234e+05 | 1.3698 | 1.639 | 1.6241 | 1.4542 | 0.94198 | 0.75 | fail | ok | 0.1109 | False | -0.15331 | True |
| root | DAE41 | 1 | 5.4448e+05 | 1.1558 | 1.3602 | 1.3816 | 1.2114 | 0.95409 | 0.75 | fail | ok | 0.11701 | False | -0.033148 | True |
| root | DAE41 | 2 | 4.5234e+05 | 1.3698 | 1.3602 | 1.3816 | 1.2114 | 1.1308 | 0.75 | fail | ok | 0.11701 | False | -0.033148 | True |
| mid1 | FX 76-MP-140 | 1 | 3.9724e+05 | 1.4657 | 1.8001 | 1.6726 | 1.4988 | 0.97792 | 0.75 | fail | ok | 0.14065 | True | -0.20534 | False |
| mid1 | FX 76-MP-140 | 2 | 3.7434e+05 | 1.396 | 1.8001 | 1.6726 | 1.4988 | 0.93142 | 0.75 | fail | ok | 0.14065 | True | -0.20534 | False |
| mid1 | DAE11 | 1 | 3.9724e+05 | 1.4657 | 1.6101 | 1.5139 | 1.3528 | 1.0835 | 0.75 | fail | ok | 0.12874 | True | -0.12603 | True |
| mid1 | DAE11 | 2 | 3.7434e+05 | 1.396 | 1.6101 | 1.5139 | 1.3528 | 1.0319 | 0.75 | fail | ok | 0.12874 | True | -0.12603 | True |
| mid1 | DAE21 | 1 | 3.9724e+05 | 1.4657 | 1.6119 | 1.5759 | 1.4098 | 1.0396 | 0.75 | fail | ok | 0.11818 | True | -0.1404 | True |
| mid1 | DAE21 | 2 | 3.7434e+05 | 1.396 | 1.6119 | 1.5759 | 1.4098 | 0.99021 | 0.75 | fail | ok | 0.11818 | True | -0.1404 | True |
| mid1 | DAE31 | 1 | 3.9724e+05 | 1.4657 | 1.6326 | 1.5999 | 1.4319 | 1.0236 | 0.75 | fail | ok | 0.1109 | True | -0.13721 | True |
| mid1 | DAE31 | 2 | 3.7434e+05 | 1.396 | 1.6326 | 1.5999 | 1.4319 | 0.97492 | 0.75 | fail | ok | 0.1109 | True | -0.13721 | True |
| mid1 | DAE41 | 1 | 3.9724e+05 | 1.4657 | 1.3426 | 1.3493 | 1.1952 | 1.2263 | 0.75 | fail | ok | 0.11701 | True | -0.0094046 | True |
| mid1 | DAE41 | 2 | 3.7434e+05 | 1.396 | 1.3426 | 1.3493 | 1.1952 | 1.168 | 0.75 | fail | ok | 0.11701 | True | -0.0094046 | True |
| mid2 | FX 76-MP-140 | 1 | 3.4814e+05 | 1.2235 | 1.7998 | 1.6631 | 1.4835 | 0.82473 | 0.75 | fail | ok | 0.14065 | True | -0.2017 | False |
| mid2 | DAE11 | 1 | 3.4814e+05 | 1.2235 | 1.6145 | 1.5061 | 1.3392 | 0.91364 | 0.75 | fail | ok | 0.12874 | True | -0.1253 | True |
| mid2 | DAE21 | 1 | 3.4814e+05 | 1.2235 | 1.6108 | 1.5663 | 1.3945 | 0.87741 | 0.75 | fail | ok | 0.11818 | True | -0.14306 | True |
| mid2 | DAE31 | 1 | 3.4814e+05 | 1.2235 | 1.6311 | 1.5935 | 1.4195 | 0.86192 | 0.75 | fail | ok | 0.1109 | True | -0.15518 | True |
| mid2 | DAE41 | 1 | 3.4814e+05 | 1.2235 | 1.3349 | 1.3351 | 1.1816 | 1.0355 | 0.75 | fail | ok | 0.11701 | True | -0.038055 | True |

## Best Historical Utilization

| zone | best_historical_airfoil | best_utilization | best_safe_clmax | best_status | current_pass_count |
| --- | --- | --- | --- | --- | --- |
| root | FX 76-MP-140 | 0.90153 | 1.5194 | ok | 0 |
| mid1 | FX 76-MP-140 | 0.97792 | 1.4988 | ok | 0 |
| mid2 | FX 76-MP-140 | 0.82473 | 1.4835 | ok | 0 |
| tip | FX 76-MP-140 | 0.6925 | 1.4533 | ok | 3 |

## Counterfactual Sweeps

| scenario | root_pass_count | mid1_pass_count | mid2_pass_count | tip_pass_count | interpretation |
| --- | --- | --- | --- | --- | --- |
| A utilization <= 0.75 | 0 | 0 | 0 | 3 | Threshold-only sweep on historical reference set. |
| A utilization <= 0.80 | 0 | 0 | 0 | 4 | Threshold-only sweep on historical reference set. |
| A utilization <= 0.85 | 0 | 0 | 1 | 4 | Threshold-only sweep on historical reference set. |
| A utilization <= 0.90 | 0 | 0 | 3 | 5 | Threshold-only sweep on historical reference set. |
| B clean-only clmax | 0 | 0 | 0 | 4 | Checks whether rough-mode robust min is the blocker. |
| B rough-only clmax | 0 | 0 | 0 | 3 | Checks whether rough-mode robust min is the blocker. |
| B min(clean,rough) clmax | 0 | 0 | 0 | 3 | Checks whether rough-mode robust min is the blocker. |
| B 70/30 clean/rough clmax | 0 | 0 | 0 | 4 | Checks whether rough-mode robust min is the blocker. |
| C mean zone cl | 0 | 0 | 0 | 5 | Checks whether a high local station dominates the zone representative demand. |
| C 75% quantile zone cl | 0 | 0 | 0 | 4 | Checks whether a high local station dominates the zone representative demand. |
| C max station cl | 0 | 0 | 0 | 3 | Checks whether a high local station dominates the zone representative demand. |
| C scoring-weighted zone cl | 0 | 0 | 0 | 4 | Checks whether a high local station dominates the zone representative demand. |
| D cruise speed +5% | 0 | 0 | 1 | 4 | Demand-only approximation: cl_target scales with W/V^2; XFOIL clmax was not rerun at the scaled Reynolds. |
| D cruise speed +10% | 1 | 0 | 3 | 5 | Demand-only approximation: cl_target scales with W/V^2; XFOIL clmax was not rerun at the scaled Reynolds. |
| D weight -5% | 0 | 0 | 0 | 4 | Demand-only approximation: cl_target scales with W/V^2; XFOIL clmax was not rerun at the scaled Reynolds. |
| D weight +5% | 0 | 0 | 0 | 1 | Demand-only approximation: cl_target scales with W/V^2; XFOIL clmax was not rerun at the scaled Reynolds. |

## Engineering Judgment

- Root/mid fail is primarily a local-CL demand versus safe-clmax contract issue, not a CST coverage issue. The Phase 5 seedless set and the historical references both fail root/mid mainly by stall utilization.
- The most effective counterfactual in this historical-reference set is demand reduction from speed +10%: it recovers one root reference and three mid2 references, while mid1 still has zero passes. The mean/weighted CL representative-point tests mainly help the tip; they do not rescue root or mid1 at the current 0.75 utilization limit.
- Rough mode is not the sole cause. Clean-only helps tip count but leaves root/mid at zero passes, so the blocker is not just forced transition being too conservative.
- A fixed 0.75 utilization limit across root and tip may be overly blunt for stall sequencing. From an aircraft-design perspective, tip should usually retain the stricter margin; root/mid may tolerate higher utilization only if 3D screening confirms root-first stall, acceptable trim, and enough maneuver margin.
- Root remains a special conflict zone: `t/c >= 0.14`, high local CL, and Cm limit can reject historically plausible thin sections even when their aerodynamics are otherwise useful.
- Tip/outboard sanity remains intact in the historical reference set: DAE21 and DAE31 pass the current tip stall utilization check, so the evidence still points inward rather than to a global XFOIL or CST failure.
- Do not relax the default stall gate from this audit alone. First inspect the 3D loading source: twist, chord, spanload target, and whether the zone representative CL should be max-station or weighted mission demand.
- Limited 3D combination screening can proceed for outboard/tip and as a diagnostic for root/mid, but root/mid should carry `NO FEASIBLE CANDIDATE` or `infeasible_best_effort` labels until the loading/gate contract is settled.

## Artifacts

- `root_mid_design_points_phase6.csv`
- `root_mid_stall_formula_phase6.csv`
- `root_mid_historical_stall_feasibility_phase6.csv`
- `root_mid_counterfactuals_phase6.csv`
- `run_summary_phase6.json`

Worker result count: 120
