# WO-006R1 GO/Baseline A CFD Bridge

Verdict: `wo006r1_go_cfd_bridge_smoke_ready`

## Plain-Language Blocker

WO-006 was blocked because the current pathfinder VSP3 materializes through `esp_rebuilt`, but the old Gmsh thin-sheet/STEP-BREP-like route does not get to a usable SU2 case. The default probe timed out during 3D volume insertion; the coarse probe hit boundary/topology failure. So there was no current Baseline A `mesh_handoff.v1` and no usable SU2 CL/CD.

## Route Decision

- Selected route: `mesh_native_current_go_section_table`.
- Rejected as primary: old VSP3 -> esp_rebuilt / STEP-BREP-like -> Gmsh route.
- Reason: current GO section-table geometry gives a controlled indexed wing surface with marker-owned wing/farfield faces; old Black Cat evidence is method evidence only.

## Authority Basis

- Design gross mass: `98.5 kg`.
- Span: `34.332286 m` full / `17.166143 m` half.
- Sref / Cref / Bref: `33.420059598` / `1.003721543` / `34.332286000`.
- Moment origin: `(0.246276512, 0.0, 0.0)` from current AVL source.
- `106.828608 kg` was classified as suspect P1 screening aggregate, not current design truth; `16.5 m` was classified as local/splice screening only. Neither was used.

## Result

- Mesh materialization status: `materialized`.
- Mesh volume elements: `2902`.
- Marker audit: `pass`.
- Mesh quality gate: `pass` with warnings `['very_low_min_gamma', 'low_p01_gamma']`.
- Solver smoke status: `completed`.
- Final smoke coefficients (readability only): `CL=0.2666424003`, `CD=-0.8452178079`.

## Engineering Caveats

- This is a coarse no-BL SU2 readability route, not validated aerodynamic drag.
- The solver smoke is not convergence and does not reopen Baseline A.
- Negative or unstable smoke coefficients are a warning that the case is not calibration evidence.
- Next CFD work should add near-wall/BL quality and y+ evidence before any drag/power claim.

## Artifacts

- `route_decision.json`
- `route_evidence_comparison.csv`
- `geometry_authority_reconciliation.csv`
- `mesh_handoff.v1.json`
- `su2_case_manifest.json`
- `su2_solver_smoke.v1.json`
- `blocker_register.csv`
- `next_repair_goal.md`

## Current Blockers

- `aero_calibration`: `coarse_no_bl_smoke_only` - mesh/SU2 readability does not provide wall-resolved drag or convergence
- `solver_smoke`: `coefficient_sanity_not_passed` - {"observed_cd": -0.8452178079, "reasons": ["negative_cd"], "status": "fail"}

Baseline A reopen status: `not_evaluated`.
