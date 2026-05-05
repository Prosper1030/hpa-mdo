# Seedless CST Airfoil Selection Behavior Audit

Read-mostly audit of post-Phase-3 seedless CST selection behavior.

## Dry-run scales

| scale | sample_count | coarse_score_count | robust_score_count | re_factors | roughness | zones | worker_results | elapsed_s |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| medium | 512 | 64 | 16 | [0.85, 1.0, 1.15] | ['clean', 'rough'] | ['root', 'mid1', 'mid2', 'tip'] | 712 | 233.75 |

## Actual candidate evaluation counts

| scale | zone | requested_sample_count | coarse_score_count_limit | robust_score_count_limit | candidate_pool_count | coarse_evaluated_count | robust_stage_candidate_count | scored_candidate_count | historical_reference_count |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| medium | root | 512 | 64 | 16 | 511 | 64 | 16 | 64 | 3 |
| medium | mid1 | 512 | 64 | 16 | 512 | 64 | 16 | 64 | 3 |
| medium | mid2 | 512 | 64 | 16 | 512 | 64 | 16 | 64 | 3 |
| medium | tip | 512 | 64 | 16 | 512 | 64 | 16 | 64 | 3 |

Important behavior note: with current `coarse_to_fine_enabled` seedless mode, the production candidate pool can be 1024 per zone, but only a small coarse subset is sent to XFOIL before the robust stage. This audit records both the pool count and actually scored count.

## Medium Top Seedless Candidates

This table is the first completed scale in the audit and is included to make sure the requested zones have explicit behavior evidence without forcing pytest to run a full 1024-sample XFOIL campaign.

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

## Representative Medium Top Seedless Candidates

This representative table uses the largest completed scale in the run with the configured Reynolds and roughness settings. Full all-zone production-probe is intentionally treated as a formal campaign scale when runtime is too high for an interactive audit.

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

## Medium Historical Baseline Comparison

| zone | candidate_id | score | cd_mission | safe_clmax | cm | robust_pass_rate | hard_gate_pass | hard_gate_notes | artifact_suspicion |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| root | historical_fx_76_mp_140 | 12.336 | 0.030612 | 1.5194 | -0.20671 | 1 | False | stall margin -0.152 at reference_avl_case; cm hard violation 0.047 | high |
| root | historical_dae11 | 14.785 | 0.032684 | 1.3729 | -0.12535 | 1 | False | stall margin -0.248 at reference_avl_case; t/c 0.129 < 0.140 | medium |
| root | historical_dae21 | 16.205 | 0.028686 | 1.4305 | -0.1431 | 1 | False | stall margin -0.208 at reference_avl_case; t/c 0.118 < 0.140 | medium |
| mid1 | historical_dae21 | 12.484 | 0.045369 | 1.4098 | -0.1404 | 1 | False | stall margin -0.290 at reference_avl_case | medium |
| mid1 | historical_fx_76_mp_140 | 12.541 | 0.044362 | 1.4988 | -0.20534 | 1 | False | stall margin -0.228 at reference_avl_case; cm hard violation 0.045 | high |
| mid1 | historical_dae11 | 13.075 | 0.06747 | 1.3528 | -0.12603 | 1 | False | stall margin -0.333 at reference_avl_case | medium |
| mid2 | historical_dae41 | 12.178 | 0.024615 | 1.1816 | -0.038055 | 1 | False | stall margin -0.285 at reference_avl_case | low |
| mid2 | historical_dae31 | 12.428 | 0.026385 | 1.4195 | -0.15518 | 1 | False | stall margin -0.112 at reference_avl_case | medium |
| mid2 | historical_dae21 | 12.509 | 0.027942 | 1.3945 | -0.14306 | 1 | False | stall margin -0.127 at reference_avl_case | medium |
| tip | historical_dae31 | 4.0746 | 0.018632 | 1.3939 | -0.15823 | 1 | True | ok | medium |
| tip | historical_dae21 | 4.3814 | 0.018621 | 1.3688 | -0.14313 | 1 | True | ok | medium |
| tip | historical_dae41 | 11.797 | 0.017284 | 1.1519 | -0.061061 | 1 | False | stall margin -0.122 at reference_avl_case | low |

## Representative Medium Historical Baseline Comparison

