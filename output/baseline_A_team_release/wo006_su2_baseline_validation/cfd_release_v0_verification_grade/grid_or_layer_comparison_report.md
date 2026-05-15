# Grid Or Layer Comparison Report

No accepted grid/layer refinement comparison exists because no case met the near-wall acceptance gate. The table below is still useful as bounded evidence that changing requested layer targets in strict snappy did not create a verification-grade layer stack.

| case | CD_primary | CL_primary | CD_total | upper mean/p95/max y+ | lower mean/p95/max y+ | accepted? |
| --- | --- | --- | --- | --- | --- | --- |
| `previous_layers_8` | 0.08141586 | 0.8227612 | 0.08147018 | 183.23868736 / 576.9516 / 1437.45 | 164.54271683 / 460.0907 / 1191.1 | no |
| `wall_function_target` | 0.07596562 | 0.8922962 | 0.07600988 | 242.88437279 / 894.0962 / 2229.37 | 129.46331533 / 658.6481 / 1190.69 | no |
| `intermediate_target` | 0.09213965 | 0.6566135 | 0.09219328 | 250.95223397 / 930.3192 / 1415.15 | 184.15006859 / 783.9661 / 1172.64 | no |
| `wall_resolved_target` | 0.07326929 | 0.9215704 | 0.07332259 | 192.62012089 / 703.5011 / 1611.03 | 128.13073409 / 411.7137 / 1175.49 | no |

The force values vary across rejected meshes and therefore cannot be interpreted as grid convergence. The closest force-stable strict-snappy case (`wall_resolved_target`) still has high yPlus and poor actual layer coverage, so it remains high-yPlus sanity only.
