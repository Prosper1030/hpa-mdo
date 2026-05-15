# Phase 3 OpenFOAM Ladder Verdict

1. Did the route-smoke remain reproducible?
   - `True`. See `route_smoke_reproduction` in `ladder_manifest.json`.
2. What is the best accepted layer case?
   - `layers_8`.
3. Did yPlus improve from the original mean 165-183 / max >1000?
   - `not improved`. Max y+ must still be read from `yplus_ladder_report.md` and remains a drag-truth warning if above 1000.
4. What are CD_primary and CL_primary for each accepted case?
- `layers_0`: CD_primary `0.09330549`, CL_primary `0.4431198`, y+ upper/lower mean `325.5238` / `398.1273`
- `layers_8`: CD_primary `0.08141586`, CL_primary `0.8227612`, y+ upper/lower mean `183.2387` / `164.5427`
- `layers_16`: CD_primary `0.09079239`, CL_primary `0.6820456`, y+ upper/lower mean `194.7079` / `186.3026`
- `layers_24`: CD_primary `0.09094512`, CL_primary `0.6697053`, y+ upper/lower mean `209.5007` / `193.3586`
5. Are tip/TE/closure patches still negligible?
   - `True` for accepted cases by the 5% diagnostic/CD_total gate.
6. Does CD_primary stabilize as layers/refinement increase?
   - Partially. Adjacent accepted layer pairs exist: `[['layers_16', 'layers_24']]`, but this is not full convergence because the refined low-yPlus case is rejected and the 8 -> 16 layer shift is still large.
7. Is the current result good enough to proceed to a real grid ladder?
   - `False` for a real drag grid ladder. It is good enough only for the targeted refinement/yPlus repair tracked by `good_enough_for_targeted_refinement_yplus_repair=True`.
8. Is the current result good enough to compare against SU2 / VSPAERO / AVL?
   - `False`. Use it only as OpenFOAM route/ladder evidence until yPlus and grid sensitivity are defensible.
9. Is the current result only high-yPlus sanity, wall-function CFD, or wall-resolved CFD?
   - `high_yplus_sanity`.
10. What is the next single action?
   - Repair `layers_8_refined_surface_plus1` mesh-quality errors while preserving its wall-function-range yPlus, then rerun the same SpalartAllmaras force window.

Engineering boundary: passing software gates means the OpenFOAM route produced bounded evidence. It does not mean the Baseline A main-wing drag is final or ready for release/procurement decisions.