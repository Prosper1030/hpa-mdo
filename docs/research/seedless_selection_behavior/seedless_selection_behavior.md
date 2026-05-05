# Seedless CST Airfoil Selection Behavior Audit

Read-mostly audit of post-Phase-3 seedless CST selection behavior.

## Dry-run scales

| scale | sample_count | re_factors | roughness | zones | worker_results | elapsed_s |
| --- | --- | --- | --- | --- | --- | --- |
| smoke | 128 | [1.0] | ['clean'] | ['root', 'mid1', 'mid2', 'tip'] | 60 | 56.099 |
| medium | 512 | [0.85, 1.0, 1.15] | ['clean', 'rough'] | ['root', 'tip'] | 96 | 117.04 |
| production-probe | 1024 | [0.85, 1.0, 1.15] | ['clean', 'rough'] | ['root', 'tip'] | 96 | 237.05 |

## Actual candidate evaluation counts

| scale | zone | requested_sample_count | candidate_pool_count | coarse_evaluated_count | robust_stage_candidate_count | scored_candidate_count | historical_reference_count |
| --- | --- | --- | --- | --- | --- | --- | --- |
| smoke | root | 128 | 128 | 12 | 3 | 12 | 3 |
| smoke | mid1 | 128 | 128 | 12 | 3 | 12 | 3 |
| smoke | mid2 | 128 | 128 | 12 | 3 | 12 | 3 |
| smoke | tip | 128 | 128 | 12 | 3 | 12 | 3 |
| medium | root | 512 | 511 | 12 | 3 | 12 | 3 |
| medium | tip | 512 | 512 | 12 | 3 | 12 | 3 |
| production-probe | root | 1024 | 1023 | 12 | 3 | 12 | 3 |
| production-probe | tip | 1024 | 1024 | 12 | 3 | 12 | 3 |

Important behavior note: with current `coarse_to_fine_enabled` seedless mode, the production candidate pool can be 1024 per zone, but only a small coarse subset is sent to XFOIL before the robust stage. This audit records both the pool count and actually scored count.

## Smoke All-Zone Top Seedless Candidates

This smoke table is the only all-zone run in the audit and is included to make sure `root`, `mid1`, `mid2`, and `tip` all have explicit behavior evidence without running a full 1024-sample XFOIL campaign in every zone.

