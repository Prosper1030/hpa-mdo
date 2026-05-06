# NSGA v2 Recommendation

Recommendation: do not run NSGA v2 now. Build the full-alpha database first, then use full-alpha quality and actual mission-query evidence to define a narrower NSGA v2.

## Direct Answers

- Is root converged? No. Root is `feasibility-saturated but performance still improving`: g7 is better than g0 by 31.8%, and late g5-g7 best candidates are still changing.
- Is mid1 converged or still improving? Mid1 is still improving. Mission-grade count rises to 90/128 by g7 and the median score continues improving late, even though best score peaks at g6.
- Is mid2 only feasibility-saturated, or performance-converged? Mid2 is feasibility-saturated and near performance-converged for sparse screening. Its best score is from g1/g4, not the final generation, so deeper NSGA is not the immediate lever.
- Is tip under-explored? Yes in the full-alpha-quality sense. Sparse screening feasibility is saturated, but the tip has many equivalent sparse-screening candidates and several full-polar discontinuity repairs, so full-alpha evidence should come first.
- Should we run deeper NSGA before full-alpha database? No.
- Should we build the full-alpha database first and use it to guide NSGA v2? Yes. Tier 1 or Tier 2 gives a better evidence base for deciding root/mid1/tip NSGA v2 targets and filtering branch/discontinuity artifacts.

## Engineering Rationale

- Root/mid1 still benefit from search, but the current bottleneck is quality evidence: sparse target-Cl screening can select candidates that later fail full-polar continuity.
- Mid2/tip are not limited by feasibility in the sparse screen; the uncertainty is polar branch quality, roughness behavior, and real full-alpha Cd around mission demand.
- Running broad NSGA v2 before the full-alpha database risks optimizing toward the same sparse-screening artifacts that Phase 7/7.1 just exposed.
