# Chord Monotonicity Report

The Phase 7 sidecar planform has a small non-monotone chord region in the mid/outer wing. The same section schedule is used by Policy A and Policy C, so the geometric finding is identical for both.

- `policy_A_performance_candidate` `base_body_axis`: positive jumps `2`, max jump `0.025487 m`, jump sum `0.035729 m`, max abs second diff `0.183184 m`; violations `3->4:+0.010242;4->5:+0.025487`.
- `policy_A_performance_candidate` `monotone_chord_area_scaled_pava`: positive jumps `0`, max jump `0.000000 m`, jump sum `0.000000 m`, max abs second diff `0.182920 m`; violations `none`.
- `policy_C_conservative_baseline` `base_body_axis`: positive jumps `2`, max jump `0.025487 m`, jump sum `0.035729 m`, max abs second diff `0.183184 m`; violations `3->4:+0.010242;4->5:+0.025487`.
- `policy_C_conservative_baseline` `monotone_chord_area_scaled_pava`: positive jumps `0`, max jump `0.000000 m`, jump sum `0.000000 m`, max abs second diff `0.182920 m`; violations `none`.

## Engineering Read

The largest local bump is about 0.0255 m from eta 0.70 to 0.82, after a smaller 0.0102 m bump from eta 0.52 to 0.70. This is not huge aerodynamically, but it is visually real and worth smoothing before using the VSP model for drawing or manufacturing-facing review.
