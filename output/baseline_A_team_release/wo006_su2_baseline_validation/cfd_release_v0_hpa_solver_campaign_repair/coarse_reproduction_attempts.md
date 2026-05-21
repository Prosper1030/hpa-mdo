# Coarse Reproduction Attempts

Verdict: `coarse_not_accepted_do_not_run_medium_or_fine`

| attempt | setup change | end time | CD_primary | CD_total_physical | CL_primary | final-100 accepted | reference reproduced |
|---|---|---:|---:|---:|---:|---|---|
| 160 probe | none; original smoke/probe limit | 160 | 0.06088113 | 0.06110341 | 0.8584368 | false | false |
| extended run | none; same locked Coarse setup | 500 | 0.05266464 | 0.05285709 | 0.9571043 | false | false |
| manual continuation | none; same case continued from latestTime 500 to 1000 | 1000 | 0.04178047 | 0.04190350 | 1.074658 | false | false |

No AoA, Re, rho, viscosity, turbulence model, Sref/Cref, force patch, or
artificial closure treatment was changed. The 500-to-1000 continuation was
required because the original wrapper stopped under the older route-smoke gate;
the current runner logic has been corrected to use the requested HPA final-100
gate for future runs.

The Coarse case is still not accepted at 1000 iterations:

- final-100 `CD_total_physical` relative drift: `0.0404822`
- final-100 `CD_primary` relative drift: `0.0403195`
- final-100 `CL_primary` relative drift: `0.01656`
- final-100 `CmPitch` relative drift: `0.01326`
- CL error vs user target `1.130726`: `-4.96%`
- CD_total_physical error vs user target `0.031823`: `+31.68%`

Phase 4 correction attempts were not entered because the precondition for that
phase was not met: Coarse did not settle to a stable low-CL result. The observed
behavior is still moving force history, not an accepted stable but wrong
aerodynamic state.
