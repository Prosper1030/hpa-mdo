# Recommended Next Actions

1. Keep `archive_source_quality` and `actual_sidecar_query_quality` separate in reports. Do not replace archive labels in the full-polar database.
2. Treat DAE11 as actual-sidecar-query acceptable for this studied operating point, but keep the archive caveat visible until the team explicitly accepts actual-envelope grading as policy.
3. Keep Policy C as the conservative baseline for mission-grade reporting: it passes both archive and actual-sidecar-query labels.
4. Do not automatically gap-fill broadly from this run. The only clean actual-sidecar coverage recommendation is DAE31 at the tip; run that targeted lower-Cl tip gap-fill only if a no-ClarkY or DAE31-tip option remains important. Most CST and DAE41 failures are `discontinuous_cd` or record-level quality issues, not missing actual-envelope coverage.
5. If actual-query grading becomes a production policy later, implement it as a diagnostics-first sidecar label with tests, not as a hard gate or ranking change in this report pass.