| zone | candidate_id | score | cd_mission | safe_clmax | cm | robust_pass_rate | hard_gate_pass | hard_gate_notes | artifact_suspicion |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| root | historical_fx_76_mp_140 | 12.336 | 0.030612 | 1.5194 | -0.20671 | 1 | False | stall margin -0.152 at reference_avl_case; cm hard violation 0.047 | high |
| root | historical_dae11 | 14.785 | 0.032684 | 1.3729 | -0.12535 | 1 | False | stall margin -0.248 at reference_avl_case; t/c 0.129 < 0.140 | medium |
| root | historical_dae21 | 16.205 | 0.028686 | 1.4305 | -0.1431 | 1 | False | stall margin -0.208 at reference_avl_case; t/c 0.118 < 0.140 | medium |
| mid1 | historical_dae21 | 12.484 | 0.045369 | 1.4098 | -0.1404 | 1 | False | stall margin -0.290 at reference_avl_case | medium |
| mid1 | historical_fx_76_mp_140 | 12.541 | 0.044362 | 1.4988 | -0.20534 | 1 | False | stall margin -0.228 at reference_avl_case; cm hard violation 0.045 | high |
| mid1 | historical_dae11 | 13.075 | 0.06747 | 1.3528 | -0.12603 | 1 | False | stall margin -0.333 at reference_avl_case | medium |
| mid2 | historical_dae41 | 12.178 | 0.024615 | 1.1816 | -0.038055 | 1 | False | stall margin -0.285 at reference_avl_case | low |
| mid2 | historical_dae31 | 12.428 | 0.026385 | 1.4195 | -0.15518 | 1 | False | stall margin -0.112 at reference_avl_case | medium |
| mid2 | historical_dae21 | 12.509 | 0.027942 | 1.3945 | -0.14306 | 1 | False | stall margin -0.127 at reference_avl_case | medium |
| tip | historical_dae31 | 4.0746 | 0.018632 | 1.3939 | -0.15823 | 1 | True | ok | medium |
| tip | historical_dae21 | 4.3814 | 0.018621 | 1.3688 | -0.14313 | 1 | True | ok | medium |
| tip | historical_dae41 | 11.797 | 0.017284 | 1.1519 | -0.061061 | 1 | False | stall margin -0.122 at reference_avl_case | low |

## Artifact Risk

| scale | zone | rank | candidate_id | artifact_suspicion | artifact_notes |
| --- | --- | --- | --- | --- | --- |
| medium | root | 7 | seedless_sobol_1546 | medium | cm -0.136 near trim penalty region |
| medium | root | 8 | seedless_sobol_1115 | high | cm -0.165 beyond hard trim bound |
| medium | root | 9 | seedless_sobol_0370 | medium | cm -0.127 near trim penalty region; polar target mismatch dCL=0.127 |
| medium | root | 10 | seedless_sobol_0752 | medium | cm -0.127 near trim penalty region |
| medium | mid1 | 1 | seedless_sobol_0539 | medium | polar target mismatch dCL=0.270 |
| medium | mid1 | 3 | seedless_sobol_1006 | medium | polar target mismatch dCL=0.918 |
| medium | mid1 | 4 | seedless_sobol_0915 | medium | polar target mismatch dCL=0.130 |
| medium | mid1 | 6 | seedless_sobol_0635 | medium | polar target mismatch dCL=0.102 |
| medium | mid1 | 7 | seedless_sobol_0393 | medium | polar target mismatch dCL=0.408 |
| medium | mid1 | 8 | seedless_sobol_0474 | medium | cm -0.145 near trim penalty region |
| medium | mid1 | 10 | seedless_sobol_0758 | medium | polar target mismatch dCL=0.930 |
| medium | mid2 | 3 | seedless_sobol_1342 | medium | polar target mismatch dCL=0.888 |
| medium | mid2 | 7 | seedless_sobol_0774 | medium | thin leading edge 0.015c at 1% chord; polar target mismatch dCL=0.879 |
| medium | tip | 3 | seedless_sobol_0848 | medium | polar target mismatch dCL=0.053 |
| medium | tip | 10 | seedless_sobol_0060 | medium | cm -0.132 near trim penalty region |

## Figures

