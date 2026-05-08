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
| coarse | 2880 | 1974.532 | 3949.064 | 0.001 | 0.001 | UNTRUSTED_FOR_LOCAL_WALL |
| medium | 6144 | 33701.080 | 67402.160 | 0.000 | 0.000 | UNTRUSTED_FOR_LOCAL_WALL |

## Stress-Calibrated Local Wall Coupon

| mesh | D/t | reference stress MPa | raw CCX lambda | raw CCX n | classical n | internal n | status |
|---|---:|---:|---:|---:|---:|---:|---|
| coupon_coarse | 87.3 | 358.1 | 4500908000.000 | 9001816000.000 | 15.044 | 12.396 | UNTRUSTED_NUMERICAL |
| coupon_medium | 87.3 | 358.1 | 7125205000.000 | 14250410000.000 | 15.044 | 12.396 | UNTRUSTED_NUMERICAL |

## Engineering Read

- Full main-spar shell deck lowest parsed factor: `lambda = 1974.5320` on `coarse`, or `n = 3949.064G` from the 2G preload.
- Engineering caution: this full-deck value is very high because the current wire load largely cancels net root vertical load in the simplified main-tube-only model; it is marked untrusted for local-wall buckling.
- Stress-calibrated local-wall coupon lowest parsed factor: `lambda = 4500908000.0000` on `coupon_coarse`.
- That raw CCX value implies an impossible critical stress of `1611673229728.4 MPa` versus the current knockdown/classical check of `2693.4 MPa`.
- Therefore the S4 shell eigenvalue is not accepted as local-wall truth in this run.
- Current usable buckling screen remains the internal estimate: local-wall buckling utilization reaches 1.0 at about `n = 12.396G`.
- A simpler knockdown/classical stress ratio gives `n = 15.044G`, which is less conservative than the internal estimate.
- Engineering conclusion: buckling is not the blocker through 3G, but candidate-specific CCX shell eigen-buckling is still numerically unresolved rather than validated.

## Limits Of This FEM

- This is candidate-specific for the main CFRP tube wall, but it is not a detailed root fitting, rib, bonded insert, lug, or wire-attach finite-element model.
- The shell tube uses a smeared ring load at the wire attach station. That is appropriate for tube-wall screening, but it intentionally avoids claiming local lug bearing strength.
- The local-wall coupon is stress-calibrated to the internal 2G compressive stress; it intentionally checks tube-wall stability rather than the full wing load path.
- The material is still the current effective isotropic CFRP tube material; final composite local buckling should eventually use laminate ABD/orthotropic shell properties and knockdowns.
- The run should therefore be called `candidate-specific CCX shell attempted, but local-wall eigenvalue unresolved`; the classical/internal estimate is still the accepted screening value.

- Reference 2G equivalent tip deflection used by the load-factor model: `1.543162 m`.
- Current effective tip deflection gate: `2.550000 m`.
