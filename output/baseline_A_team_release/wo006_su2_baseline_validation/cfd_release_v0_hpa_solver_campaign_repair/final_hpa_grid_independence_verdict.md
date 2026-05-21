# Final HPA Grid-Independence Verdict

Verdict: `grid_independence_not_demonstrated`

Operating-condition lock:

The Coarse/reference diff confirms the comparison basis is physically locked:
`rhoInf=1.225`, `nu=1.4607e-05`, `V=6.5 m/s`, `AoA=0.18 deg` by inlet vector,
`Sref=33.420059598 m^2`, `Cref=1.003721543 m`, `RAS/SpalartAllmaras`,
matching `dragDir` / `liftDir`, and matching primary force patches
`airfoil_upper airfoil_lower`.

1. Why did Coarse stop at 160 iterations?
   It was launched as a smoke/probe with `endTime 160`
   (`--first-iterations 160 --final-iterations 160`). It was not stopped by
   timeout, force guard, or OpenFOAM failure.

2. Was `CL_primary≈0.858` under-converged or real?
   Under-converged. The same Coarse setup continued to `CL_primary=0.9571043`
   at 500 and `CL_primary=1.074658` at 1000.

3. Was the successful reference reproduced?
   No. At 1000, Coarse is still `-4.96%` low in CL versus the user-supplied
   `CL_primary=1.130726` target and `+31.68%` high in `CD_total_physical`
   versus `0.031823`.

4. If not, what exact mismatch remains?
   No proven AoA/Re/BC/Sref/Cref/force-definition mismatch was found. The exact
   blocker is that the new Coarse grid-family baseline has not reached a stable
   force window or reference-equivalent force level by 1000 iterations.

5. Did Coarse, Medium, and Fine all run to stable force windows?
   No. Coarse failed the required final-100 gate, so Medium and Fine were not
   run.

6. Are CL, CD, and Cm grid-independent?
   No. The prerequisite stable Coarse baseline is not established.

7. Are yPlus, Cp, Cf, wake, and tip-vortex behavior acceptable?
   Real upper/lower/TE wall yPlus is acceptable on Coarse
   (`mean=0.748`, `p95=1.485`, `max=3.173`). Cp, Cf, wake, and tip-vortex
   grid-family comparisons were not allowed because Medium/Fine remain gated.

8. Can `CD≈0.0315` be trusted?
   No.

9. Can design power be updated from 174 W?
   No.

10. If not, what exact blocker remains?
    Coarse final-100 stability at 1000 fails:
    `CD_total_physical drift=4.05%`, `CD_primary drift=4.03%`,
    `CL_primary drift=1.66%`, and `CmPitch drift=1.33%`. The accepted gate is
    `<1%`, `<1%`, `<0.5%`, and `<1%`, respectively.

Engineering decision:

Do not run Medium/Fine from this state. Do not claim grid independence. Do not
update design power. The next work item must remain a Coarse-only convergence
or mesh-baseline repair until the Coarse force window is stable and reproduces
the reference force level.