| zone | rank | candidate_id | cd_mission | safe_clmax | cm | robust_pass_rate | tc | camber | te_thickness | hard_gate_pass | artifact_suspicion | hard_gate_notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| root | 1 | seedless_sobol_0004 | 0.012143 | 1.377 | -0.10287 | 1 | 0.14667 | 0.05391 | 0.0038843 | False | low | stall margin -0.245 at reference_avl_case |
| root | 2 | seedless_sobol_0118 | 0.010902 | 0.44122 | -0.11305 | 1 | 0.15173 | 0.019226 | 0.0010903 | False | medium | stall margin -2.355 at reference_avl_case |
| root | 3 | seedless_sobol_0183 | 0.012416 | 1.3102 | -0.10949 | 1 | 0.15765 | 0.058811 | 0.00023512 | False | low | stall margin -0.296 at reference_avl_case |
| root | 4 | seedless_sobol_0228 | 0.012575 | 1.6475 | -0.12566 | 1 | 0.15009 | 0.049756 | 0.0034961 | False | medium | stall margin -0.081 at reference_avl_case |
| root | 5 | seedless_sobol_0689 | 0.06896 | 0.93274 | -0.059783 | 1 | 0.14666 | 0.011639 | 0.0038991 | False | medium | stall margin -0.719 at reference_avl_case |
| root | 6 | seedless_sobol_0410 | 0.045462 | 1.0496 | -0.072204 | 1 | 0.15589 | 0.032792 | 0.0010569 | False | medium | stall margin -0.555 at reference_avl_case |
| root | 7 | seedless_sobol_0633 | 0.096464 | 1.1229 | -0.079303 | 1 | 0.15865 | 0.05677 | 0.0036902 | False | medium | stall margin -0.470 at reference_avl_case |
| root | 8 | seedless_sobol_0531 | 0.020363 | 1.4268 | -0.12844 | 1 | 0.14032 | 0.031352 | 0.0033247 | False | medium | stall margin -0.210 at reference_avl_case |
| root | 9 | seedless_sobol_0066 | 0.032622 | 1.0504 | -0.10101 | 1 | 0.15796 | 0.045701 | 0.002227 | False | medium | stall margin -0.554 at reference_avl_case |
| root | 10 | seedless_sobol_0599 | 0.031325 | 1.3725 | -0.11029 | 1 | 0.15809 | 0.039546 | 0.0017006 | False | low | stall margin -0.248 at reference_avl_case |
| mid1 | 1 | seedless_sobol_0100 | 0.014006 | 1.4476 | -0.087837 | 1 | 0.14779 | 0.050125 | 0.0033766 | False | low | stall margin -0.263 at reference_avl_case |
| mid1 | 2 | seedless_sobol_0004 | 0.014219 | 1.3866 | -0.10571 | 1 | 0.14667 | 0.05391 | 0.0038843 | False | low | stall margin -0.307 at reference_avl_case |
| mid1 | 3 | seedless_sobol_0248 | 0.075072 | 1.2376 | -0.058185 | 1 | 0.15125 | 0.051161 | 0.00060152 | False | medium | stall margin -0.434 at reference_avl_case |
| mid1 | 4 | seedless_sobol_0220 | 0.013847 | 1.3436 | -0.15791 | 1 | 0.13612 | 0.073028 | 0.0029832 | False | medium | stall margin -0.341 at reference_avl_case |
| mid1 | 5 | seedless_sobol_0154 | 0.091581 | 1.1752 | -0.060337 | 1 | 0.15476 | 0.046685 | 0.0031404 | False | medium | stall margin -0.497 at reference_avl_case |
| mid1 | 6 | seedless_sobol_0276 | 0.019471 | 1.4973 | -0.085551 | 1 | 0.12728 | 0.02708 | 0.00050116 | False | low | stall margin -0.229 at reference_avl_case |
| mid1 | 7 | seedless_sobol_0173 | 0.043802 | 1.077 | -0.068673 | 1 | 0.11969 | 0.049039 | 0.0010738 | False | medium | stall margin -0.611 at reference_avl_case |
| mid1 | 8 | seedless_sobol_0028 | 0.055642 | 1.2847 | -0.083263 | 1 | 0.15733 | 0.044842 | 0.0019558 | False | low | stall margin -0.391 at reference_avl_case |
| mid1 | 9 | seedless_sobol_0077 | 0.059386 | 1.168 | -0.099904 | 1 | 0.14427 | 0.055707 | 0.0015558 | False | medium | stall margin -0.505 at reference_avl_case |
| mid1 | 10 | seedless_sobol_0197 | 0.067488 | 1.3141 | -0.10364 | 1 | 0.14129 | 0.06273 | 0.0027864 | False | low | stall margin -0.365 at reference_avl_case |
| mid2 | 1 | seedless_sobol_0196 | 0.014574 | 1.2341 | -0.021546 | 1 | 0.11509 | 0.025663 | 0.00081128 | False | low | stall margin -0.241 at reference_avl_case |
| mid2 | 2 | seedless_sobol_0336 | 0.01692 | 1.2465 | -0.027486 | 1 | 0.1098 | 0.02715 | 0.0020788 | False | low | stall margin -0.232 at reference_avl_case |
| mid2 | 3 | seedless_sobol_0296 | 0.013289 | 1.3631 | -0.052302 | 1 | 0.13364 | 0.037675 | 0.00083711 | False | low | stall margin -0.148 at reference_avl_case |
| mid2 | 4 | seedless_sobol_0416 | 0.017869 | 1.4223 | -0.031861 | 1 | 0.10737 | 0.024677 | 0.0032398 | False | low | stall margin -0.110 at reference_avl_case |
| mid2 | 5 | seedless_sobol_0222 | 0.013673 | 0.18787 | -0.058512 | 1 | 0.15644 | 0.025346 | 0.0015434 | False | medium | stall margin -5.763 at reference_avl_case |
| mid2 | 6 | seedless_sobol_0377 | 0.020044 | 0.55195 | -0.034088 | 1 | 0.11794 | 0.015811 | 0.00048573 | False | medium | stall margin -1.467 at reference_avl_case |
| mid2 | 7 | seedless_sobol_0052 | 0.022261 | 1.138 | -0.026712 | 1 | 0.12909 | 0.023222 | 0.0010888 | False | low | stall margin -0.325 at reference_avl_case |
| mid2 | 8 | seedless_sobol_0149 | 0.01726 | 0.82202 | -0.07173 | 1 | 0.12346 | 0.025695 | 0.00051843 | False | medium | stall margin -0.738 at reference_avl_case |
| mid2 | 9 | seedless_sobol_0265 | 0.011 | 0.35015 | -0.13347 | 1 | 0.11659 | 0.037666 | 0.0011052 | False | medium | stall margin -2.744 at reference_avl_case |
| mid2 | 10 | seedless_sobol_0003 | 0.029831 | 1.2415 | -0.07572 | 1 | 0.12313 | 0.045804 | 0.0026784 | False | low | stall margin -0.236 at reference_avl_case |
| tip | 1 | seedless_sobol_0416 | 0.013992 | 1.3992 | -0.030143 | 1 | 0.10737 | 0.024677 | 0.0032398 | True | low | ok |
| tip | 2 | seedless_sobol_0296 | 0.012696 | 1.341 | -0.051263 | 1 | 0.13364 | 0.037675 | 0.00083711 | False | low | stall margin -0.000 at reference_avl_case |
| tip | 3 | seedless_sobol_0336 | 0.012624 | 1.2239 | -0.02315 | 1 | 0.1098 | 0.02715 | 0.0020788 | False | low | stall margin -0.071 at reference_avl_case |
| tip | 4 | seedless_sobol_0196 | 0.01302 | 1.1967 | -0.020596 | 1 | 0.11509 | 0.025663 | 0.00081128 | False | low | stall margin -0.090 at reference_avl_case |
| tip | 5 | seedless_sobol_0052 | 0.011863 | 1.1151 | -0.029741 | 1 | 0.12909 | 0.023222 | 0.0010888 | False | low | stall margin -0.151 at reference_avl_case |
| tip | 6 | seedless_sobol_0377 | 0.02053 | 0.5571 | -0.033738 | 1 | 0.11794 | 0.015811 | 0.00048573 | False | medium | stall margin -1.041 at reference_avl_case |
| tip | 7 | seedless_sobol_0222 | 0.017363 | 0.51128 | -0.059043 | 1 | 0.15644 | 0.025346 | 0.0015434 | False | medium | stall margin -1.199 at reference_avl_case |
| tip | 8 | seedless_sobol_0003 | 0.011372 | 1.2115 | -0.11786 | 1 | 0.12313 | 0.045804 | 0.0026784 | False | low | stall margin -0.080 at reference_avl_case |
| tip | 9 | seedless_sobol_0149 | 0.016503 | 0.93212 | -0.072172 | 1 | 0.12346 | 0.025695 | 0.00051843 | False | low | stall margin -0.326 at reference_avl_case |
| tip | 10 | seedless_sobol_0077 | 0.016278 | 0.8792 | -0.090629 | 1 | 0.11071 | 0.043387 | 0.0013613 | False | low | stall margin -0.391 at reference_avl_case |

