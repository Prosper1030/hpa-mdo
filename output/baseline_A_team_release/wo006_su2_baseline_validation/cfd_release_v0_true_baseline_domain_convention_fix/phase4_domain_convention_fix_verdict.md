# Phase 4 Domain Convention Fix Verdict

1. Is the current mesh half-wing or full-wing?
   - `half-wing`
2. Which patch was wrongly treated as physical wall?
   - `tip_left`
3. Was root_symmetry correctly applied if needed?
   - `True`
4. What reference area convention is used?
   - `half-wing raw forces normalized by half-wing Sref; coefficients are also full-wing-equivalent under mirror symmetry`
5. What are corrected CD_primary and CL_primary?
   - `{'status': 'not valid; solver force history unstable before 500 iterations', 'last_unstable_CD_primary': 1.889339, 'last_unstable_CL_primary': 6.774819}`
6. What are corrected CD_total and diagnostic CD sum?
   - `{'status': 'not valid; solver force history unstable before 500 iterations', 'last_unstable_CD_total': 1.921214, 'diagnostic_CD_sum_excluding_root': 0.031875359, 'diagnostic_fraction': 0.016591258964383977}`
7. Did yPlus remain wall-resolved?
   - `False`
8. Is diagnostic patch contamination resolved?
   - `True`
9. Is the result ready for AoA/CL sweep?
   - `False`
10. Is it comparable to XFOIL yet, or only ready for comparable-CL sweep?
   - `Only ready for comparable-CL sweep; do not compare to XFOIL until CL target is matched.`
