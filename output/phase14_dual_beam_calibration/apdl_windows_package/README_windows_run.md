# Phase 14 APDL Windows Package

This package is validation tooling only. Do not use these results to change aerodynamic ranking, hard gates, dual_beam_production physics, or calibration factors.

## Steps

1. Copy this whole folder to the Windows machine that has ANSYS Mechanical APDL.
2. Open ANSYS Mechanical APDL.
3. In APDL, set working directory to this folder.
4. Run `run_all_phase14.mac`.
5. Wait until all four decks finish.
6. Send back `phase14_apdl_results.csv`.

## Files

- `run_all_phase14.mac`: one-click runner.
- `phase14_b2_tapered_tube.mac`: B2 tapered hollow tube BEAM188/CTUBE check.
- `phase14_b5_single_torsion.mac`: B5 single tube torsion check.
- `phase14_b5_dual_direct_my.mac`: simplified dual-beam direct MY case.
- `phase14_b5_dual_force_couple.mac`: simplified dual-beam vertical-force-couple case.
- `expected_values.csv`: Mac-local references to compare against.

The runner recreates `phase14_apdl_results.csv` automatically in the same folder.
`expected_values.csv` may include several references for the same APDL metric:
beam/theory rows are the primary APDL comparison targets, while rows whose
source contains `shell_fem` are Mac-local sanity evidence and should not be used
as calibration factors.
