# Closed Loop Decision

C. More data is impossible locally, with the exact missing file/tool/input.

- candidate: `current_avl_compromise_conservative_closed`
- selected structural run: `/Volumes/Samsung SSD/hpa-mdo/output/go_mode_main_wing_candidate/current_avl_compromise_conservative_closed_closure/runs/conservative_best/structure_response`
- confidence label: `internal screening; FEM model-basis mismatch`
- ccx binary: `/Volumes/Samsung SSD/homebrew-cellar/Cellar/calculix-ccx/2.23/bin/ccx_2.23`
- primary first-fail estimate: `wire` at `n = 3.030`
- note: lift-wire tension reaches allowable
- FEM scale check: internal reference tip `1.5432 m`, CalculiX max tip `0.0796 m`, mismatch `94.8%`

Engineering judgement: the candidate clears the requested 1g, 1.5g, and 1.75g checks on the fixed-design internal estimate. The controlling extrapolated limit is the lift-wire tension margin, not tube stress or buckling.

The FEM spot-check is a candidate-specific B32R beam deck generated from the selected jig spar CSV. It does not upgrade the candidate when its displacement scale is not comparable with the internal inverse-design structural response; that is a model-basis blocker, not a physical pass.
