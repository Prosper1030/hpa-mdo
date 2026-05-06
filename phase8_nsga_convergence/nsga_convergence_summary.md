# Phase 8 NSGA Convergence Summary

This is a report-only analysis. It does not change Fourier settings, rerun CST/NSGA, build the full-alpha database, change aircraft ranking, or add hard gates.

Quality labels are kept separate: screening quality/score comes from the target-Cl CST/NSGA database; `archive_source_quality` comes from the full-polar archive; `actual_sidecar_query_quality` comes from the actual-sidecar-envelope regrade; repair-worthy/repaired status comes from Phase 7/7.1 diagnostics.

## Zone Verdicts

| zone | classification | g0 best score | g7 best score | improvement | g7 mission-grade | global Pareto front | late g5-g7 best IDs | read |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
| root | feasibility-saturated but performance still improving | 0.040915 | 0.027923 | 31.8% | 116/128 | 106 | `cst_root_nsga2_g05_child_0042_253b24ef;cst_root_nsga2_g06_child_0037_2ed236ac;cst_root_nsga2_g07_child_0117_6874eb7b` | Root is not converged. Feasibility is mostly saturated by g6-g7, but best and median score keep improving late. |
| mid1 | still improving | 0.083825 | 0.028691 | 65.8% | 90/128 | 43 | `cst_mid1_nsga2_g05_child_0068_b9794b28;cst_mid1_nsga2_g06_child_0046_9ca15362;cst_mid1_nsga2_g07_child_0120_6ba170d3` | Mid1 is still improving. Mission-grade count and median score are still moving late, even though the best scalar score regresses slightly from g6 to g7. |
| mid2 | feasibility-saturated and near performance-converged | 0.015021 | 0.014595 | 2.8% | 128/128 | 209 | `cst_mid2_nsga2_g05_child_0125_08c4ee49;cst_mid2_nsga2_g06_child_0115_eaea30b5;cst_mid2_nsga2_g07_child_0018_8980e10b` | Mid2 is feasibility-saturated from g0 and close to performance-converged in sparse screening; late generations do not beat the early/g4 best score. |
| tip | under-explored at full-alpha quality despite screening feasibility saturation | 0.014571 | 0.014556 | 0.1% | 128/128 | 216 | `cst_tip_nsga2_g05_child_0015_2813f3a4;cst_tip_nsga2_g06_child_0101_f4c46cf4;cst_tip_nsga2_g07_child_0106_1ef5b689` | Tip is feasible from g0, but under-explored in full-alpha quality because sparse screening passes almost everything while full-polar repairs remain decisive. |

## Convergence Notes

- Root and mid1 show real late-generation movement. Treat them as useful but not converged search spaces.
- Mid2 and tip are feasibility-saturated under target-Cl screening: every generation has 128/128 screening mission-grade candidates.
- ID-level top-16 overlap between adjacent generations is zero because each generation emits new child IDs rather than carrying the same record forward. That field is still reported, but metric stabilization is more informative than ID reuse for this artifact.
- Large Pareto fronts in mid2/tip mean the sparse screening objective is not selective enough to decide the next winner by itself; full-alpha quality should become the next discriminator.

## Output Files

- `nsga_convergence_by_zone.csv`: generation-level metrics and classifications.
- `full_alpha_candidate_manifest.csv`: unique airfoil manifest for all current CST records plus references, with tier flags and separate quality labels.
- `full_alpha_candidate_tiers.csv`: candidate counts, point estimates, runtime multipliers, and storage estimates.
