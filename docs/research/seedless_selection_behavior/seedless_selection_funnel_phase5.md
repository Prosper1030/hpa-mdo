# Phase 5 Seedless CST Selection Funnel Audit

This is the post-patch audit for the seedless CST selection funnel. It is intentionally narrow: no CST degree change, no N1/N2 change, and no stall-gate relaxation.

## Funnel Controls

| Stage | Current count/limit | Source file | Function/config | Notes |
| --- | --- | --- | --- | --- |
| seedless_sample_count | baseline 1024 / smoke 128 | configs/birdman_upstream_concept_baseline.yaml | cst_search.seedless_sample_count | Sobol geometry pool; not equal to XFOIL-scored count. |
| Sobol feasible geometry candidates | up to sample_count after geometry prescreen | src/hpa_mdo/concept/airfoil_selection.py | _prepare_zone_selection_inputs | Caches by zone, min t/c, TE min, sample count, seed, oversample. |
| coarse screening candidate count | smoke 12 / medium 64 / production 96 | src/hpa_mdo/concept/airfoil_selection.py | coarse_score_count -> _coarse_seed_candidates | Phase 4 fallback was stride-derived 12 for seedless pools. |
| robust-stage candidate count | smoke 3 / medium 16 / production 24 | src/hpa_mdo/concept/airfoil_selection.py | robust_score_count | Promotes this many coarse-ranked candidates into robust clean/rough scoring. |
| clean/rough + Re factors scoring | production 3 Re x 2 roughness | configs/birdman_upstream_concept_baseline.yaml | robust_reynolds_factors, robust_roughness_modes | Smoke keeps Re=[1.0] and clean only. |
| hard gate | stall, t/c, spar depth, Cm | src/hpa_mdo/concept/airfoil_selection.py | _score_available_zone_candidates, select_best_zone_candidate | Hard-gate pass candidates sort ahead of infeasible candidates. |
| selected candidates | 1 per zone, or infeasible_best_effort label | src/hpa_mdo/concept/airfoil_selection.py | SelectedZoneCandidate.selection_status | No feasible zone is explicitly marked instead of treated as a normal selected airfoil. |

## Old vs New Funnel

- Phase 4 behavior: production-probe `1024 -> 12 coarse -> 3 robust-stage` per zone.
- Phase 5 production behavior: `1024 -> 96 coarse -> 24 robust-stage` per zone.
- Smoke behavior remains intentionally small: `128 -> 12 -> 3`, and CI tests do not run a production XFOIL campaign.
- Medium dry-run behavior is `512 -> 64 -> 16` for a more useful local probe.
- In this recorded Phase 5 run the completed XFOIL audit scale is `medium`. Full all-zone `production-probe` was attempted but the 1024-sample feasible Sobol generation was too slow for an interactive audit turn; keep it as a formal campaign scale, not a pytest/smoke job.

## Dry-Run Counts

| scale | zone | requested_sample_count | coarse_score_count_limit | robust_score_count_limit | candidate_pool_count | coarse_evaluated_count | robust_stage_candidate_count | scored_candidate_count |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| medium | root | 512 | 64 | 16 | 511 | 64 | 16 | 64 |
| medium | mid1 | 512 | 64 | 16 | 512 | 64 | 16 | 64 |
| medium | mid2 | 512 | 64 | 16 | 512 | 64 | 16 | 64 |
| medium | tip | 512 | 64 | 16 | 512 | 64 | 16 | 64 |

## Root/Mid Feasibility

| zone | feasible_geometry_candidates | coarse_scored | robust_scored | hard_gate_pass_count | stall_pass_count | cm_pass_count | tc_pass_count | spar_pass_count | best_stall_margin | best_hard_gate_pass_score | dominant_failures |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| root | 511 | 64 | 16 | 0 | 0 | 62 | 64 | 64 | -0.085691 |  | stall:64; cm:2 |
| mid1 | 512 | 64 | 16 | 0 | 0 | 61 | 64 | 64 | -0.18172 |  | stall:64; cm:3 |
| mid2 | 512 | 64 | 16 | 0 | 0 | 64 | 64 | 64 | -0.11218 |  | stall:64 |

## Stall Gate / Design Point Audit