- [production-probe_root_cd_vs_cl.png](production-probe_root_cd_vs_cl.png)
- [production-probe_root_clean_vs_rough_cd.png](production-probe_root_clean_vs_rough_cd.png)
- [production-probe_root_cm_vs_cl.png](production-probe_root_cm_vs_cl.png)
- [production-probe_root_shape_overlay.png](production-probe_root_shape_overlay.png)
- [production-probe_tc_camber_summary.png](production-probe_tc_camber_summary.png)
- [production-probe_tip_cd_vs_cl.png](production-probe_tip_cd_vs_cl.png)
- [production-probe_tip_clean_vs_rough_cd.png](production-probe_tip_clean_vs_rough_cd.png)
- [production-probe_tip_cm_vs_cl.png](production-probe_tip_cm_vs_cl.png)
- [production-probe_tip_shape_overlay.png](production-probe_tip_shape_overlay.png)
- [smoke_mid1_cd_vs_cl.png](smoke_mid1_cd_vs_cl.png)
- [smoke_mid1_clean_vs_rough_cd.png](smoke_mid1_clean_vs_rough_cd.png)
- [smoke_mid1_cm_vs_cl.png](smoke_mid1_cm_vs_cl.png)
- [smoke_mid1_shape_overlay.png](smoke_mid1_shape_overlay.png)
- [smoke_mid2_cd_vs_cl.png](smoke_mid2_cd_vs_cl.png)
- [smoke_mid2_clean_vs_rough_cd.png](smoke_mid2_clean_vs_rough_cd.png)
- [smoke_mid2_cm_vs_cl.png](smoke_mid2_cm_vs_cl.png)
- [smoke_mid2_shape_overlay.png](smoke_mid2_shape_overlay.png)
- [smoke_root_cd_vs_cl.png](smoke_root_cd_vs_cl.png)
- [smoke_root_clean_vs_rough_cd.png](smoke_root_clean_vs_rough_cd.png)
- [smoke_root_cm_vs_cl.png](smoke_root_cm_vs_cl.png)
- [smoke_root_shape_overlay.png](smoke_root_shape_overlay.png)
- [smoke_tc_camber_summary.png](smoke_tc_camber_summary.png)
- [smoke_tip_cd_vs_cl.png](smoke_tip_cd_vs_cl.png)
- [smoke_tip_clean_vs_rough_cd.png](smoke_tip_clean_vs_rough_cd.png)
- [smoke_tip_cm_vs_cl.png](smoke_tip_cm_vs_cl.png)
- [smoke_tip_shape_overlay.png](smoke_tip_shape_overlay.png)

## Judgment

1. Bounds expansion did allow seedless geometry in the historical FX/DAE envelope, but selection only partially moves toward those families. The `tip` production-probe top candidates are plausible low-Re sections (`t/c` about 0.102-0.105 and moderate camber) and compete directly with DAE31/DAE21. The `root` probe does not produce a clean accepted FX-like solution; every root seedless and historical candidate in this run fails a hard gate.
2. The root mismatch is mainly a design-point/gate and effective-sampling issue, not a CST-degree issue. Root and mid stations carry high target CL, and the hard-gate notes are dominated by stall margin. The Phase 5 funnel now records explicit coarse and robust-stage counts so `seedless_sample_count=1024` is no longer mistaken for the number of XFOIL-scored candidates.
3. XFOIL artifact risk is mixed. The best `tip` production-probe candidates are low-suspicion and hard-gate passing. Several root candidates that look attractive by drag have large polar target mismatch, low safe-clmax, or excessive negative Cm, so those should not be promoted as real gains.
4. Historical baselines are useful sanity checks but not all are suitable for every zone under the current scoring contract. DAE31/DAE21 pass the `tip` hard gates. FX 76-MP-140 is penalized at the root by stall margin and Cm, while DAE11/DAE21 are also below the current root thickness requirement.
5. Recommendation: do not promote the full production baseline directly into unrestricted 3D combination screening yet. A limited outboard/tip screening is reasonable, with DAE31/DAE21 retained as references. Root/mid should first get a selection-behavior patch plan around hard-gate feasibility, robust candidate count, and design-point weighting.
6. Keep manufacturing constraints separate from the airfoil search-space coverage gate. The near-sharp TE allowance should stay in search; any build minimum should be a downstream manufacturing/buildability gate.
7. Keep `n=7` as diagnostic mode. Phase 3 already showed `n=6` fits the historical geometry gate, and this Phase 4 behavior is controlled by scoring, gates, XFOIL robustness, and effective candidate evaluation count.

## Files

- `run_summary.json`: complete machine-readable audit payload.
- `top_candidates.csv`: top seedless candidate rows across all scales.
- `historical_baselines.csv`: historical baseline rows across all scales.
- `zone_evaluation_counts.csv`: requested vs actually evaluated candidate counts.
