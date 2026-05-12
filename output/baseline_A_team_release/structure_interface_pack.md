# Structure Interface Pack

P1 is ready for coupon/local FEM, not final build.

## Current Structural Read

- C04 original peel path fails: margin `-0.893`.
- Selected fix: `saddle_ring_yoke_plus_secondary_clamp`.
- Installed surrogate pass, governing clamp margin `0.8876`.
- C04 fix mass: `0.093839 kg`.
- Spar splice mass: `3.847 kg`.

## Assigned Work

- Build saddle/yoke/clamp coupon matrix and coupon FEM correlation.
- Run C04 local FEM with adhesive, lug bearing, clamp preload, and tube wall contact.
- Build 1 m wing-bay v2 to check rib/collar load path and skin sag.
- Keep direct spar-pair stress-test as a conservative mapping warning until aero-surface mapping is qualified.

## Engineering Caveat

The C04 fix removes the eccentric peel load path in the screening model. It does not prove adhesive durability, tube-wall ovalization, local buckling, or shop repeatability.