| zone | cl_target_range | re_range | required_stall_margin | historical_best_safe_clmax | historical_pass_fail | likely_issue |
| --- | --- | --- | --- | --- | --- | --- |
| root | 1.156-1.370 | 452-544k | utilization <= 0.75 | 1.5194 | 0/3 pass | root t/c gate plus high CL demand rejects thin historical references |
| mid1 | 1.396-1.466 | 374-397k | utilization <= 0.75 | 1.4988 | 0/3 pass | target CL/stall-utilization contract is tighter than historical safe CLmax |
| mid2 | 1.224-1.224 | 348-348k | utilization <= 0.75 | 1.4195 | 0/3 pass | target CL/stall-utilization contract is tighter than historical safe CLmax |
| tip | 0.665-1.012 | 265-330k | utilization <= 0.75 | 1.3939 | 2/3 pass | historical reference includes at least one hard-gate pass |

## Medium Top Candidates

| zone | rank | candidate_id | cd_mission | safe_clmax | cm | robust_pass_rate | tc | camber | te_thickness | hard_gate_pass | artifact_suspicion | hard_gate_notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| root | 1 | seedless_sobol_0988 | 0.013231 | 1.2546 | -0.062564 | 1 | 0.14943 | 0.037823 | 0.0017699 | False | low | stall margin -0.342 at reference_avl_case |
| root | 2 | seedless_sobol_1192 | 0.017817 | 1.3958 | -0.058953 | 1 | 0.14217 | 0.041554 | 0.0021741 | False | low | stall margin -0.231 at reference_avl_case |
| root | 3 | seedless_sobol_2423 | 0.017417 | 1.445 | -0.067285 | 1 | 0.15987 | 0.01638 | 0.002667 | False | low | stall margin -0.198 at reference_avl_case |
| root | 4 | seedless_sobol_2136 | 0.082119 | 1.2338 | -0.07954 | 1 | 0.15532 | 0.059285 | 0.00062556 | False | low | stall margin -0.360 at reference_avl_case |
| root | 5 | seedless_sobol_0004 | 0.012143 | 1.377 | -0.10287 | 1 | 0.14667 | 0.05391 | 0.0038843 | False | low | stall margin -0.245 at reference_avl_case |
| root | 6 | seedless_sobol_2224 | 0.013092 | 1.4523 | -0.0928 | 1 | 0.15218 | 0.050731 | 0.003395 | False | low | stall margin -0.193 at reference_avl_case |
| root | 7 | seedless_sobol_1546 | 0.027769 | 1.3253 | -0.13615 | 1 | 0.14167 | 0.047481 | 0.0035403 | False | medium | stall margin -0.284 at reference_avl_case |
| root | 8 | seedless_sobol_1115 | 0.011207 | 1.3003 | -0.16533 | 1 | 0.15925 | 0.051238 | 0.0028883 | False | high | stall margin -0.303 at reference_avl_case; cm hard violation 0.005 |
| root | 9 | seedless_sobol_0370 | 0.011515 | 1.1033 | -0.12688 | 1 | 0.1533 | 0.06529 | 0.0027957 | False | medium | stall margin -0.492 at reference_avl_case |
| root | 10 | seedless_sobol_0752 | 0.011847 | 1.3625 | -0.12738 | 1 | 0.14301 | 0.043235 | 0.0028269 | False | medium | stall margin -0.255 at reference_avl_case |
| mid1 | 1 | seedless_sobol_0539 | 0.074283 | 1.0641 | -0.026844 | 1 | 0.13458 | 0.056575 | 4.1946e-05 | False | medium | stall margin -0.627 at reference_avl_case |
| mid1 | 2 | seedless_sobol_0887 | 0.022041 | 1.3692 | -0.034341 | 1 | 0.12426 | 0.023949 | 5.3149e-05 | False | low | stall margin -0.320 at reference_avl_case |
| mid1 | 3 | seedless_sobol_1006 | 0.0099568 | 0.48054 | -0.11058 | 1 | 0.10005 | 0.044215 | 0.00013267 | False | medium | stall margin -2.300 at reference_avl_case |
| mid1 | 4 | seedless_sobol_0915 | 0.013841 | 1.1925 | -0.090745 | 1 | 0.15761 | 0.05133 | 0.0013783 | False | medium | stall margin -0.479 at reference_avl_case |
| mid1 | 5 | seedless_sobol_0491 | 0.064514 | 1.2903 | -0.042003 | 1 | 0.15566 | 0.03216 | 0.0029053 | False | low | stall margin -0.386 at reference_avl_case |
| mid1 | 6 | seedless_sobol_0635 | 0.045167 | 1.2181 | -0.044153 | 1 | 0.13758 | 0.032217 | 0.00053338 | False | medium | stall margin -0.453 at reference_avl_case |
| mid1 | 7 | seedless_sobol_0393 | 0.056326 | 0.93729 | -0.048618 | 1 | 0.14089 | 0.028962 | 0.0013664 | False | medium | stall margin -0.814 at reference_avl_case |
| mid1 | 8 | seedless_sobol_0474 | 0.012509 | 1.2725 | -0.14509 | 1 | 0.14586 | 0.063095 | 0.0021212 | False | medium | stall margin -0.402 at reference_avl_case |
| mid1 | 9 | seedless_sobol_0723 | 0.018969 | 1.3822 | -0.072436 | 1 | 0.10426 | 0.040209 | 0.00035997 | False | low | stall margin -0.310 at reference_avl_case |
| mid1 | 10 | seedless_sobol_0758 | 0.01277 | 0.49716 | -0.11987 | 1 | 0.12952 | 0.043479 | 0.00010343 | False | medium | stall margin -2.198 at reference_avl_case |
| mid2 | 1 | seedless_sobol_0900 | 0.01897 | 1.3004 | -0.017757 | 1 | 0.11883 | 0.03718 | 0.00066445 | False | low | stall margin -0.191 at reference_avl_case |
| mid2 | 2 | seedless_sobol_0874 | 0.012585 | 1.1184 | -0.057096 | 1 | 0.11651 | 0.049447 | 0.001581 | False | low | stall margin -0.344 at reference_avl_case |
| mid2 | 3 | seedless_sobol_1342 | 0.009356 | 0.25921 | -0.079165 | 1 | 0.11306 | 0.032644 | 0.0031506 | False | medium | stall margin -3.970 at reference_avl_case |
| mid2 | 4 | seedless_sobol_1192 | 0.017997 | 1.2868 | -0.036237 | 1 | 0.10775 | 0.039322 | 0.0019024 | False | low | stall margin -0.201 at reference_avl_case |
| mid2 | 5 | seedless_sobol_0932 | 0.01632 | 1.2281 | -0.054166 | 1 | 0.1511 | 0.01684 | 0.0029045 | False | low | stall margin -0.246 at reference_avl_case |
| mid2 | 6 | seedless_sobol_0515 | 0.035794 | 1.0303 | -0.02167 | 1 | 0.11463 | 0.0070035 | 0.0018468 | False | low | stall margin -0.437 at reference_avl_case |
| mid2 | 7 | seedless_sobol_0774 | 0.013132 | 0.26765 | -0.076621 | 1 | 0.14942 | 0.022768 | 0.003407 | False | medium | stall margin -3.821 at reference_avl_case |
| mid2 | 8 | seedless_sobol_1124 | 0.014055 | 1.2798 | -0.073901 | 1 | 0.14472 | 0.034047 | 0.0031031 | False | low | stall margin -0.206 at reference_avl_case |
| mid2 | 9 | seedless_sobol_1296 | 0.020658 | 1.3442 | -0.074759 | 1 | 0.13672 | 0.027592 | 0.0014019 | False | low | stall margin -0.160 at reference_avl_case |
| mid2 | 10 | seedless_sobol_0560 | 0.017109 | 1.1737 | -0.065623 | 1 | 0.11151 | 0.037242 | 0.0016292 | False | low | stall margin -0.292 at reference_avl_case |
| tip | 1 | seedless_sobol_0208 | 0.016406 | 1.3716 | -0.064326 | 1 | 0.1029 | 0.043028 | 0.00028636 | True | low | ok |
| tip | 2 | seedless_sobol_0487 | 0.065419 | 1.3402 | -0.090056 | 1 | 0.10971 | 0.042599 | 0.00027239 | False | low | stall margin -0.001 at reference_avl_case |
| tip | 3 | seedless_sobol_0848 | 0.017319 | 1.3287 | -0.10636 | 1 | 0.12389 | 0.057879 | 0.0030215 | False | medium | stall margin -0.007 at reference_avl_case |
| tip | 4 | seedless_sobol_1535 | 0.017438 | 1.3135 | -0.065106 | 1 | 0.10919 | 0.028037 | 0.0023612 | False | low | stall margin -0.016 at reference_avl_case |
| tip | 5 | seedless_sobol_1296 | 0.017164 | 1.3145 | -0.074614 | 1 | 0.13672 | 0.027592 | 0.0014019 | False | low | stall margin -0.015 at reference_avl_case |
| tip | 6 | seedless_sobol_1455 | 0.012695 | 1.3049 | -0.060681 | 1 | 0.10862 | 0.036464 | 0.00080738 | False | low | stall margin -0.021 at reference_avl_case |
| tip | 7 | seedless_sobol_1192 | 0.014692 | 1.286 | -0.032664 | 1 | 0.10775 | 0.039322 | 0.0019024 | False | low | stall margin -0.032 at reference_avl_case |
| tip | 8 | seedless_sobol_0647 | 0.061159 | 1.3028 | -0.11163 | 1 | 0.11653 | 0.047159 | 0.0034561 | False | low | stall margin -0.022 at reference_avl_case |
| tip | 9 | seedless_sobol_0900 | 0.015818 | 1.2771 | -0.01523 | 1 | 0.11883 | 0.03718 | 0.00066445 | False | low | stall margin -0.037 at reference_avl_case |
| tip | 10 | seedless_sobol_0060 | 0.018134 | 1.2906 | -0.13214 | 1 | 0.12298 | 0.050905 | 0.0021023 | False | medium | stall margin -0.029 at reference_avl_case |

