# Phase 7 Recommended Next Actions

1. Conservative baseline for reports: Policy C / E. It passes both archive and actual-sidecar query quality, so it is the cleanest external/reporting baseline.
2. Performance candidate to keep: Policy A / D. It is the best actual-query performance candidate and should stay visible as the likely lower-drag option.
3. DAE11 is acceptable under the actual sidecar loading studied here. Root and mid1 actual Cl demand sit below DAE11 safe_clmax with positive margin.
4. DAE11 should remain archive-caveated. The caveat is conservative-envelope margin, not a current-operating-point failure.
5. CST candidates are close enough to justify repair before broad search. Several failed candidates have good actual Cd and safe-Cl margin, but are blocked by localized `discontinuous_cd` behavior.
6. Repair CST candidates first: cst_mid2_seedless_sobol_0619_a07c5c7e, cst_tip_nsga2_g02_child_0085_cb99bc9c, cst_root_nsga2_g03_child_0090_3408e0ca, cst_tip_nsga2_g06_child_0101_f4c46cf4, cst_mid2_nsga2_g04_child_0012_72b8e600.
7. Do not rerun broad NSGA yet. First run targeted CST polar repair/verification for the top discontinuous-Cd candidates and DAE31-tip coverage if the no-ClarkY branch remains important.
8. Do not hard-gate yet and do not change ranking. Keep `archive_source_quality` and `actual_sidecar_query_quality` separate until a repaired-polar evidence packet justifies a policy change.
9. Next engineering step before changing ranking or gates: run a small, auditable repair diagnostic that preserves raw XFOIL/JXFoil points, classifies branch behavior near design Cl, and compares repaired CST root/mid/tip candidates against Policy A and Policy C.

Expected conclusion: Conservative baseline for reports is Policy C; performance candidate to keep is Policy A; do not hard-gate; do not rerun broad NSGA; first diagnose/repair top CST discontinuous-Cd candidates; keep archive and actual-sidecar quality labels separate.
