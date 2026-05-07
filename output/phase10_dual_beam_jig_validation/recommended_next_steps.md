# Recommended Next Steps

## Structural Verdict

The real dual-beam model ran, but the smooth aerodynamic baseline is **not yet structurally cleared**. The results are adapter-grade because the smooth aero package still lacks a candidate-owned structural layout, spar recipe, wire pretension definition, and validated load/torque mapping.

The most important next action is to make the structural recipe candidate-owned instead of adapter-assumed:

1. Add a smooth-baseline structural config/manifest with main/rear spar locations, tube/layup recipe, material keys, joint stations, wire anchor geometry, and pretension.
2. Reuse the real builder path where possible instead of directly constructing `DualBeamMainlineModel`.
3. Map AVL lift and airfoil/AVL moment into a reviewed torque-per-span convention, then close the current `moment_closure` diagnostic.
4. Run `dual_beam_production` plus inverse-jig recovery as a required sidecar report, but keep it outside aerodynamic ranking until reviewed.
5. Replace the Phase 9 scalar proxy in final validation reports with this sidecar once the inputs are no longer assumptions.

## Engineering Caution

If the equal `CF-STD-100x98` recipe looks much better in deflection than the Phase 9 proxy, that does not mean the old proxy was simply pessimistic. It used a scalar equivalent EI target, while this run uses explicit main/rear beams, a real truss wire, torque input, and a different stiffness distribution. The mass comparison is only direct for the equal-tube recipe; other recipes are not comparable to the `32.959 kg` proxy number.
