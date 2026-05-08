# Candidate-Specific Shell Buckling FEM

## Scope

- Candidate: `current_avl_compromise_conservative_closed` / conservative closed run.
- FEM route: Mac-local CalculiX S4 shell eigen-buckling, main spar only.
- Geometry: current candidate jig main-spar centerline, outer radius, and wall thickness.
- Load: current 2G main-spar nodal vertical loads plus the current wire force vector at the wire attach ring.
- Material: `carbon_fiber_hm` as the current isotropic effective tube material.

## Results

| mesh | elements | first lambda | shell buckling n | util at 3G | util at 4G | status |
|---|---:|---:|---:|---:|---:|---|
| coarse | 2880 | 0.824 | 1.648 | 1.820 | 2.427 | GLOBAL_BRACING_FAIL_DIRECTIONAL |
| medium | 6144 | 0.702 | 1.404 | 2.137 | 2.849 | GLOBAL_BRACING_FAIL_DIRECTIONAL |

## Stress-Calibrated Local Wall Coupon

| mesh | L m | D/t | CCX stress MPa | classical MPa | delta % | CCX n | internal n | status |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| coupon_rib_bay_0p30m | 0.30 | 87.3 | 2761.9 | 2693.4 | 2.5 | 15.427 | 12.396 | PASS_DIRECTIONAL |
| coupon_mid_0p60m | 0.60 | 87.3 | 2287.7 | 2693.4 | -15.1 | 12.778 | 12.396 | PASS_DIRECTIONAL |
| coupon_long_1p50m | 1.50 | 87.3 | 1189.6 | 2693.4 | -55.8 | 6.644 | 12.396 | PASS_DIRECTIONAL |

## Engineering Read

- Full main-spar shell deck lowest parsed factor: `lambda = 0.7020` on `medium`, or `n = 1.404G` from the 2G preload.
- Engineering caution: this is a global compression/lateral-bracing mode in an isolated main-spar shell. It is not the local wall-buckling answer and it is not a complete wing truth without rear spar, ribs, and wire-attach load-transfer stiffness.
- After moving the loads into the CalculiX `*BUCKLE` step, the stress-calibrated coupon route is now numerically plausible instead of returning astronomical eigenvalues.
- Lowest long-coupon shell result is `6.644G`; it still clears 3G but is length/global-column sensitive.
- The rib-bay-scale `coupon_rib_bay_0p30m` coupon gives critical stress `2761.9 MPa` versus classical `2693.4 MPa`, delta `2.5%`.
- That maps to local-wall buckling at `n = 15.427G`, so the coupon supports a non-blocking local-wall interpretation through 3G under the conditional assumed rib-bay bracing length.
- The internal buckling estimate remains `n = 12.396G`; the rib-bay shell coupon is now in the same conservative order as the classical/internal screen.
- Engineering conclusion: local wall buckling is a conditional coupon check through 3G for assumed rib-bay braced tube-wall behavior. The remaining unresolved item is global wire-compression bracing / joint load-transfer, not local wall coupon response.

## Blocking Resolution

- Fixed numerically: the CalculiX decks now repeat the active loads inside the `*BUCKLE` step, matching the local CalculiX verification examples. This removes the previous astronomical/unusable eigenvalue blocker.
- Bounded check for this task: candidate-specific CFRP tube local-wall buckling is now checked by a stress-calibrated shell coupon and clears 3G only under assumed rib-bay braced behavior.
- Not honestly passable yet: the full isolated main-spar shell shows a global compression/lateral-bracing mode below 1.75G. That mode is model-scope dominated because the deck omits rear-spar, rib, and wire-attach load-transfer stiffness; it needs a dual-spar/rib/joint load-transfer FEM before being used as a final wing-buckling verdict.
- Engineering decision: the original local-wall buckling numerical blocker is resolved as a conditional coupon check; the remaining blocker has moved to global bracing/load-transfer evidence rather than shell local coupon response.

## Limits Of This FEM

- This is candidate-specific for the main CFRP tube wall, but it is not a detailed root fitting, rib, bonded insert, lug, or wire-attach finite-element model.
- The shell tube uses a smeared ring load at the wire attach station. That is appropriate for tube-wall screening, but it intentionally avoids claiming local lug bearing strength.
- The local-wall coupons are stress-calibrated to the internal 2G compressive stress; they intentionally check tube-wall stability rather than the full wing load path.
- The material is still the current effective isotropic CFRP tube material; final composite local buckling should eventually use laminate ABD/orthotropic shell properties and knockdowns.
- The full main-spar shell result should not be used alone as final failure truth because the real wing is not an isolated main spar with no rear-spar/rib bracing.

- Reference 2G equivalent tip deflection used by the load-factor model: `1.543162 m`.
- Current effective tip deflection gate: `2.550000 m`.
