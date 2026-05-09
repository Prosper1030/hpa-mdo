# Current Pathfinder Rib / Torsion Fast Design Search

Candidate: `current_avl_compromise_conservative_closed`
Verdict: `fast_design_loop_ready_for_fem_calibration`

## Selected Fast Candidate

- case: `eps_balsa_cap_hybrid_10mm__t10p0mm__manufacturing_relaxed_0p36__carbon_face_collar_y2p328__rear75`
- family / group: `eps_balsa_cap_hybrid_10mm` / `hybrid_foam_balsa_cap`
- thickness / spacing / local reinforcement: `10.0` mm / `manufacturing_relaxed_0p36` / `carbon_face_collar_y2p328`
- rear-spar participation: `bounded_75pct_screening`
- fast direct / bounded twist: `2.446107` deg / `1.471349` deg
- mass / CG / rebalance: `5.071237` kg / `0.75` m / `0.080789` m
- tail trim / SM / C_n_beta: `4.786933` deg / `0.094301` / `0.01403`
- evidence: `fast_model_result_needs_FEM_calibration`

## Shortlist

| case | family | rear | mass kg | bounded twist deg | direct status | manuf |
|---|---|---|---:|---:|---|---:|
| `eps_balsa_cap_hybrid_10mm__t10p0mm__manufacturing_relaxed_0p36__carbon_face_collar_y2p328__rear75` | `eps_balsa_cap_hybrid_10mm` | `bounded_75pct_screening` | 5.071237 | 1.471349 | `clears_bound` | 0.6 |
| `eps_balsa_cap_hybrid_10mm__t12p0mm__manufacturing_relaxed_0p36__carbon_face_collar_y2p328__rear75` | `eps_balsa_cap_hybrid_10mm` | `bounded_75pct_screening` | 6.015484 | 1.203972 | `clears_bound` | 0.55 |
| `eps_balsa_cap_hybrid_10mm__t8p0mm__torque_zone_0p24_outboard_0p36__carbon_face_collar_y2p328__rear75` | `eps_balsa_cap_hybrid_10mm` | `bounded_75pct_screening` | 4.899556 | 1.602067 | `clears_bound` | 0.44 |
| `eps_balsa_cap_hybrid_10mm__t10p0mm__manufacturing_relaxed_0p36__glass_face_collar_y2p328__rear75` | `eps_balsa_cap_hybrid_10mm` | `bounded_75pct_screening` | 5.141237 | 1.575618 | `clears_bound` | 0.66 |
| `eps_balsa_cap_hybrid_10mm__t10p0mm__uniform_0p30__carbon_face_collar_y2p328__rear75` | `eps_balsa_cap_hybrid_10mm` | `bounded_75pct_screening` | 5.715042 | 1.353641 | `clears_bound` | 0.55 |
| `eps_balsa_cap_hybrid_10mm__t8p0mm__uniform_0p30__carbon_face_collar_y2p328__rear75` | `eps_balsa_cap_hybrid_10mm` | `bounded_75pct_screening` | 4.642034 | 1.730233 | `clears_bound` | 0.5 |
| `eps_balsa_cap_hybrid_10mm__t10p0mm__torque_zone_0p24_outboard_0p36__carbon_face_collar_y2p328__rear75` | `eps_balsa_cap_hybrid_10mm` | `bounded_75pct_screening` | 6.036945 | 1.253371 | `clears_bound` | 0.49 |
| `eps_balsa_cap_hybrid_10mm__t12p0mm__manufacturing_relaxed_0p36__glass_face_collar_y2p328__rear75` | `eps_balsa_cap_hybrid_10mm` | `bounded_75pct_screening` | 6.085484 | 1.289293 | `clears_bound` | 0.61 |
| `eps_balsa_cap_hybrid_10mm__t10p0mm__manufacturing_relaxed_0p36__carbon_face_collar_y2p328__rear65` | `eps_balsa_cap_hybrid_10mm` | `bounded_65pct_screening` | 5.071237 | 1.654664 | `clears_bound` | 0.6 |
| `eps_balsa_cap_hybrid_10mm__t10p0mm__manufacturing_relaxed_0p36__balsa_cap_collar_y2p328__rear75` | `eps_balsa_cap_hybrid_10mm` | `bounded_75pct_screening` | 4.901237 | 1.755293 | `clears_bound` | 0.76 |
| `eps_balsa_cap_hybrid_10mm__t12p0mm__manufacturing_relaxed_0p36__balsa_cap_collar_y2p328__rear75` | `eps_balsa_cap_hybrid_10mm` | `bounded_75pct_screening` | 5.845484 | 1.436317 | `clears_bound` | 0.71 |
| `eps_balsa_cap_hybrid_10mm__t8p0mm__torque_zone_0p24_outboard_0p36__glass_face_collar_y2p328__rear75` | `eps_balsa_cap_hybrid_10mm` | `bounded_75pct_screening` | 4.969556 | 1.7156 | `clears_bound` | 0.5 |

## FEM Calibration Samples

| role | family | fast bounded deg | solver | policy |
|---|---|---:|---|---|
| `baseline_balsa_3mm` | `balsa_sheet_3mm` | 3.256324 | `calculix` | `candidate_structural_credit_requires_FEM_calibration` |
| `selected_hybrid_10mm` | `eps_balsa_cap_hybrid_10mm` | 2.070316 | `apdl_or_calculix` | `candidate_structural_credit_requires_FEM_calibration` |
| `aggressive_plausible_hybrid` | `structural_foam_glass_face_10mm` | 0.508631 | `apdl` | `candidate_structural_credit_requires_FEM_calibration` |
| `lightweight_foam_core_reference` | `eps_hd_foam_cnc_10mm` | 19.944533 | `calculix` | `shape_core_reference_only` |

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

Fast loop selected eps_balsa_cap_hybrid_10mm__t10p0mm__manufacturing_relaxed_0p36__carbon_face_collar_y2p328__rear75 with bounded twist 1.471349 deg. It is ready for FEM calibration across 4 representative samples, not final signoff.
