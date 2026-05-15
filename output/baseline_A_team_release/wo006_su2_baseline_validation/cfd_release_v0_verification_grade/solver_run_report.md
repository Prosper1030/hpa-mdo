# Solver Run Report

All strict snappy fallback cases reached a finite `simpleFoam`/SpalartAllmaras run and produced force histories plus yPlus fields. This proves the route can execute, but the accepted-CFD gate remains failed because the mesh/yPlus gate failed first.

| case | solver status | iterations/rows | CD_primary final | CL_primary final | CD_total final | last-20 CD span | last-20 CL span | elapsed wall s |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `wall_function_target` | route_smoke_case_completed | 120 | 0.07596562 | 0.8922962 | 0.07600988 | 0.01194544 | 0.0679375 | 77.74429917 |
| `intermediate_target` | mesh_quality_failed | 120 | 0.09213965 | 0.6566135 | 0.09219328 | 0.001725 | 0.0099915 | 78.60207582 |
| `wall_resolved_target` | route_smoke_case_completed | 120 | 0.07326929 | 0.9215704 | 0.07332259 | 0.00027942 | 0.0064635 | 75.08996677 |

The closest numerical history is `wall_resolved_target`: its last-20 CD span is small, but the mesh is not actually wall-resolved. Solver stability therefore cannot upgrade the result into drag truth.
