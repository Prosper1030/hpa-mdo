# Phase 4 True Baseline OpenFOAM Route-Smoke Verdict

1. Did BC reconciliation complete?
   - `True`
2. Did every patch have valid BCs?
   - `True`
3. Did checkMesh still pass on the accepted full-wing mesh?
   - `True`
4. Did simpleFoam run?
   - `True`
5. What are CD_primary, CL_primary, CD_total?
   - `{'CD_primary': 0.01837651, 'CL_primary': 0.5654834, 'CD_total': 0.06993191}`
6. What is yPlus mean/p95/max?
   - `{'mean': 0.5882082748397414, 'p95': 1.17049, 'max': 2.8138}`
7. Are tip/TE/closure diagnostics contaminating CD?
   - `{'diagnostic_sum': 0.051555389539999996, 'diagnostic_fraction_of_total': 0.7372226718818348, 'interpretation': 'Primary CD is separated, but diagnostic tip patches are not negligible in CD_total; do not use CD_total for profile-drag comparison without resolving patch role/domain symmetry.'}`
8. Is the force window stable enough for route-smoke?
   - `True`
9. Is this result high-yPlus, wall-function, wall-resolved, or failed?
   - `main_wall_resolved_like_but_tip_high_yplus_not_validated`
10. Is this result comparable to XFOIL CD≈0.02602 yet?
   - `False`
11. What is the next action?
   - `patch-role/domain audit before AoA sweep; then farfield/outlet sensitivity on the corrected BC convention`

Engineering boundary: OpenFOAM route-smoke only. Passing checkMesh and simpleFoam here does not establish grid-converged, wall-resolved, or release-grade drag.
Patch-geometry audit: tip_left is exactly y=0 plane while tip_right is y=17.166143 plane; this looks like a half-span/root-symmetry domain, not a +/- full-span wing.
