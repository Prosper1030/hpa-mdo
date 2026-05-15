# yPlus Verification Report

Acceptance targets were not met. Wall-function verification wanted mean yPlus preferably `30-100` with p95 preferably below `300`; wall-resolved verification wanted mean below `5`, p95 below `20`, and max preferably below `100` or localized.

| case | patch | count | min | mean | p95 | max | wall-function accepted? | wall-resolved accepted? |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `wall_function_target` | `wing_upper` | 9687 | 2.47417 | 242.88437279 | 894.0962 | 2229.37 | no | no |
| `wall_function_target` | `wing_lower` | 8383 | 4.11124 | 129.46331533 | 658.6481 | 1190.69 | no | no |
| `intermediate_target` | `wing_upper` | 9687 | 1.3874 | 250.95223397 | 930.3192 | 1415.15 | no | no |
| `intermediate_target` | `wing_lower` | 8383 | 1.5544 | 184.15006859 | 783.9661 | 1172.64 | no | no |
| `wall_resolved_target` | `wing_upper` | 9687 | 2.84186 | 192.62012089 | 703.5011 | 1611.03 | no | no |
| `wall_resolved_target` | `wing_lower` | 8383 | 5.83869 | 128.13073409 | 411.7137 | 1175.49 | no | no |

## Comparison To Previous High-yPlus Route

Previous `layers_8` high-yPlus route-smoke: upper mean/p95/max `183.23868736 / 576.9516 / 1437.45`, lower mean/p95/max `164.54271683 / 460.0907 / 1191.1`.

The strict snappy `wall_resolved_target` improved some yPlus statistics relative to `layers_8`, but not enough to cross either acceptance boundary. Its upper p95 is still about `703.5011` and lower p95 about `411.7137`.