## Representative Production-Probe Top Seedless Candidates

The production-probe table uses 1024 samples per requested zone with multipoint Reynolds and clean/rough evaluation. In this run it was intentionally limited to `root` and `tip` to keep runtime bounded.

| zone | rank | candidate_id | cd_mission | safe_clmax | cm | robust_pass_rate | tc | camber | te_thickness | hard_gate_pass | artifact_suspicion | hard_gate_notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| root | 1 | seedless_sobol_4584 | 0.045161 | 1.36 | -0.10037 | 1 | 0.15544 | 0.062984 | 0.0010299 | False | low | stall margin -0.257 at reference_avl_case |
| root | 2 | seedless_sobol_0961 | 0.011544 | 0.37056 | -0.11067 | 1 | 0.14156 | 0.042648 | 2.3621e-05 | False | medium | stall margin -2.947 at reference_avl_case |
| root | 3 | seedless_sobol_1377 | 0.012328 | 0.3801 | -0.11658 | 1 | 0.15907 | 0.035155 | 0.0024511 | False | medium | stall margin -2.854 at reference_avl_case |
| root | 4 | seedless_sobol_0004 | 0.03535 | 1.3269 | -0.10376 | 1 | 0.14667 | 0.05391 | 0.0038843 | False | low | stall margin -0.282 at reference_avl_case |
| root | 5 | seedless_sobol_3593 | 0.013066 | 0.59906 | -0.19761 | 1 | 0.14802 | 0.055237 | 0.0011351 | False | high | stall margin -1.537 at reference_avl_case; cm hard violation 0.038 |
| root | 6 | seedless_sobol_5176 | 0.019681 | 1.4968 | -0.10916 | 1 | 0.14139 | 0.040803 | 0.0015048 | False | low | stall margin -0.165 at reference_avl_case |
| root | 7 | seedless_sobol_4095 | 0.032704 | 1.2965 | -0.063173 | 1 | 0.14214 | 0.04116 | 8.5746e-05 | False | low | stall margin -0.307 at reference_avl_case |
| root | 8 | seedless_sobol_5731 | 0.039757 | 1.1415 | -0.067738 | 1 | 0.1423 | 0.03908 | 0.00053769 | False | medium | stall margin -0.450 at reference_avl_case |
| root | 9 | seedless_sobol_0537 | 0.035861 | 1.0259 | -0.083167 | 1 | 0.14779 | 0.033836 | 0.0031973 | False | medium | stall margin -0.585 at reference_avl_case |
| root | 10 | seedless_sobol_2445 | 0.02227 | 1.0823 | -0.14912 | 1 | 0.15825 | 0.04465 | 0.0030968 | False | medium | stall margin -0.516 at reference_avl_case |
| tip | 1 | seedless_sobol_2616 | 0.01751 | 1.4056 | -0.054729 | 1 | 0.10166 | 0.027683 | 0.0010455 | True | low | ok |
| tip | 2 | seedless_sobol_2048 | 0.01665 | 1.3785 | -0.056929 | 1 | 0.10357 | 0.044277 | 0.001447 | True | low | ok |
| tip | 3 | seedless_sobol_3231 | 0.017645 | 1.3434 | -0.059377 | 1 | 0.10542 | 0.024655 | 0.0032041 | True | low | ok |
| tip | 4 | seedless_sobol_2343 | 0.011227 | 1.3298 | -0.10997 | 1 | 0.1068 | 0.04228 | 0.00083526 | False | low | stall margin -0.006 at reference_avl_case |
| tip | 5 | seedless_sobol_1767 | 0.014863 | 1.2753 | -0.097303 | 1 | 0.15703 | 0.03877 | 0.0031534 | False | low | stall margin -0.039 at reference_avl_case |
| tip | 6 | seedless_sobol_1484 | 0.016499 | 1.2655 | -0.063374 | 1 | 0.13408 | 0.02472 | 0.0012653 | False | low | stall margin -0.045 at reference_avl_case |
| tip | 7 | seedless_sobol_1191 | 0.013472 | 1.221 | -0.045702 | 1 | 0.13076 | 0.046438 | 0.0013972 | False | low | stall margin -0.073 at reference_avl_case |
| tip | 8 | seedless_sobol_0298 | 0.010379 | 1.2195 | -0.13725 | 1 | 0.13166 | 0.051979 | 0.0033251 | False | medium | stall margin -0.074 at reference_avl_case |
| tip | 9 | seedless_sobol_2940 | 0.013469 | 1.082 | -0.076627 | 1 | 0.10967 | 0.047813 | 0.0017389 | False | low | stall margin -0.178 at reference_avl_case |
| tip | 10 | seedless_sobol_0003 | 0.011372 | 1.2115 | -0.11786 | 1 | 0.12313 | 0.045804 | 0.0026784 | False | low | stall margin -0.080 at reference_avl_case |