## Historical Baselines

| zone | candidate_id | score | cd_mission | safe_clmax | cm | robust_pass_rate | hard_gate_pass | hard_gate_notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| root | historical_fx_76_mp_140 | 12.336 | 0.030612 | 1.5194 | -0.20671 | 1 | False | stall margin -0.152 at reference_avl_case; cm hard violation 0.047 |
| root | historical_dae11 | 14.785 | 0.032684 | 1.3729 | -0.12535 | 1 | False | stall margin -0.248 at reference_avl_case; t/c 0.129 < 0.140 |
| root | historical_dae21 | 16.205 | 0.028686 | 1.4305 | -0.1431 | 1 | False | stall margin -0.208 at reference_avl_case; t/c 0.118 < 0.140 |
| mid1 | historical_dae21 | 12.484 | 0.045369 | 1.4098 | -0.1404 | 1 | False | stall margin -0.290 at reference_avl_case |
| mid1 | historical_fx_76_mp_140 | 12.541 | 0.044362 | 1.4988 | -0.20534 | 1 | False | stall margin -0.228 at reference_avl_case; cm hard violation 0.045 |
| mid1 | historical_dae11 | 13.075 | 0.06747 | 1.3528 | -0.12603 | 1 | False | stall margin -0.333 at reference_avl_case |
| mid2 | historical_dae41 | 12.178 | 0.024615 | 1.1816 | -0.038055 | 1 | False | stall margin -0.285 at reference_avl_case |
| mid2 | historical_dae31 | 12.428 | 0.026385 | 1.4195 | -0.15518 | 1 | False | stall margin -0.112 at reference_avl_case |
| mid2 | historical_dae21 | 12.509 | 0.027942 | 1.3945 | -0.14306 | 1 | False | stall margin -0.127 at reference_avl_case |
| tip | historical_dae31 | 4.0746 | 0.018632 | 1.3939 | -0.15823 | 1 | True | ok |
| tip | historical_dae21 | 4.3814 | 0.018621 | 1.3688 | -0.14313 | 1 | True | ok |
| tip | historical_dae41 | 11.797 | 0.017284 | 1.1519 | -0.061061 | 1 | False | stall margin -0.122 at reference_avl_case |

## Engineering Judgment

- Zones with no feasible medium seedless candidate: root, mid1, mid2.
- Outboard stability: acceptable; at least one mid2/tip hard-gate pass remains.
- Root/mid infeasibility should not be fixed by blindly relaxing the stall gate. The current evidence points first to target-CL/stall-utilization compatibility and the root t/c plus Cm contract.
- Limited 3D combination screening is reasonable only for zones/designs that carry `hard_gate_pass=True`; root/mid no-feasible cases should enter as explicit diagnostic/best-effort references, not normal selected airfoils.
- Manufacturing trailing-edge thickness should remain a downstream build gate, not an airfoil search-space coverage gate.
- `n=7` remains diagnostic only; Phase 5 does not show a CST-degree blocker.

## Machine-Readable Artifacts

- `phase5_feasibility_stats.csv`
- `phase5_stall_design_audit.csv`
- `zone_evaluation_counts.csv`
- `top_candidates.csv`
- `historical_baselines.csv`
- `run_summary.json`
