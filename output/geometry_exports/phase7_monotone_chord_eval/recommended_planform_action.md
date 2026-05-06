# Recommended planform action

## Answers
1. Is the original chord bump small enough to accept? Yes for aerodynamic screening and historical traceability. The max positive jump is only about 0.0255 m, so it is not an induced-drag emergency.
2. Does enforcing monotone chord significantly reduce e_CDi? No. The AVL e_CDi change is negligible and slightly favorable for the monotone variants in this check.
3. Does monotone chord increase profile drag or local Cl risk? No meaningful increase was found. Profile Cd and max local Cl shift only at diagnostic-noise scale for both Policy A and Policy C.
4. Should production geometry use monotone chord? Yes, use the monotone-chord geometry for production-facing CAD/VSP review if the current area/span/twist/loaded-z preservation is maintained. It is cleaner for manufacturing and manual inspection with no material aero penalty in this test.
5. Should future optimizer add chord monotonicity as a hard gate or soft penalty? Use a soft penalty or post-processing regularizer first. Do not add a hard gate yet; the current bump is not severe enough to justify excluding otherwise good aerodynamic candidates.

## Recommended next step
Adopt monotone-chord export as the presentation/production geometry normalization for Policy A/C while keeping original optimizer outputs archived. Before any ranking or gate change, run one combined AVL + VSPAERO + structural packaging smoke on the monotone Policy C conservative baseline and Policy A performance candidate.