## Smoke All-Zone Historical Baseline Comparison

| zone | candidate_id | score | cd_mission | safe_clmax | cm | robust_pass_rate | hard_gate_pass | hard_gate_notes | artifact_suspicion |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| root | historical_fx_76_mp_140 | 12.268 | 0.010259 | 1.6252 | -0.20488 | 1 | False | stall margin -0.093 at reference_avl_case; cm hard violation 0.045 | high |
| root | historical_dae11 | 14.709 | 0.010633 | 1.4377 | -0.12531 | 1 | False | stall margin -0.203 at reference_avl_case; t/c 0.129 < 0.140 | medium |
| root | historical_dae21 | 16.158 | 0.0096416 | 1.4425 | -0.14276 | 1 | False | stall margin -0.200 at reference_avl_case; t/c 0.118 < 0.140 | medium |
| mid1 | historical_dae21 | 12.424 | 0.011664 | 1.4374 | -0.14001 | 1 | False | stall margin -0.270 at reference_avl_case | medium |
| mid1 | historical_fx_76_mp_140 | 12.442 | 0.011959 | 1.6219 | -0.20423 | 1 | False | stall margin -0.154 at reference_avl_case; cm hard violation 0.044 | high |
| mid1 | historical_dae11 | 12.496 | 0.012767 | 1.4392 | -0.12582 | 1 | False | stall margin -0.268 at reference_avl_case | medium |
| mid2 | historical_dae41 | 12.084 | 0.018818 | 1.1713 | -0.035239 | 1 | False | stall margin -0.295 at reference_avl_case | low |
| mid2 | historical_dae31 | 12.354 | 0.01033 | 1.4518 | -0.15504 | 1 | False | stall margin -0.093 at reference_avl_case | medium |
| mid2 | historical_dae21 | 12.413 | 0.011191 | 1.4329 | -0.14265 | 1 | False | stall margin -0.104 at reference_avl_case | medium |
| tip | historical_dae31 | 3.2541 | 0.012815 | 1.4321 | -0.15823 | 1 | True | ok | medium |
| tip | historical_dae21 | 3.6076 | 0.01282 | 1.4144 | -0.14353 | 1 | True | ok | medium |
| tip | historical_dae41 | 11.752 | 0.0098299 | 1.1518 | -0.061352 | 1 | False | stall margin -0.123 at reference_avl_case | low |

