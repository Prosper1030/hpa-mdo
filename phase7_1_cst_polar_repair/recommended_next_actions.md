# Phase 7.1 Recommended Next Actions

1. Keep Policy C/E as the conservative reporting baseline and Policy A/D as the performance candidate.
2. Do not change production ranking, hard gates, or global archive labels from this diagnostic run.
3. Full diagnostic repair candidates to consider for a separate reviewed archive patch: cst_mid2_seedless_sobol_0619_a07c5c7e, cst_root_nsga2_g03_child_0090_3408e0ca, cst_tip_nsga2_g06_child_0101_f4c46cf4, cst_mid2_nsga2_g04_child_0012_72b8e600.
4. Actual-sidecar-only repair candidates can be used as sidecar diagnostics, not conservative archive baselines: cst_tip_nsga2_g02_child_0085_cb99bc9c.
5. No repaired candidate remains in reject/manual-review class under the diagnostic criteria.
6. Before any ranking or gate change, package a reviewed repaired-polar archive artifact with raw points, branch labels, and clean/rough evidence.
7. Do not rerun broad NSGA until the repaired CST evidence is accepted or rejected.
