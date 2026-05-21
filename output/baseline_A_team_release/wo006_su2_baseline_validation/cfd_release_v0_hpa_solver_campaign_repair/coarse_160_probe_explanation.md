# Coarse 160 Probe Explanation

Verdict: `coarse_160_is_smoke_probe_not_converged_result`

- case: `/Volumes/Samsung SSD/hpa-mdo/output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0_hpa_grid_independence_verification/coarse_solver_probe/openfoam_cases/coarse/fullwing_artificial_tip_symmetry`
- controlDict endTime: `160`
- executed command: `simpleFoam`
- simpleFoam returncode: `0`
- elapsed seconds: `494.93955854093656`
- stopped by runtime timeout: `False`
- stopped by force guard: `False`
- runaway time: `None`

The probe stopped at 160 iterations because the run was launched with
`--first-iterations 160 --final-iterations 160`; the workflow therefore
wrote `endTime 160` into `system/controlDict`. It was not stopped by the
force guard or by an OpenFOAM error.

## Stability Read

- rows in primary force history: `160`
- final-50 primary drift: `{"Cd": {"last": 0.06088113, "rel_span": 0.09861459639525562}, "Cl": {"last": 0.8584368, "rel_span": 0.08628039474943207}, "CmPitch": {"last": -0.0970012, "rel_span": 0.10514774111454997}}`
- final-100 primary drift: `{"Cd": {"last": 0.06088113, "rel_span": 0.4145012513841721}, "Cl": {"last": 0.8584368, "rel_span": 0.4890453724884563}, "CmPitch": {"last": -0.0970012, "rel_span": 0.35183579965225753}}`
- final-100 total_physical drift: `{"Cd": {"last": 0.06110341, "rel_span": 0.4129125647238874}, "Cl": {"last": 0.858412, "rel_span": 0.48906114811332946}, "CmPitch": {"last": -0.09679694, "rel_span": 0.35490261815348717}}`

`CL_primary≈0.858` is not an accepted aerodynamic result. The case has
fewer than 500 iterations and fails the requested final-100 stability gate.

## CL/CD Trend

| iteration | CD_primary | CL_primary | CmPitch_primary |
|---:|---:|---:|---:|
| 1 | 0.05127724 | 0.11182 | -0.004847059 |
| 10 | 0.02457192 | 0.2790552 | -0.02356198 |
| 25 | 0.09857021 | 0.3895461 | -0.01961627 |
| 50 | 0.072212 | 0.4059996 | -0.06341712 |
| 100 | 0.07176497 | 0.7387837 | -0.08615248 |
| 125 | 0.06436642 | 0.8368096 | -0.09563048 |
| 150 | 0.06111723 | 0.8590607 | -0.09714897 |
| 160 | 0.06088113 | 0.8584368 | -0.0970012 |