## Representative Historical Baseline Comparison

| zone | candidate_id | score | cd_mission | safe_clmax | cm | robust_pass_rate | hard_gate_pass | hard_gate_notes | artifact_suspicion |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| root | historical_fx_76_mp_140 | 12.336 | 0.030612 | 1.5194 | -0.20671 | 1 | False | stall margin -0.152 at reference_avl_case; cm hard violation 0.047 | high |
| root | historical_dae11 | 14.785 | 0.032684 | 1.3729 | -0.12535 | 1 | False | stall margin -0.248 at reference_avl_case; t/c 0.129 < 0.140 | medium |
| root | historical_dae21 | 16.205 | 0.028686 | 1.4305 | -0.1431 | 1 | False | stall margin -0.208 at reference_avl_case; t/c 0.118 < 0.140 | medium |
| tip | historical_dae31 | 4.0746 | 0.018632 | 1.3939 | -0.15823 | 1 | True | ok | medium |
| tip | historical_dae21 | 4.3814 | 0.018621 | 1.3688 | -0.14313 | 1 | True | ok | medium |
| tip | historical_dae41 | 11.797 | 0.017284 | 1.1519 | -0.061061 | 1 | False | stall margin -0.122 at reference_avl_case | low |

## Artifact Risk

| scale | zone | rank | candidate_id | artifact_suspicion | artifact_notes |
| --- | --- | --- | --- | --- | --- |
| smoke | root | 2 | seedless_sobol_0118 | medium | polar target mismatch dCL=0.847 |
| smoke | root | 4 | seedless_sobol_0228 | medium | cm -0.126 near trim penalty region |
| smoke | root | 5 | seedless_sobol_0689 | medium | polar target mismatch dCL=0.313 |
| smoke | root | 6 | seedless_sobol_0410 | medium | polar target mismatch dCL=0.186 |
| smoke | root | 7 | seedless_sobol_0633 | medium | polar target mismatch dCL=0.162 |
| smoke | root | 8 | seedless_sobol_0531 | medium | cm -0.128 near trim penalty region |
| smoke | root | 9 | seedless_sobol_0066 | medium | polar target mismatch dCL=0.185 |
| smoke | mid1 | 3 | seedless_sobol_0248 | medium | polar target mismatch dCL=0.081 |
| smoke | mid1 | 4 | seedless_sobol_0220 | medium | cm -0.158 near trim penalty region |
| smoke | mid1 | 5 | seedless_sobol_0154 | medium | polar target mismatch dCL=0.149 |
| smoke | mid1 | 7 | seedless_sobol_0173 | medium | polar target mismatch dCL=0.256 |
| smoke | mid1 | 9 | seedless_sobol_0077 | medium | polar target mismatch dCL=0.157 |
| smoke | mid2 | 5 | seedless_sobol_0222 | medium | polar target mismatch dCL=0.965 |
| smoke | mid2 | 6 | seedless_sobol_0377 | medium | polar target mismatch dCL=0.570 |
| smoke | mid2 | 8 | seedless_sobol_0149 | medium | polar target mismatch dCL=0.276 |
| smoke | mid2 | 9 | seedless_sobol_0265 | medium | cm -0.133 near trim penalty region; polar target mismatch dCL=0.789 |
| smoke | tip | 6 | seedless_sobol_0377 | medium | polar target mismatch dCL=0.335 |
| smoke | tip | 7 | seedless_sobol_0222 | medium | polar target mismatch dCL=0.384 |
| medium | root | 3 | seedless_sobol_0228 | medium | cm -0.126 near trim penalty region |
| medium | root | 4 | seedless_sobol_1184 | medium | cm -0.126 near trim penalty region |
| medium | root | 5 | seedless_sobol_1619 | medium | polar target mismatch dCL=0.105 |
| medium | root | 7 | seedless_sobol_0754 | high | cm -0.177 beyond hard trim bound |
| medium | root | 8 | seedless_sobol_0537 | medium | polar target mismatch dCL=0.211 |
| medium | tip | 6 | seedless_sobol_0298 | medium | cm -0.137 near trim penalty region |
| medium | tip | 8 | seedless_sobol_0465 | medium | polar target mismatch dCL=0.218 |
| medium | tip | 9 | seedless_sobol_0606 | medium | thin leading edge 0.015c at 1% chord; polar target mismatch dCL=0.388 |
| production-probe | root | 2 | seedless_sobol_0961 | medium | polar target mismatch dCL=0.924 |
| production-probe | root | 3 | seedless_sobol_1377 | medium | polar target mismatch dCL=0.913 |
| production-probe | root | 5 | seedless_sobol_3593 | high | cm -0.198 beyond hard trim bound; polar target mismatch dCL=0.675 |
| production-probe | root | 8 | seedless_sobol_5731 | medium | polar target mismatch dCL=0.086 |
| production-probe | root | 9 | seedless_sobol_0537 | medium | polar target mismatch dCL=0.211 |
| production-probe | root | 10 | seedless_sobol_2445 | medium | cm -0.149 near trim penalty region; polar target mismatch dCL=0.150 |
| production-probe | tip | 8 | seedless_sobol_0298 | medium | cm -0.137 near trim penalty region |

