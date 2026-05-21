# Current Mesh Quality Audit

Verdict: `route_smoke_accepted_and_grid_family_strict_checkmesh_clean`

The latest successful full-wing mirror route is the current audit baseline.
It is not a final grid-independent family. The current generated
Coarse/Medium/Fine family now passes strict checkMesh, and the coarse
potential-initialized solver probe gives the first same-family y+ evidence.

## Accepted Route-Smoke Mesh

- cell count: `1996800`
- combined y+ mean / p90 / p95 / p99 / max on real airfoil walls: `0.5678595352296987` / `0.8781874000000001` / `1.0904245` / `1.8354890999999969` / `2.65697`
- first layer height: `5e-5 m` from the current swept C-grid generator
- BL layer count: represented by the `n_radial=64` near-wall C-grid stack; current generator still needs explicit BL-layer-count metadata for final Phase 1 closure
- BL total thickness: not yet reported as an explicit scalar; must be added before final Phase 1 closure
- wall-normal growth rate: current generator default is `1.12`, within the preferred `<=1.2` target
- surface spacing near LE/TE: tied to the `n_perim=192` C-grid, but exact LE/TE spacing scalars are not yet exported
- wake resolution: current topology has an `8 chord` wake length; explicit wake sampling and profile comparisons are still missing
- tip vortex resolution: side patches exist, but physical tip-vortex core diagnostics are still missing
- farfield distance: current C-grid uses `10 chords`; final workflow still needs a domain-effect check if forces remain sensitive
- max non-orthogonality: `89.193`
- max skew: `3.45663`
- strict checkMesh failed checks: `2`

This accepted route-smoke mesh is retained as operating-condition and y+
context only. It is not the formal final C/M/F family.

## Real-Wall y+ Split

- `airfoil_upper` y+ mean / p90 / p95 / p99 / max: `0.5913392806089747` / `0.9731635000000001` / `1.1975625` / `1.7804425` / `2.65697`
- `airfoil_lower` y+ mean / p90 / p95 / p99 / max: `0.5443797898504277` / `0.673433` / `0.7880510000000001` / `1.90195` / `2.25937`
- `physical_tip_left` diagnostic y+ max is `1171.39`; this is not accepted as a physical tip-wall/tip-vortex sign-off.
- `physical_tip_right` diagnostic y+ max is `1171.42`; this is not accepted as a physical tip-wall/tip-vortex sign-off.

## Grid-Family Gate

- current grid-gate status: `grid_independence_not_demonstrated`
- mesh family: coarse `1,335,552`, medium `3,136,000`, fine `6,090,240` full-wing cells
- checkMesh: all three current rungs pass strict `checkMesh -meshQuality` with open cells `0`, negative volumes `0`, wrong-oriented face pyramids `0`, and failed checks `0`
- first layer height: `7e-5 m`
- wall-normal growth rate: `1.12`
- coarse same-family y+ on real upper/lower walls: mean `0.545112`, p95 `1.34603`, max `3.01407`
- force history status: coarse 160-iteration probe completes but is not stable over the final 50 iterations; Medium/Fine histories are not complete
- max CD change seen so far: `None%`

The new systematic ladder proves the generator/checkMesh part is no longer the
limiting issue. It cannot be treated as a passed grid study until Medium/Fine
solver histories, y+, Cp, Cf, wake, and tip-vortex comparisons are complete.
