# Phase 9 Recommendation

Generated: 2026-05-07T03:47:01.466177Z

## Direct Answers

1. The current faceted chord is acceptable as optimizer/AVL evidence, but it is not the geometry I would hand to SolidWorks as the production-facing baseline.
2. A smooth monotone planform is recommended for production-facing VSP/SolidWorks/final drawing work.
3. The raw Tier2 smooth penalty is 13.497 W crank in this sidecar lookup.
4. Smoothing improves CAD/loft quality, but it does not materially solve jig or spar feasibility because span, loaded z, twist, and spanload family are nearly unchanged.
5. Current production-facing baseline: Tier2 conservative best, smooth_monotone. It keeps clean airfoil evidence and avoids selling a 166 W aero-only result as a finished structure.
6. The raw 166 W candidate is aerodynamically attractive but not structurally proven as-is. Treat it as needing the current spar/wire mass allowance, not as a lower-mass production answer.
7. Future optimizer handling: use chord smoothness as a soft penalty plus post-processing regularizer. Do not make it a hard gate until the penalty is calibrated against real CAD/loft constraints.

## Engineering Notes

- Raw smooth quality score: 85.4; conservative smooth quality score: 85.4.
- Raw smooth jig flags: negative_unloaded_jig_tip_estimate. Conservative smooth jig flags: negative_unloaded_jig_tip_estimate|above_preferred_deflection_band_proxy.
- Lightest passing catalog tube proxy: CF-HM-90x88 at 30.487 kg full span.

The structural rows are deliberately labeled `not_structure_grade`: they are AVL spanload plus beam/tube proxies, useful for rejecting fantasy-level conclusions, not for releasing a layup.
