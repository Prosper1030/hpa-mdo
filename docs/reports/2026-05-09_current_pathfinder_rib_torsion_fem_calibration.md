# Current Pathfinder Rib / Torsion CalculiX FEM Calibration

Candidate: `current_avl_compromise_conservative_closed`
Decision: `calculix_calibrated_fast_loop_ready_for_search`
Primary solver: `calculix_ccx_local_frame_fem`

## Answer

- CalculiX local frame stiffness response says the selected carbon-collar/rear75 fast model is `fast_optimistic` with twist factor `1.497702`.
- Python local_torsion_link_fem comparison factor for the same row: `1.238016`.
- Selected candidate bounded twist after calibration: `2.203642` deg.
- Calibrated fast-search top row: `eps_balsa_cap_hybrid_10mm__t12p0mm__manufacturing_relaxed_0p36__carbon_face_collar_y2p328__rear75` at `1.803191` deg.
- y=2.328 m bond/collar/tube-wall risk: `watch`; tube-wall margin `2.303946`.
- Relaxed spacing 0.36 m assessment: `relaxed_spacing_reasonable_for_search_not_final`.
- Aggressive carbon collar / rear75 bound case: `fast_optimistic`, disposition `aggressive_bound_not_selected`.
- Lightweight foam-core reference remains `downgrade_reference_only`.
- CCX local frame cases completed: `4` / `4`.

## Sample Results

| role | fast bounded deg | CCX calibrated deg | CCX factor | Python factor | bias | load-path risk | disposition |
|---|---:|---:|---:|---:|---|---|---|
| `baseline_balsa_3mm` | 3.256324 | 3.256324 | 1.0 | 1.0 | `usable_close` | `watch` | `baseline_reference_anchor` |
| `selected_hybrid_10mm` | 1.471349 | 2.203642 | 1.497702 | 1.238016 | `fast_optimistic` | `watch` | `keep_selected_after_calibration` |
| `aggressive_plausible_hybrid` | 0.508631 | 0.758169 | 1.490608 | 2.010986 | `fast_optimistic` | `no_obvious_smoke_risk` | `aggressive_bound_not_selected` |
| `lightweight_foam_core_reference` | 19.944533 | 3.323776 | 0.166651 | 0.233224 | `fast_conservative` | `elevated_watch` | `downgrade_reference_only` |

## CalculiX Local Frame

- status: `ccx_local_frame_completed`
- ccx: `/Volumes/Samsung SSD/homebrew-cellar/Cellar/calculix-ccx/2.23/bin/ccx_2.23`
- model: main spar segment + rear spar segment + torque-zone collar beams + rib shear-transfer beams + diagonal shear-transfer braces
- load: main lift `21.202 N` plus main/rear force couple `-23.839 / +23.839 N` at y=`2.327757 m`
- boundary: local neighboring bay/rib end stations clamped in the beam-frame deck

## Solver Smoke

- CalculiX smoke status: `not_requested`
- deck: `/Volumes/Samsung SSD/hpa-mdo/output/current_pathfinder_rib_torsion_fem_calibration/calculix_smoke/baseline_balsa_3mm__balsa_sheet_3mm__t3p0mm__uniform_0p30__none__rear50.inp`
- note: Legacy 2-node smoke deck only. It is not used for calibration; numeric correction factors come from calculix_ccx_local_frame_fem cases.

## Engineering Boundary

This is first-pass calibration evidence, not final sign-off. It checks twist/stiffness response and bond/collar/tube-wall indicators for the fast surrogate. It does not certify final local stress, buckling, manufacturing quality, adhesive allowables, tube crushing, or flight load factors.

First-pass FEM calibration evidence only. Do not treat this as final bond, collar, tube-wall, buckling, composite, or aircraft sign-off.
