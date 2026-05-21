# HPA Mesh Strategy

Verdict: `strategy_defined_for_recent_openfoam_basis`

Use `recent_successful_openfoam_fullwing_mirror` as the CFD basis. Do not restart from the old
`rho=1.18/V=6.6` screening basis unless explicitly asked.

The mesh-family generator now preserves one topology family and scales local
HPA physics zones. Uniformly increasing cells is not accepted. The current
state is strict `checkMesh -meshQuality` clean across the generated
Coarse/Medium/Fine family. The remaining verification work is solver-complete
force stability plus Cp/Cf/wake/tip-vortex comparison, not another one-off fix
of the old open-cell or wrong-oriented-face bug.

## Local Zones

| zone | target spacing | growth | scaling | HPA reason |
|---|---|---|---|---|
| `leading_edge` | resolve LE curvature; keep chordwise LE spacing tied to n_perim | `<=1.20` | 4/3 linear then 5/4 linear | Low-speed high-CL suction peak and transition/separation sensitivity start at LE. |
| `boundary_layer` | first layer 7e-5 m; y+ probe remains wall-resolved on real upper/lower walls | `<=1.20` | 4/3 linear then 5/4 linear | Wall-resolved HPA RANS needs y+ mostly below 1-2 on real wing walls without over-compressing LE wall cells. |
| `trailing_edge` | explicit finite-TE/wake C-grid stencil; no open-cell TE regression | `<=1.20` | 4/3 linear then 5/4 linear | Low-Re pressure recovery and wake drag are sensitive to TE stencil quality. |
| `near_wake` | streamwise wake cells begin at TE spacing and grow smoothly | `<=1.20` | 4/3 linear then 5/4 linear | Wake momentum thickness is part of drag sanity, not just forceCoeffs output. |
| `downstream_wake` | hold wake length at least 8 chords; refine wake sampling, not only body cells | `<=1.25` | 4/3 linear then 5/4 linear | Very low dynamic pressure makes small wake errors meaningful in power estimates. |
| `wing_tip_vortex_region` | physical tip patch and vortex core refinement must remain physical, not symmetry-only | `<=1.20` | 4/3 linear then 5/4 linear | Tip vortex behavior is a major induced-drag and wake-structure check at high span. |
| `farfield` | keep current farfield at 10 chords minimum unless domain study says otherwise | `<=1.30` | 4/3 linear then 5/4 linear | Small force coefficients are sensitive to blockage and artificial boundary effects. |

## Generator Fix Requirements

- Keep the successful full-wing mirror route as the starting point.
- Preserve the lower-TE radial rebalance that keeps wrong-oriented face pyramids at zero.
- Keep the HPA wall-resolved meshQuality policy (`minDeterminant=1e-8`, `minTwist=0`) tied to explicit y+ evidence and zero high-aspect failures.
- Keep TE gap cross-wake cells bounded and identical across the C/M/F family.
- Replace artificial tip-only convergence claims with physical tip-vortex diagnostics.
- Keep explicit BL layer count and total-thickness metadata in each rung manifest.
- Export Cp/Cf/wake/tip-vortex comparison surfaces for every grid.
