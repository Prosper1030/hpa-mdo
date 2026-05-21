# Final HPA Grid-Independence Verdict

Verdict: `grid_independence_not_demonstrated_yet`

The generator/checkMesh workflow is now stable enough to enter the formal
solver campaign, but grid independence is not demonstrated.

## Required Answers

1. Operating conditions: current CFD basis is `recent_successful_openfoam_fullwing_mirror` with `rho=1.225`, `V=6.5`, `nu=1.4607e-5`, `AoA=0.18 deg`, `Sref=33.420059598 m^2`, and `Cref=1.003721543 m`.
2. y+ acceptable on current coarse same-family probe: yes on real upper/lower airfoil walls (`mean=0.545112`, `p95=1.34603`, `max=3.01407`). Artificial physical-tip cap walls report large diagnostic y+ and are excluded from physical drag and y+ acceptance.
3. BL layer count/growth: growth `1.12` and first layer `7e-5 m` are acceptable for the current real-wall y+ probe; every final rung still needs its own y+ report.
4. LE / TE / wake / tip refinement: the old TE open-cell and wrong-oriented-face failures are repaired, and all rungs keep the same LE/TE/BL/wake/tip/farfield refinement logic. Wake/tip diagnostics are not yet compared from solver-complete Medium/Fine runs.
5. Same mesh strategy: yes for the generated Coarse/Medium/Fine family (`1.335M`, `3.136M`, `6.090M` cells), with the same topology and local refinement contract.
6. checkMesh: all three current rungs pass strict `checkMesh -meshQuality` with open cells `0`, negative volumes `0`, wrong-oriented face pyramids `0`, and failed checks `0`.
7. force histories: coarse 160-iteration potential-initialized probe completes, but the last-50 force window is not stable (`Cd` relative span about `9.9%`, `Cl` about `8.6%`). Medium/Fine stable histories are not complete.
8. CL/CD/Cm grid independence: not demonstrated.
9. Cp/Cf stability: not yet compared.
10. Wake/tip vortex stability: not yet compared.
11. Can CD around 0.0315 be trusted: no, not for design power.
12. Can design power be updated from 174W: no. Do not update design power.
13. Exact remaining verification requirement: run the same-family Medium and Fine solver cases with the current potential-initialized workflow until stable CL/CD/Cm windows, then compare y+, Cp, Cf, wake, and tip-vortex behavior. Until that is done, `CD≈0.0315` is not trusted.
