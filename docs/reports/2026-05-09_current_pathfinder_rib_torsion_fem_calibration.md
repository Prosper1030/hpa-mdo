# Current Pathfinder Rib / Torsion FEM Calibration

Candidate: `current_avl_compromise_conservative_closed`
Decision: `selected_candidate_still_clears_but_calibrated_search_prefers_next`

## Answer

- FEM/local stiffness response says the selected carbon-collar/rear75 fast model is `fast_optimistic` with twist factor `1.238016`.
- Selected candidate bounded twist after calibration: `1.821554` deg.
- Calibrated fast-search top row: `eps_balsa_cap_hybrid_10mm__t12p0mm__manufacturing_relaxed_0p36__carbon_face_collar_y2p328__rear75` at `1.490536` deg.
- y=2.328 m bond/collar/tube-wall risk: `watch`; tube-wall margin `2.303946`.
- Relaxed spacing 0.36 m assessment: `relaxed_spacing_reasonable_for_search_not_final`.
- Aggressive carbon collar / rear75 bound case: `fast_optimistic`, disposition `aggressive_bound_not_selected`.
- Lightweight foam-core reference remains `downgrade_reference_only`.

## Sample Results

| role | fast bounded deg | FEM/local deg | factor | bias | load-path risk | disposition |
|---|---:|---:|---:|---|---|---|
| `baseline_balsa_3mm` | 3.256324 | 3.256324 | 1.0 | `usable_close` | `watch` | `baseline_reference_anchor` |
| `selected_hybrid_10mm` | 1.471349 | 1.821554 | 1.238016 | `fast_optimistic` | `watch` | `keep_selected_after_calibration` |
| `aggressive_plausible_hybrid` | 0.508631 | 1.02285 | 2.010986 | `fast_optimistic` | `no_obvious_smoke_risk` | `aggressive_bound_not_selected` |
| `lightweight_foam_core_reference` | 19.944533 | 4.651547 | 0.233224 | `fast_conservative` | `elevated_watch` | `downgrade_reference_only` |

## Solver Smoke

- CalculiX smoke status: `ran`
- deck: `/Volumes/Samsung SSD/hpa-mdo/output/current_pathfinder_rib_torsion_fem_calibration/calculix_smoke/baseline_balsa_3mm__balsa_sheet_3mm__t3p0mm__uniform_0p30__none__rear50.inp`
- note: CalculiX deck is an executable smoke for the local equivalent torsion probe; numeric calibration factors come from the local torsion-link FEM.

## Engineering Boundary

This is first-pass calibration evidence, not final sign-off. It checks twist/stiffness response and bond/collar/tube-wall indicators for the fast surrogate. It does not certify final local stress, buckling, manufacturing quality, adhesive allowables, tube crushing, or flight load factors.

First-pass FEM calibration evidence only. Do not treat this as final bond, collar, tube-wall, buckling, composite, or aircraft sign-off.
