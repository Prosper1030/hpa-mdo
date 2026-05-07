# Recommended Optimizer Constraints

## Recommended Policy

- Add a chord smoothness soft penalty based on max slope change and integrated curvature.
- Keep a post-processing smooth monotone regularizer that preserves span, area, root/tip chord, MAC, loaded z, relative twist, and airfoil zones.
- Do not turn chord smoothness into a hard gate yet; it can reject aerodynamically good candidates before CAD tolerance is quantified.
- Add a warning gate, not a rejection gate, when the unloaded jig-tip estimate goes negative under the not_structure_grade beam proxy.
- Keep production ranking and hard gates unchanged until a real structural sizing rerun is connected to the smoothed planform.

## Suggested Numeric Starters

- area error after smoothing: <= 0.5%
- MAC error after smoothing: prefer <= 1.5%, warn above 2.0%
- positive chord jumps: 0
- near-constant chord plateaus: soft penalty after 1 segment
- max slope change: minimize as soft objective; do not gate before CAD review
