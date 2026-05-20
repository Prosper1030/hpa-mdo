# HPA Mesh Strategy

Verdict: `strategy_defined_for_recent_openfoam_basis`

Use `recent_successful_openfoam_fullwing_mirror` as the CFD basis. Do not restart from the old
`rho=1.18/V=6.6` screening basis unless explicitly asked.

The next mesh-family generator fix must preserve one topology family and
scale local HPA physics zones. Uniformly increasing cells is not accepted.

## Local Zones

| zone | target spacing | growth | scaling | HPA reason |
|---|---|---|---|---|
| `leading_edge` | resolve LE curvature; keep chordwise LE spacing tied to n_perim | `<=1.20` | 4/3 linear then 5/4 linear | Low-speed high-CL suction peak and transition/separation sensitivity start at LE. |
| `upper_lower_wall_bl` | first layer 5e-5 m until y+ evidence supports a change | `<=1.20` | 4/3 linear then 5/4 linear | Wall-resolved HPA RANS needs y+ mostly below 1-2 on real wing walls. |
| `trailing_edge` | explicit finite-TE/wake C-grid stencil; no open-cell TE regression | `<=1.20` | 4/3 linear then 5/4 linear | Low-Re pressure recovery and wake drag are sensitive to TE stencil quality. |
| `near_wake` | streamwise wake cells begin at TE spacing and grow smoothly | `<=1.20` | 4/3 linear then 5/4 linear | Wake momentum thickness is part of drag sanity, not just forceCoeffs output. |
| `downstream_wake` | hold wake length at least 8 chords; refine wake sampling, not only body cells | `<=1.25` | 4/3 linear then 5/4 linear | Very low dynamic pressure makes small wake errors meaningful in power estimates. |
| `wing_tip_tip_vortex` | physical tip patch and vortex core refinement must remain physical, not symmetry-only | `<=1.20` | 4/3 linear then 5/4 linear | Tip vortex behavior is a major induced-drag and wake-structure check at high span. |
| `possible_low_re_separation_region` | extra upper-surface resolution from LE through aft suction recovery | `<=1.20` | 4/3 linear then 5/4 linear | At Re roughly 2.9e5-5.7e5, laminar bubble or transition location can dominate profile drag. |
| `farfield` | keep current farfield at 10 chords minimum unless domain study says otherwise | `<=1.30` | 4/3 linear then 5/4 linear | Small force coefficients are sensitive to blockage and artificial boundary effects. |

## Generator Fix Requirements

- Keep the successful full-wing mirror route as the starting point.
- Fix high-resolution TE stencil/open-cell regression before running Fine.
- Replace artificial tip-only convergence claims with physical tip-vortex diagnostics.
- Add explicit BL layer count and total-thickness metadata.
- Export Cp/Cf/wake/tip-vortex comparison surfaces for every grid.
