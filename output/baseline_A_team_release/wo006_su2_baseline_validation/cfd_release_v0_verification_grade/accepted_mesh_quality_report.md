# Accepted Mesh Quality Report

No verification-grade mesh was accepted. Two strict snappy fallback cases were checkMesh-clean under the local smoke parser, but they still fail the CFD validation requirement because near-wall layer coverage collapsed and yPlus stayed high. The intermediate case also failed custom mesh quality.

| case | cells | checkMesh/custom errors | upper y+ mean/p95/max | lower y+ mean/p95/max | avg layers upper/lower | accepted verification mesh | reason |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `wall_function_target` | 230740 | pass_with_smoke_skew_warning / 0 | 242.88437279 / 894.0962 / 2229.37 | 129.46331533 / 658.6481 / 1190.69 | 0.644 / 1.37 | no | yPlus/layer coverage fail |
| `intermediate_target` | 226609 | failed_checkmesh / 1 | 250.95223397 / 930.3192 / 1415.15 | 184.15006859 / 783.9661 / 1172.64 | 0.449 / 1.11 | no | custom checkMesh quality error plus yPlus fail |
| `wall_resolved_target` | 233866 | pass_with_smoke_skew_warning / 0 | 192.62012089 / 703.5011 / 1611.03 | 128.13073409 / 411.7137 / 1175.49 | 0.82 / 1.54 | no | yPlus/layer coverage fail |

## Engineering Reading

The failure is not diagnostic patch contamination and not solver startup. The dominant issue is that the mature open-source routes available here did not create a controlled boundary-layer mesh on `wing_upper` and `wing_lower` while preserving mesh quality. For the strict snappy fallback, asking for 30 layers still produced less than two average added layers on the wing patches and yPlus remained O(100-1000), which is not wall-resolved and not defensible wall-function verification.
