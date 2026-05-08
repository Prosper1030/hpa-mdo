# Tip Deflection Limit Engineering Review

## What The Limit Means

- The current `max_tip_deflection_m = 2.5 m` is a design-validity gate, not a material rupture limit.
- The feasibility code applies a 2% tolerance, so the effective current gate is `2.55 m`.
- Crossing this gate means the fixed-load, fixed-aero-ranking, small/linear-deflection assumptions are becoming questionable; it does not mean the carbon tube snaps at that instant.

## Sensitivity

| raw limit m | effective limit m | effective / halfspan | deflection-limit n | first limiter with 6kN wire | engineering use |
|---:|---:|---:|---:|---|---|
| 2.50 | 2.55 | 0.149 | 3.305 | tip_deflection | current conservative submission/design gate |
| 2.75 | 2.81 | 0.163 | 3.635 | tip_deflection | reasonable exploration gate only if loaded-shape/aeroelastic checks are rerun |
| 3.00 | 3.06 | 0.178 | 3.966 | tip_deflection | reasonable exploration gate only if loaded-shape/aeroelastic checks are rerun |
| 3.25 | 3.31 | 0.193 | 4.296 | wire_6kn | not recommended without a new aeroelastic/large-deflection validation basis |

## Recommendation

- The current 2.5 m raw limit is conservative but defensible: effective deflection is about 14.9% of halfspan, already large enough that aeroelastic/load-path assumptions deserve respect.
- A modest relaxation to 2.75 m raw looks reasonable for engineering exploration using the current internal/classical buckling screen, because it keeps the deflection gate below the 6 kN wire failure estimate.
- A 3.0 m raw limit can be used as a temporary exploration ceiling if the purpose is to see what happens after the current blocker, but it should trigger a loaded-shape AVL/aeroelastic recheck before being used as a submission number.
- I would not relax beyond 3.0 m raw without a new validation basis. At that point the structural tube may still have stress/buckling margin, but the aircraft-level shape and joint load transfer are the real question.
