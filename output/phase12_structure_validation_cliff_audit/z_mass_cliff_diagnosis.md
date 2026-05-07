# Z Mass Cliff Diagnosis

## What Was Re-run

I reran the canonical z-state path with the smooth Tier2 baseline, fixed current AVL spanwise load ownership, `refresh_steps=0`, `dihedral_exponent=1`, and the same coarse reduced-variable grids used by the Phase 11 MVP. The new fine sweep is written to `smooth_z_cliff_sweep.csv` and the detailed neighboring cases are in `z_mass_cliff_cases.csv`.

## Observed Cliff

The cliff is between `target_main_tip_z = 2.000 m` and `2.025 m`:

| target main tip z | beam-line dihedral | tube mass | total structural mass | selected branch | tip deflection proxy | jig clearance | wire tension |
|---:|---:|---:|---:|---|---:|---:|---:|
| 2.000 m | 6.645 deg | 77.014 kg | 79.514 kg | 8 mm thick-wall branch | -0.102 m | 0.0652 m | 256.2 N |
| 2.025 m | 6.728 deg | 15.519 kg | 18.019 kg | thin-wall large-radius branch | 1.188 m | 0.0003 m | 2772.5 N |
| 2.100 m | 6.975 deg | 15.519 kg | 18.019 kg | same thin branch | 1.188 m | 0.0312 m | 2772.5 N |
| 2.150 m | 7.139 deg | 14.703 kg | 17.203 kg | lighter rear-radius thin branch | 1.272 m | 0.0005 m | 2831.0 N |

That is not a physically smooth stiffness/mass response. A 25 mm change in requested loaded Z should not by itself produce a 61.5 kg tube-mass drop and a 1.29 m jump in tip deflection if the same continuous design family remains active.

## Why It Jumps

Most likely cause: branch/constraint artifact from the reduced design grid plus clearance boundary.

- At low target Z, the thin-wall/high-deflection branch would backsolve to a very low jig shape. The first sampled thin branch at 2.025 m has only 0.27 mm jig clearance, so the same branch at 2.000 m would be expected to go negative on clearance.
- The selected low-Z branch therefore snaps to a very stiff 8 mm wall design. It has tiny/negative equivalent tip deflection and healthy clearance, but carries huge tube mass.
- The branch variables are at coarse-grid bounds. The heavy branch uses `wall_thickness_fraction=1.0`; the light branch uses `wall_thickness_fraction=0.0` with large main radius variables at their upper bounds. This is branch switching, not gradual sizing.
- Active constraints confirm the branch nature: the heavy branch sits on geometry/radius-dominance and reduced-variable bounds; the first light branch sits on ground clearance and rear-thickness-step limits.

## What It Is Not

- It is probably not a simple tube-mass aggregation bug. Reconstructing mass from radius, thickness, segment lengths, and `carbon_fiber_hm` density matches the reported tube masses within about 0.2 kg for the 77 kg branch and within grams for the light branches.
- It is not a smooth physical proof that 6-7 deg necessarily needs a 75 kg spar. The current fixed-current-spanload sweep shows a discontinuous branch flip.
- It is not enough evidence to reject 6-7 deg HPA cruise dihedral. The same 6 deg target with the synthetic more-inboard load ownership from Phase 12 selected 14.703 kg tube mass instead of 77.014 kg, although it still failed the 11.5 kg target and healthy clearance.

## Constraint Attribution

Ranked causes for the cliff:

1. **Clearance threshold plus inverse-jig backout.** The low-Z target leaves little vertical room for a flexible thin branch. The heavy branch is selected because it keeps jig clearance healthy.
2. **Discrete reduced-variable branch switching.** The MVP grid is only `0.0,1.0` for key variables, so the optimizer snaps between very different recipes instead of walking a continuous sizing curve.
3. **Load ownership sensitivity.** The Phase 12 inboard-load counterexample reduces 6 deg tube mass drastically, proving the selected branch depends on spanload/load mapping.
4. **Validation uncertainty in `dual_beam_production` and inverse jig.** Even if the branch mechanics are internally consistent, the model has not yet been externally validated enough for final rejection.
5. **Not primarily mass aggregation.** The reported mass follows the tube geometry/density calculation.

## Engineering Read

The 75-77 kg result is best treated as a warning that the current low-Z target, current load ownership, current single-wire geometry, and current coarse reduced-variable design space are producing a clearance-driven stiff branch. It is not yet a final structural requirement.
