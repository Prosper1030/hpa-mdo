# WO-006 Transition/Turbulence Drag-Gap Diagnosis

## Verdict

Usable as engineering diagnostic, not usable as final transition-SST drag.

The 50% gap is now narrowed: the largest suspect is the old clean XFOIL profile basis, with 3D pressure/form/wake residual second. A pure SA-vs-transition-model overprediction is unlikely to explain the full gap by itself. The original 3D LM `CD=0.0387` remains rejected.

## Locked Comparison Basis

| Quantity | CD |
|---|---:|
| Old clean XFOIL profile | 0.00936885 |
| Old AVL induced | 0.01276130 |
| Old clean XFOIL+AVL wing-only | 0.02213015 |
| Accepted OpenFOAM SA Fine total physical | 0.03326556 |
| Gap | 0.01113541 (50.3%) |
| Existing rough XFOIL profile | 0.02348777 |
| Existing rough XFOIL+AVL wing-only | 0.03624907 |

Do not add AVL induced drag to OpenFOAM wing CD. OpenFOAM already includes finite-wing pressure forces on the 3D wing patches.

## Why The First 3D LM Run Exploded

The first LM setup used `L=0.07 c_ref`, `omega=1.034 1/s`, `k=0.001584 m2/s2`, giving an estimated freestream `nut/nu = k/(omega nu) = 104.9`. That is high for a clean 0.5% Tu external-flow inlet. In the failed run, `omega` was bounded from the first SIMPLE step and grew to `max omega = 3.992e+20` with 62 omega-bounding events. This is a setup/numerics failure, not a drag result.

## Bounded 3D Fix Attempts

| Attempt | Change | Result |
|---|---|---|
| LM L=0.007c | `omega=10.34`, `nut/nu≈10.5`, low relaxation, upwind turbulence | no omega bounding for 5 steps; CD diagnostic 0.031791 |
| LM L=0.001c | `omega=72.40`, `nut/nu≈1.5`, same conservative numerics | no omega bounding through 2020; CD diagnostic 0.030939 |
| LM L=0.001c + T3A scalar BC | farfield fixedValue, outlet zeroGradient for transition scalars | same 5-step response as freestream BC |
| SST L=0.001c warm-start | ordinary SST with same k/omega scale | stable, no LM correlation warnings; CD diagnostic 0.0317782 |

At 2020 the corrected LM diagnostic split was `CD=0.030939`, pressure `0.021969`, viscous `0.008970`, `CL=1.16017`. It is about `7.0%` below accepted SA Fine, not 50% below. It still has one `ReThetat0 maxLambdaIter` warning per step, so it is not final transition evidence.

Latest corrected LM field min/max at 2020: `gammaInt=0.0771318..1.00004`, `ReThetat=588.689..1042.78`, `max nut/nu≈5.29`.

## Section Sanity

| Station | eta | Re | cl | Airfoil | clean XFOIL cd | rough XFOIL cd | rough/clean |
|---|---:|---:|---:|---|---:|---:|---:|
| root | 0.000 | 568130 | 1.2989 | dae31 | 0.00912 | 0.02389 | 2.62 |
| mid | 0.491 | 446088 | 1.3120 | dae31 | 0.01000 | 0.02664 | 2.66 |
| outboard | 0.802 | 360197 | 0.7787 | cst_tip_nsga2_g05_child_0032_70ef8136 | 0.01255 | 0.01615 | 1.29 |


The existing section-level rough bracket is much larger than clean XFOIL: DAE31 root/mid increases by about 2.6x, and the outboard CST tip increases by about 1.3x at the selected local Re/cl. The integrated rough profile CD `0.02348777` plus the same AVL induced CD gives `0.03624907`, which is above the accepted SA Fine wing CD. That means transition/roughness treatment alone can create a shift of the same order as the observed 50% gap.

2D OpenFOAM section RANS was not credited: the available root, intermediate, and tip OpenFOAM section meshes fail `checkMesh` gates, including non-closed cells/wrong-oriented faces for root/intermediate and determinant/skew failures for the tip. Running SA/SST/LM on those would create solver-looking numbers without engineering meaning. No new grid refinement was performed.

## Pressure/Form Check

Accepted SA Fine split: pressure `0.02295001`, viscous `0.01031555`. If an AVL-like induced drag of about `0.01259593` is subtracted from pressure, residual pressure/form/wake CD is about `0.01035408`. That is roughly another clean-XFOIL-profile-sized contribution, so 3D pressure/wake/TE/tip/form effects remain a real suspect even if XFOIL clean is optimistic.

## Suspect Ranking

1. **B: old XFOIL profile too optimistic**. Strongest evidence: clean-to-rough XFOIL bracket spans more than the full observed gap.
2. **C: 3D pressure/wake/tip/TE/form residual**. Strong evidence: pressure drag after induced estimate still leaves about `CD=0.01035` unexplained by clean 2D profile drag.
3. **A: SA/fully turbulent model high for clean mission condition**. Contributes, but bounded LM/SST probes suggest it is not enough alone: corrected LM at 2020 is only about `21%` of the old-clean gap lower than SA.
4. **D: transition setup not yet final**. True for final LM drag, but no longer the only answer: the corrected setup removes catastrophic omega growth through 2020 while retaining LM correlation warnings.

## Next Minimum Experiment

Do not update design power. The next minimum experiment is not grid refinement; it is a credible 2D/quasi-2D section mesh gate for the three stations, then run SA/SST/LM on that same accepted section mesh at local Re and alpha/cl. If those section RANS values sit near rough XFOIL, the old clean profile basis is the main culprit. If section RANS sits near clean XFOIL, the 3D pressure/wake decomposition becomes the lead culprit.
