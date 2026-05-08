# Tier2 Loaded-Shape Airfoil MVP

This is a report-only MVP4 artifact. It does not change production ranking, add hard gates, rerun broad CST/NSGA, run broad FEM, or promote structure to final truth.

## Source

- Cl/Re source: `stage6_loaded_shape_avl_actual_local_cl_re`.
- Airfoil source: existing Tier2 full-alpha reusable database.
- No broad CST/NSGA rerun was performed.

## Zone Requirements

| zone | Re min | Re p50 | Re max | Cl p50 | Cl p90 | Cl max | current airfoil |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| root | 507793 | 552456 | 568130 | 1.255 | 1.283 | 1.286 | dae31 |
| mid1 | 432390 | 468080 | 498029 | 1.285 | 1.292 | 1.294 | dae31 |
| mid2 | 371499 | 395593 | 419914 | 1.166 | 1.214 | 1.225 | dae31 |
| tip | 291577 | 308663 | 360197 | 0.672 | 0.866 | 0.932 | cst_tip_nsga2_g06_child_0056_b3f9b7c4 |

## Selected Assignments

| role | assignment | profile CD | CD0 total | P crank | P crank cons. | stall margin min | query quality |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| raw_best | `root:dae31|mid1:dae31|mid2:cst_mid2_nsga2_g01_child_0046_9585b968|tip:cst_tip_nsga2_g01_child_0118_60ecf404` | 0.008619 | 0.012509 | 167.31 | 171.48 | 0.819 | actual_loaded_shape_query_warning_not_mission_grade |
| conservative_best | `root:dae31|mid1:dae31|mid2:dae31|tip:cst_tip_nsga2_g05_child_0032_70ef8136` | 0.009366 | 0.013256 | 172.92 | 177.11 | 1.582 | actual_loaded_shape_query_pass |

## Engineering Read

- The assignment is based on MVP3 loaded-shape AVL actual local Cl/Re, not Fourier target Cl.
- Raw best and conservative production-quality best are intentionally separate; raw drag advantage is not a production decision by itself.
- If the conservative row carries warnings, treat MVP4 as diagnostic and loop back through airfoil database coverage or loaded-shape definition instead of forcing a design decision.
- MVP3 still uses a beam-line loaded-Z proxy, so this airfoil result is a screening input to MVP5 closure, not final wing truth.

## Artifact Trace

- combo count: 160
- profile station rows: 5508
- required outputs: `tier2_loaded_shape_airfoil_assignment.json`, `tier2_loaded_shape_combo_search.csv`, `tier2_loaded_shape_profile_drag.csv`, `tier2_loaded_shape_airfoil_report.md`
