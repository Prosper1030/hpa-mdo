# Current Mesh Quality Audit

Verdict: `route_smoke_mesh_accepted_but_grid_family_not_validated`

The latest successful full-wing mirror route is the current audit baseline.
It is not a final grid-independent family.

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

## Real-Wall y+ Split

- `airfoil_upper` y+ mean / p90 / p95 / p99 / max: `0.5913392806089747` / `0.9731635000000001` / `1.1975625` / `1.7804425` / `2.65697`
- `airfoil_lower` y+ mean / p90 / p95 / p99 / max: `0.5443797898504277` / `0.673433` / `0.7880510000000001` / `1.90195` / `2.25937`
- `physical_tip_left` diagnostic y+ max is `1171.39`; this is not accepted as a physical tip-wall/tip-vortex sign-off.
- `physical_tip_right` diagnostic y+ max is `1171.42`; this is not accepted as a physical tip-wall/tip-vortex sign-off.

## Grid-Family Gate

- current grid-gate status: `grid_independence_not_demonstrated`
- blockers: `['coarse:solver_not_completed', 'medium:solver_not_completed', 'fine:checkMesh_not_solver_smoke_acceptable', 'fine:solver_not_completed']`
- max CD change seen so far: `50.73972140084425%`

The previous systematic ladder is useful because it proved the route still
breaks under refinement. It cannot be treated as a passed grid study.
