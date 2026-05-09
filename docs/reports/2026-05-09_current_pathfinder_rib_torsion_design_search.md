# Current Pathfinder Rib / Torsion Fast Design Search

Candidate: `current_avl_compromise_conservative_closed`
Verdict: `fast_design_loop_ready_for_fem_calibration`

## Selected Fast Candidate

- case: `eps_balsa_cap_hybrid_10mm__t10p0mm__uniform_0p30__carbon_face_collar_y2p328__rear75`
- family / group: `eps_balsa_cap_hybrid_10mm` / `hybrid_foam_balsa_cap`
- thickness / spacing / local reinforcement: `10.0` mm / `uniform_0p30` / `carbon_face_collar_y2p328`
- rear-spar participation: `bounded_75pct_screening`
- fast direct / bounded twist: `2.782336` deg / `1.673592` deg
- mass / CG / rebalance: `5.715042` kg / `0.75` m / `0.079276` m
- tail trim / SM / C_n_beta: `4.792985` deg / `0.094301` / `0.01403`
- evidence: `fast_model_result_needs_FEM_calibration`

## Shortlist

| case | family | rear | mass kg | bounded twist deg | direct status | manuf |
|---|---|---|---:|---:|---|---:|
| `eps_balsa_cap_hybrid_10mm__t10p0mm__uniform_0p30__carbon_face_collar_y2p328__rear75` | `eps_balsa_cap_hybrid_10mm` | `bounded_75pct_screening` | 5.715042 | 1.673592 | `clears_bound` | 0.55 |
| `eps_balsa_cap_hybrid_10mm__t10p0mm__uniform_0p30__glass_face_collar_y2p328__rear75` | `eps_balsa_cap_hybrid_10mm` | `bounded_75pct_screening` | 5.785042 | 1.720516 | `clears_bound` | 0.61 |
| `eps_balsa_cap_hybrid_10mm__t10p0mm__torque_zone_0p24_outboard_0p36__carbon_face_collar_y2p328__rear75` | `eps_balsa_cap_hybrid_10mm` | `bounded_75pct_screening` | 6.036945 | 1.627038 | `clears_bound` | 0.49 |
| `eps_balsa_cap_hybrid_10mm__t8p0mm__dense_torque_zone_0p20__carbon_face_collar_y2p328__rear75` | `eps_balsa_cap_hybrid_10mm` | `bounded_75pct_screening` | 5.586281 | 1.781821 | `clears_bound` | 0.38 |
| `eps_balsa_cap_hybrid_10mm__t10p0mm__torque_zone_0p24_outboard_0p36__balsa_cap_collar_y2p328__rear75` | `eps_balsa_cap_hybrid_10mm` | `bounded_75pct_screening` | 5.866945 | 1.754649 | `clears_bound` | 0.65 |
| `eps_balsa_cap_hybrid_10mm__t10p0mm__torque_zone_0p24_outboard_0p36__glass_face_collar_y2p328__rear75` | `eps_balsa_cap_hybrid_10mm` | `bounded_75pct_screening` | 6.106945 | 1.672656 | `clears_bound` | 0.55 |
| `eps_balsa_cap_hybrid_10mm__t12p0mm__uniform_0p30__carbon_face_collar_y2p328__rear75` | `eps_balsa_cap_hybrid_10mm` | `bounded_75pct_screening` | 6.78805 | 1.451738 | `clears_bound` | 0.5 |
| `eps_balsa_cap_hybrid_10mm__t12p0mm__uniform_0p30__balsa_cap_collar_y2p328__rear75` | `eps_balsa_cap_hybrid_10mm` | `bounded_75pct_screening` | 6.61805 | 1.5656 | `clears_bound` | 0.66 |
| `eps_balsa_cap_hybrid_10mm__t12p0mm__uniform_0p30__glass_face_collar_y2p328__rear75` | `eps_balsa_cap_hybrid_10mm` | `bounded_75pct_screening` | 6.85805 | 1.492441 | `clears_bound` | 0.56 |
| `eps_balsa_cap_hybrid_10mm__t10p0mm__dense_torque_zone_0p20__carbon_face_collar_y2p328__rear75` | `eps_balsa_cap_hybrid_10mm` | `bounded_75pct_screening` | 6.895351 | 1.497181 | `clears_bound` | 0.43 |
| `eps_balsa_cap_hybrid_10mm__t12p0mm__torque_zone_0p24_outboard_0p36__carbon_face_collar_y2p328__rear75` | `eps_balsa_cap_hybrid_10mm` | `bounded_75pct_screening` | 7.174333 | 1.411355 | `clears_bound` | 0.44 |
| `eps_balsa_cap_hybrid_10mm__t10p0mm__dense_torque_zone_0p20__balsa_cap_collar_y2p328__rear75` | `eps_balsa_cap_hybrid_10mm` | `bounded_75pct_screening` | 6.725351 | 1.614607 | `clears_bound` | 0.59 |

## FEM Calibration Samples

| role | family | fast bounded deg | solver | policy |
|---|---|---:|---|---|
| `baseline_balsa_3mm` | `balsa_sheet_3mm` | 3.256324 | `calculix` | `candidate_structural_credit_requires_FEM_calibration` |
| `selected_hybrid_10mm` | `eps_balsa_cap_hybrid_10mm` | 2.107663 | `apdl_or_calculix` | `candidate_structural_credit_requires_FEM_calibration` |
| `aggressive_plausible_hybrid` | `structural_foam_glass_face_10mm` | 0.749391 | `apdl` | `candidate_structural_credit_requires_FEM_calibration` |
| `lightweight_foam_core_reference` | `eps_hd_foam_cnc_10mm` | 19.944533 | `calculix` | `shape_core_reference_only` |
| `revised_selected_candidate` | `eps_balsa_cap_hybrid_10mm` | 1.673592 | `calculix` | `candidate_structural_credit_requires_FEM_calibration` |

## Outputs

- candidate design table: `/Volumes/Samsung SSD/hpa-mdo/output/current_pathfinder_rib_torsion_design_search/candidate_design_table.csv`
- shortlist: `/Volumes/Samsung SSD/hpa-mdo/output/current_pathfinder_rib_torsion_design_search/shortlist.csv`
- FEM sample set: `/Volumes/Samsung SSD/hpa-mdo/output/current_pathfinder_rib_torsion_design_search/fem_calibration_samples.csv`
- calibration result template: `/Volumes/Samsung SSD/hpa-mdo/output/current_pathfinder_rib_torsion_design_search/fem_calibration_results_template.csv`
- selected closure rerun basis: `/Volumes/Samsung SSD/hpa-mdo/output/current_pathfinder_rib_torsion_design_search/selected_fast_candidate_for_tail_aware_closure_rerun.json`
- CalculiX manifest: `/Volumes/Samsung SSD/hpa-mdo/output/current_pathfinder_rib_torsion_design_search/calculix_manifest.json`
- APDL manifest: `/Volumes/Samsung SSD/hpa-mdo/output/current_pathfinder_rib_torsion_design_search/apdl_manifest.json`

## Engineering Boundary

This output is a fast design-search and FEM-calibration handoff. EPS/XPS foam-only rows are shape-core references only and rear_spar_participation=1.0 is not generated as selected basis.

Fast loop selected eps_balsa_cap_hybrid_10mm__t10p0mm__uniform_0p30__carbon_face_collar_y2p328__rear75 with bounded twist 1.673592 deg. It is ready for FEM calibration across 5 representative samples, not final signoff.
