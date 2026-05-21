# Final HPA Grid-Independence Verdict

Verdict: `grid_independence_not_demonstrated_yet`

The latest route-smoke is successful, but grid independence is not demonstrated.

## Required Answers

1. Operating conditions: current CFD basis is `recent_successful_openfoam_fullwing_mirror` with `rho=1.225`, `V=6.5`.
2. y+ acceptable on latest successful route: yes on upper/lower real airfoil walls (`mean=0.5678595352296987`, `p95=1.0904245`, `max=2.65697`), but not a final all-wall/tip-vortex sign-off.
3. BL layer count/growth: growth is acceptable by generator default, but explicit layer count and total thickness must be documented before final sign-off.
4. LE / TE / wake / tip refinement: TE open-cell and wrong-oriented-face blockers are repaired in `fine_te_radial_chord_shift_run`, but wake/tip diagnostics are not yet compared across a passed C/M/F family.
5. Same mesh strategy: not yet proven by a strict-clean Coarse/Medium/Fine run.
6. checkMesh: latest route-smoke passes solver-smoke gate; repaired Fine has no open/negative/wrong-oriented cells but still fails `1` strict meshQuality check.
7. force histories: latest route-smoke stable; repaired Fine solver status is `runaway_guard_triggered_at_pseudo_time_1`.
8. CL/CD/Cm grid independence: not demonstrated.
9. Cp/Cf stability: not yet compared.
10. Wake/tip vortex stability: not yet compared.
11. Can CD around 0.0315 be trusted: no, not for design power.
12. Can design power be updated from 174W: no. Do not update design power.
13. Exact blocker: `strict C/M/F family gate not passed; Fine has inherited determinant/twist warning and no stable force window`; the new C/M/F checkMesh reports show strict-clean failure on all three rungs, so stable force histories and Cp/Cf/wake/tip comparisons are intentionally not run yet.
