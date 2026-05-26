# Turbulence and Transition Risk Report

## Current model mismatch

The accepted OpenFOAM reference and the old XFOIL+AVL estimate are not using the same boundary-layer physics basis.

| Item | Old XFOIL + AVL | Current OpenFOAM |
|---|---|---|
| 3D lift/induced model | AVL inviscid vortex lattice | 3D RANS force integration |
| Profile drag | XFOIL section polars | RANS wall/shear plus pressure/form |
| Transition basis | clean XFOIL by default | no transition model |
| Turbulence model | not applicable to AVL; XFOIL e^N transition | Spalart-Allmaras |
| Clean XFOIL settings | `Ncrit=9`, `xtrip=(1.0,1.0)` | not applicable |
| Rough XFOIL settings available | `Ncrit=5`, `xtrip=(0.05,0.05)` | not applicable |
| Re range | about 0.29M to 0.57M | about 0.29M to 0.56M |

The CFD setup has `transition_model=none` and `turbulence_model=SpalartAllmaras`. For this low-Re HPA wing, that is a major modeling assumption. At these Reynolds numbers, laminar run, transition location, laminar separation bubbles, surface waviness, contamination, and airfoil-specific bucket behavior can dominate profile drag.

## Existing-data transition sensitivity

No new XFOIL runs were needed for this check. The existing Tier2 database contains both clean and rough modes.

Using the exact old station `Re`, local AVL `cl`, and airfoil assignment:

| XFOIL mode | Settings | Integrated profile CD |
|---|---|---:|
| clean/default | `Ncrit=9`, `xtrip=(1.0,1.0)` | 0.009368851 |
| rough | `Ncrit=5`, `xtrip=(0.05,0.05)` | 0.023487768 |

This is a `+0.014118917` CD increase in profile drag from transition/roughness treatment alone. That is larger than the CFD-vs-old-wing-only gap of `+0.011135409`.

If the real wing or the RANS model behaves closer to early-transition/fully turbulent than clean natural transition, the old XFOIL+AVL wing-only `0.02213` is likely too low.

## Why fully turbulent SA could explain higher CD

Fully turbulent or early-transition treatment can plausibly raise drag by the right magnitude because:

- the old clean profile drag includes very low outboard XFOIL values, including `cd` values near `0.0003` to `0.003` in the low-`cl` tip region;
- the inboard/mid-span sections operate at high local `cl` around `1.2` to `1.34`, where transition and separation-bubble behavior are sensitive;
- SA RANS does not model natural transition and tends to remove laminar-bucket benefit;
- wall-resolved-ish yPlus is acceptable for force extraction, but good yPlus does not validate transition physics.

## Why this does not automatically validate CFD

The CFD pressure drag is `0.02295001`, and after subtracting an AVL-like induced estimate, the remaining pressure/form residual is about `0.01035`. That is large enough to require skepticism.

Possible CFD-side risks:

- SA fully turbulent drag may be an upper-bound rather than a mission-realistic value;
- pressure/form residual may include numerical wake, trailing-edge, or mesh-form effects;
- the accepted artifacts do not yet provide spanwise or upper/lower force decomposition;
- RANS agreement after grid independence does not prove the turbulence/transition formulation is physically correct.

## Bounded next test

Do not run a new grid ladder.

The next bounded CFD diagnostic should use the accepted Fine mesh and the same force definitions, then run one turbulence/transition sensitivity bracket:

1. Keep geometry, mesh, AoA, `Sref`, `Cref`, force groups, and final-window acceptance checks fixed.
2. Run a transition-capable model if available in the local OpenFOAM stack, preferably a transition SST / gamma-Re-theta-style model.
3. If transition SST is not available, run a tightly bounded laminar-vs-SST or laminar-vs-SA bracket on the same Fine mesh as a diagnostic, not as a design update.
4. Stop at the same force-window/stability criteria used for the accepted Fine case; do not extend into a new refinement study.
5. Compare `CD_total_physical`, pressure/viscous split, and `CL_primary` against:
   - clean XFOIL+AVL wing-only `0.02213015`;
   - rough XFOIL+AVL wing-only `0.03624907`;
   - current SA Fine `0.03326556`.

Expected interpretation:

- If transition/laminar sensitivity drops toward the clean XFOIL+AVL value, current SA is likely overpredicting for a smooth clean mission assumption.
- If transition/SST remains near `0.033`, the old clean XFOIL+AVL estimate is likely underpredicting operational drag.
- If the pressure residual remains large and unexplained, force decomposition should be instrumented before any power update.
