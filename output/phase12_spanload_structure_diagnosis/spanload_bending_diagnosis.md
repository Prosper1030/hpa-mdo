# Spanload And Bending Diagnosis

## Current AVL Spanload

- half lift: 501.6 N
- root bending proxy: 3545.0 N m
- outer lift fraction eta >= 0.7: 17.3%

Lift and root-bending contribution by region:
- eta_0p0_0p3: lift 39.5%, root-bending contribution 14.2%
- eta_0p3_0p6: lift 33.9%, root-bending contribution 36.6%
- eta_0p6_0p8: lift 16.9%, root-bending contribution 28.4%
- eta_0p8_1p0: lift 9.7%, root-bending contribution 20.8%

## Diagnosis

- The current AVL actual load is not obviously too outboard; it is already slightly inboard of an elliptical loading by the root-bending proxy.
- The requested loaded z(y) is a global beam-line scaling: at 6 deg the main beam is only about 0.263 m high by eta=0.3, 0.679 m by eta=0.6, and 1.149 m by eta=0.8. That asks the inner/mid wing to stay low while still carrying a long 34.3 m span.
- The 6 deg mass result is dominated by the inverse design trying to hold that low total loaded beam-line Z. It selects very thick 8 mm walls and leaves equivalent tip deflection near zero/negative rather than allowing elastic recovery.
- At 2.65-2.72 m target Z the same load path can use much lighter walls, but those states correspond to roughly 8.8-9.0 deg beam-line proxy.

## Variant Check At 6 Deg

- current spanload tube mass: 77.01360725359352 kg
- more-inboard synthetic spanload tube mass: 14.702920907067146 kg, but clearance is 0.0064767260931653525 m and still misses 11.5 kg
- Birdman-style outboard Z exponent variant tube mass: 77.01360725359352 kg

This means spanload changes are a real lever, but the low-Z stiffness/clearance contract remains the larger blocker in this canonical model.
