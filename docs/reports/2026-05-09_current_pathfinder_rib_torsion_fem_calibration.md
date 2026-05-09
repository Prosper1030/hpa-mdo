# Current Pathfinder Rib / Torsion CalculiX FEM Calibration

Candidate: `current_avl_compromise_conservative_closed`
Decision: `fast_physical_model_verified_within_5pct`
Primary solver: `calculix_ccx_local_frame_fem`

## Answer

- CCX local model audit: `ccx_local_model_reasonable_for_fast_physics_alignment`.
- Selected 10 mm legacy fast / CCX / revised fast bounded twist: `1.471349` / `2.203642` / `2.107663` deg.
- Selected legacy factor error / revised factor error: `49.77021`% / `4.553835`%.
- Revised fast-search top row: `eps_balsa_cap_hybrid_10mm__t10p0mm__uniform_0p30__carbon_face_collar_y2p328__rear75` at `1.673592` deg.
- y=2.328 m bond/collar/tube-wall risk: `watch`; tube-wall margin `2.303946`.
- Relaxed spacing 0.36 m assessment: `relaxed_spacing_reasonable_for_search_not_final`.
- Aggressive carbon collar / rear75 bound case: `usable_close`, disposition `aggressive_bound_not_selected`.
- Lightweight foam-core reference remains `downgrade_reference_only`.
- CCX local frame cases completed: `5` / `5`.
- Verdict: `fast_physical_model_verified_within_5pct`.

## Sample Results

| role | legacy fast deg | CCX deg | legacy error % | revised fast deg | revised error % | reason | disposition |
|---|---:|---:|---:|---:|---:|---|---|
| `baseline_balsa_3mm` | 3.256324 | 3.256324 | 0.0 | 3.256324 | 0.0 | baseline anchor; no revised correction is fitted to this row | `baseline_reference_anchor` |
| `selected_hybrid_10mm` | 1.471349 | 2.203642 | 49.77021 | 2.107663 | 4.553835 | relaxed spacing is penalized and carbon collar credit is capped as rib shear-link stiffness | `keep_selected_after_calibration` |
| `aggressive_plausible_hybrid` | 0.508631 | 0.758169 | 49.060796 | 0.749391 | 1.171407 | thickness and dense-spacing gains are saturated; carbon collar is a shear-link credit | `aggressive_bound_not_selected` |
| `lightweight_foam_core_reference` | 19.944533 | 3.323776 | 83.334901 | 19.944533 | 83.334901 | foam-only row kept as downgraded shape-core reference, not fitted as bracing | `downgrade_reference_only` |
| `revised_selected_candidate` | 1.353641 | 1.64095 | 21.224878 | 1.673592 | 1.950437 | relaxed spacing is penalized and carbon collar credit is capped as rib shear-link stiffness | `new_selected_after_revised_search` |

## Fast Physics Sensitivity

The largest structural correction is the local shear-transfer/link term: carbon collar is capped as load-introduction stiffness, and uncollared hybrid torque-zone rows are downgraded instead of receiving free rear-spar credit.

| role | dominant term | legacy error % | revised error % |
|---|---|---:|---:|
| `baseline_balsa_3mm` | `thickness_factor` | 0.0 | 0.0 |
| `selected_hybrid_10mm` | `local_reinforcement_factor` | 49.77021 | 4.553835 |
| `aggressive_plausible_hybrid` | `local_reinforcement_factor` | 49.060796 | 1.171407 |
| `lightweight_foam_core_reference` | `thickness_factor` | 83.334901 | 83.334901 |
| `revised_selected_candidate` | `local_reinforcement_factor` | 21.224878 | 1.950437 |

## CalculiX Local Frame

- status: `ccx_local_frame_completed`
- ccx: `/Volumes/Samsung SSD/homebrew-cellar/Cellar/calculix-ccx/2.23/bin/ccx_2.23`
- model: main spar segment + rear spar segment + torque-zone collar beams + rib shear-transfer beams + diagonal shear-transfer braces
- load: main lift `21.202 N` plus main/rear force couple `-23.839 / +23.839 N` at y=`2.327757 m`
- boundary: local neighboring bay/rib end stations clamped in the beam-frame deck
- reaction balance: `reaction_force_balance_closed`
- deformation mode: `torsion_shear_transfer_dominant`

## Solver Smoke

- CalculiX smoke status: `not_requested`
- deck: `/Volumes/Samsung SSD/hpa-mdo/output/current_pathfinder_rib_torsion_fem_calibration/calculix_smoke/baseline_balsa_3mm__balsa_sheet_3mm__t3p0mm__uniform_0p30__none__rear50.inp`
- note: Legacy 2-node smoke deck only. It is not used for calibration; numeric correction factors come from calculix_ccx_local_frame_fem cases.

## Engineering Boundary

This is first-pass calibration evidence, not final sign-off. It checks twist/stiffness response and bond/collar/tube-wall indicators for the fast surrogate. It does not certify final local stress, buckling, manufacturing quality, adhesive allowables, tube crushing, or flight load factors.

First-pass FEM calibration evidence only. Do not treat this as final bond, collar, tube-wall, buckling, composite, or aircraft sign-off.
