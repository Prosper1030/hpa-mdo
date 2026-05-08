# Wire 6 kN Load-Factor Ramp

## Plain-Language Answer

- Changing the modeled wire allowable from 4.581 kN to 6 kN mainly increases strength margin, not stiffness. If the real wire diameter/material/stiffness changes, the FEM must be rerun with the new AE and pretension.
- At `3.0G`, the 6 kN wire-body tension is `4536.1 N`, utilization `0.756`. The modeled cable-body tension allowable is not exceeded.
- Put bluntly: this is a cable-body allowable check, not proof that the termination, splice, bend radius, clamp, fuselage anchor, or wing attach survives 3.0G.
- First thing that happens as G increases: the configured tip deflection limit is reached at about `n = 3.305`.
- The 6 kN wire allowable is reached later at about `n = 3.968`.
- CFRP global bending stress reaches allowable later still at about `n = 5.585`.
- Internal local buckling estimate reaches utilization 1.0 at about `n = 12.396`, but candidate-specific shell buckling is still a separate FEM/detail-model task.

## Why There Is A Limit

- The 6 kN number is a design allowable, not necessarily the physical snap load.
- A design allowable exists because knots, splices, bend radius, UV, abrasion, creep, and attach fittings reduce real strength. The model stops at allowable before the rope's catalog breaking load.
- If 6 kN allowable is justified by the previous policy, the implied catalog minimum break load is roughly `22.5 kN`; under ideal no-loss scaling that physical break would be around `n = 14.9`, far beyond the wing model's valid range.
- So before that hypothetical rope snap, the wing already violates deflection and then stress limits.

## Ramp Table

| n | wire N | wire util | tip defl m | tip util | stress util | buckling util est | event |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 1.00 | 1512.0 | 0.252 | 0.772 | 0.303 | 0.179 | 0.081 | within_model_margins |
| 1.25 | 1890.1 | 0.315 | 0.964 | 0.378 | 0.224 | 0.101 | within_model_margins |
| 1.50 | 2268.1 | 0.378 | 1.157 | 0.454 | 0.269 | 0.121 | within_model_margins |
| 1.75 | 2646.1 | 0.441 | 1.350 | 0.530 | 0.313 | 0.141 | within_model_margins |
| 2.00 | 3024.1 | 0.504 | 1.543 | 0.605 | 0.358 | 0.161 | within_model_margins |
| 2.25 | 3402.1 | 0.567 | 1.736 | 0.681 | 0.403 | 0.182 | within_model_margins |
| 2.50 | 3780.1 | 0.630 | 1.929 | 0.756 | 0.448 | 0.202 | within_model_margins |
| 2.75 | 4158.1 | 0.693 | 2.122 | 0.832 | 0.492 | 0.222 | within_model_margins |
| 3.00 | 4536.1 | 0.756 | 2.315 | 0.908 | 0.537 | 0.242 | within_model_margins |
| 3.25 | 4914.1 | 0.819 | 2.508 | 0.983 | 0.582 | 0.262 | within_model_margins |
| 3.30 | 4997.2 | 0.833 | 2.550 | 1.000 | 0.592 | 0.267 | tip_deflection_limit_exceeded |
| 3.50 | 5292.1 | 0.882 | 2.701 | 1.059 | 0.627 | 0.282 | tip_deflection_limit_exceeded |
| 3.75 | 5670.2 | 0.945 | 2.893 | 1.135 | 0.671 | 0.303 | tip_deflection_limit_exceeded |
| 3.97 | 6000.0 | 1.000 | 3.062 | 1.201 | 0.710 | 0.320 | wire_allowable_exceeded |
| 4.00 | 6048.2 | 1.008 | 3.086 | 1.210 | 0.716 | 0.323 | wire_allowable_exceeded |
| 4.25 | 6426.2 | 1.071 | 3.279 | 1.286 | 0.761 | 0.343 | wire_allowable_exceeded |
| 4.50 | 6804.2 | 1.134 | 3.472 | 1.362 | 0.806 | 0.363 | wire_allowable_exceeded |
| 4.75 | 7182.2 | 1.197 | 3.665 | 1.437 | 0.850 | 0.383 | wire_allowable_exceeded |
| 5.00 | 7560.2 | 1.260 | 3.858 | 1.513 | 0.895 | 0.403 | wire_allowable_exceeded |
| 5.25 | 7938.2 | 1.323 | 4.051 | 1.589 | 0.940 | 0.424 | wire_allowable_exceeded |
| 5.50 | 8316.2 | 1.386 | 4.244 | 1.664 | 0.985 | 0.444 | wire_allowable_exceeded |
| 5.59 | 8445.3 | 1.408 | 4.310 | 1.690 | 1.000 | 0.451 | cfrp_global_bending_stress_exceeded |
| 5.75 | 8694.2 | 1.449 | 4.437 | 1.740 | 1.029 | 0.464 | cfrp_global_bending_stress_exceeded |
| 6.00 | 9072.3 | 1.512 | 4.629 | 1.815 | 1.074 | 0.484 | cfrp_global_bending_stress_exceeded |

## Engineering Readout

- Moving wire allowable to 6 kN removes wire as the first limiter, but it does not buy a large system-level load-factor increase because tip deflection takes over at about 3.305G.
- If you relax or move the tip-deflection limit, the next stop is the 6 kN wire allowable at about 3.968G.
- Past that, continuing the table is useful for understanding failure order, but it should be labeled post-limit extrapolation, not validation.
