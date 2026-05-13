/goal In /Volumes/Samsung SSD/hpa-mdo, execute WO-006R6: repair the current-GO conformal BL/core interface and mixed-element SU2 writer after WO-006R5.

Start from `output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r5_bl_core_merge/`.
First resolve the preserved-core quality/coupling blockers without changing Baseline A external shape.
Only emit `bl_mesh_handoff.v1.json` after one merged mixed-element SU2 mesh exists, marker ownership passes, interface unmatched counts are zero, SU2 readability passes, and coefficient interpretation remains explicitly blocked until y+/wall shear, convergence, and grid-pair evidence exist.

Previous verdict: `wo006r5_core_merge_limitation_proven`.
