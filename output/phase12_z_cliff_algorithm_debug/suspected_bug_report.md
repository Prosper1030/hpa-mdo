# Suspected Bug Report

## Root Cause Classification

The cliff is best classified as an algorithm/search-branch artifact around a real hard constraint, not as a smooth physical mass requirement.

Important boundary: this statement describes the inverse-selector branch. The production dual-beam numerical-consistency channel reports `moment_closure` failure for the evaluated candidates, while the inverse-selector `overall_feasible` flag does not include that production hard failure.

The immediate hard constraint flip is:

- `ground_clearance_margin_m: forced light recipe is -0.012759 m at z=2.000 m versus selected-light 0.000272 m at z=2.025 m`

## Checks From the Requested Bug List

| Check | Finding |
|---|---|
| wrong clearance inequality sign | No evidence in this dump; failures flip exactly when `ground_clearance_margin_m` changes sign. |
| unit mismatch mm vs m | No evidence; reported z scales and tube dimensions remain in expected m/mm conventions, and design arrays match canonical summaries. |
| stale unscaled target shape CSV | A known export hazard exists in prior Phase 11/12 rows, but this candidate selection uses in-memory inverse target and summary JSON, not the exported target CSV. Downstream readers must not use stale CSV as selection truth. |
| wrong artifact path / JSON vs CSV path | Candidate AVL artifact path is case-specific and recorded in the debug output. Selection uses the JSON artifact. |
| discontinuous catalog sorting | This path is not a physical tube catalog pick; it is a reduced-variable grid over generated tube geometries plus rib profiles. The coarse endpoint grid creates branch discreteness. |
| objective prefers thick wall due bad penalty scaling | The heavy z=2.000 m recipe is selected because lighter recipes fail hard feasibility, mainly clearance. Objective is not the first cause. |
| pass/fail overwritten by later checks | No direct overwrite found, but active-wall probe candidates are added after `selected` is captured, so `best_overall_feasible` can improve without updating the reported selected candidate. |
| production moment-closure ignored by selector | Confirmed as a lineage/selection gap: `build_candidate_hard_margins()` only includes geometry plus equivalent-beam gates, and inverse selection uses `inverse.feasibility.overall_feasible`; production `moment_closure` is visible but not part of the selected candidate pass/fail. |
| mass aggregation double-counting | No new evidence of double-counting in this run; masses track geometry changes and prior reconstruction matched the reported full-system convention. |
| full-span vs half-span convention mismatch | The reported `spar_tube_mass_full_kg` remains a full-system tube mass convention. It is not the cause of the 2.000/2.025 jump because both cases use the same convention. |
| recipe selection not sorted after filtering | Coarse selection is sorted by `_feasible_key`; however, diagnostics probes are evaluated after selection and are not reselected. |

## Additional Algorithm Findings

- The active-wall diagnostics evaluate additional candidates after the reported selection is frozen. For z=2.000 m this found 75.514549 kg, but the summary still reports 77.013607 kg.
- `structure_budgeted_z_state_search.py` does not pass `--target-mass-kg` into the canonical search. The 11.5 kg budget is applied as a post-filter, so the canonical selected recipe is not budget-seeking.
- Every candidate in the two dumps reports `moment_closure_status=fail`. That means neither the 77 kg nor 15.5 kg recipe should be treated as structure-grade until the production feasibility channel is wired into the selector or explicitly declared report-only.
- The MVP uses endpoint grids and `--skip-local-refine --no-ground-clearance-recovery`. Near a zero-clearance boundary, that can produce a sharp reported mass cliff even when nearby continuous geometries might exist.

## Trust Assessment

- z=2.000 m reported mass: 77.013607 kg.
- z=2.025 m reported mass: 15.518635 kg.
- The 77 kg-class result should be treated as a warning that the current selected recipe branch is clearance-blocked at low z, not as final CFRP sizing.