## Figures

- [smoke_root_shape_overlay.png](smoke_root_shape_overlay.png)
- [smoke_root_cd_vs_cl.png](smoke_root_cd_vs_cl.png)
- [smoke_root_cm_vs_cl.png](smoke_root_cm_vs_cl.png)
- [smoke_root_clean_vs_rough_cd.png](smoke_root_clean_vs_rough_cd.png)
- [smoke_mid1_shape_overlay.png](smoke_mid1_shape_overlay.png)
- [smoke_mid1_cd_vs_cl.png](smoke_mid1_cd_vs_cl.png)
- [smoke_mid1_cm_vs_cl.png](smoke_mid1_cm_vs_cl.png)
- [smoke_mid1_clean_vs_rough_cd.png](smoke_mid1_clean_vs_rough_cd.png)
- [smoke_mid2_shape_overlay.png](smoke_mid2_shape_overlay.png)
- [smoke_mid2_cd_vs_cl.png](smoke_mid2_cd_vs_cl.png)
- [smoke_mid2_cm_vs_cl.png](smoke_mid2_cm_vs_cl.png)
- [smoke_mid2_clean_vs_rough_cd.png](smoke_mid2_clean_vs_rough_cd.png)
- [smoke_tip_shape_overlay.png](smoke_tip_shape_overlay.png)
- [smoke_tip_cd_vs_cl.png](smoke_tip_cd_vs_cl.png)
- [smoke_tip_cm_vs_cl.png](smoke_tip_cm_vs_cl.png)
- [smoke_tip_clean_vs_rough_cd.png](smoke_tip_clean_vs_rough_cd.png)
- [smoke_tc_camber_summary.png](smoke_tc_camber_summary.png)
- [production-probe_root_shape_overlay.png](production-probe_root_shape_overlay.png)
- [production-probe_root_cd_vs_cl.png](production-probe_root_cd_vs_cl.png)
- [production-probe_root_cm_vs_cl.png](production-probe_root_cm_vs_cl.png)
- [production-probe_root_clean_vs_rough_cd.png](production-probe_root_clean_vs_rough_cd.png)
- [production-probe_tip_shape_overlay.png](production-probe_tip_shape_overlay.png)
- [production-probe_tip_cd_vs_cl.png](production-probe_tip_cd_vs_cl.png)
- [production-probe_tip_cm_vs_cl.png](production-probe_tip_cm_vs_cl.png)
- [production-probe_tip_clean_vs_rough_cd.png](production-probe_tip_clean_vs_rough_cd.png)
- [production-probe_tc_camber_summary.png](production-probe_tc_camber_summary.png)

## Judgment

1. Bounds expansion did allow seedless geometry in the historical FX/DAE envelope, but selection only partially moves toward those families. The `tip` production-probe top candidates are plausible low-Re sections (`t/c` about 0.102-0.105 and moderate camber) and compete directly with DAE31/DAE21. The `root` probe does not produce a clean accepted FX-like solution; every root seedless and historical candidate in this run fails a hard gate.
2. The root mismatch is mainly a design-point/gate and effective-sampling issue, not a CST-degree issue. Root and mid stations carry high target CL, and the hard-gate notes are dominated by stall margin. Also, the current coarse-to-fine setup sends only 12 coarse candidates and 3 local robust-stage candidates per zone to XFOIL, so `seedless_sample_count=1024` mostly improves the hidden Sobol pool rather than the number of scored aerodynamic alternatives.
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
