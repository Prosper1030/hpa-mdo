# WO-006 SU2 Baseline Validation

Verdict: `su2_baseline_needs_fix`

This is bounded main-wing SU2 aero calibration evidence only. It is not release truth, not RFQ/procurement truth, not structural sign-off, and not final aircraft sign-off.

## Data Authority

- Design gross mass authority: `98.5 kg`.
- Current pipeline span authority: `34.332286 m` full span / `17.166143 m` half-span.
- Any sensitivity case must be labeled as sensitivity; this package does not replace the authority table.

## Geometry Basis

- Candidate: `current_avl_compromise_conservative_closed`.
- Geometry source: `sidecar_avl_loaded_shape`.
- Sref / Bref / Cref: `33.420059598` / `34.332286` / `1.003721543`.
- Loaded tip Z: `2.62856087` m.

## SU2 Status

- Current pathfinder SU2 status: `su2_unavailable_mesh_blocked`.
- No current-pathfinder SU2 CL/CD delta is usable because the mesh/SU2 handoff did not reach a solver case.

## Current Blockers

- `main_wing_real_geometry_mesh_handoff_timeout`
- `main_wing_real_geometry_mesh3d_volume_insertion_timeout`
- `main_wing_solver_not_run`
- `convergence_gate_not_run`
- `main_wing_real_geometry_mesh_handoff_blocked`
- `main_wing_real_geometry_boundary_parametrization_topology_failed`
- `main_wing_real_mesh_handoff_not_available`
- `main_wing_real_su2_handoff_not_materialized`

## Aero Deltas

- AVL loaded-shape reference remains the current screening aerodynamic model.
- Tier2/XFOIL profile drag remains the current profile-drag estimate.
- SU2 did not produce a current-pathfinder integrated CL/CD in this run, so CDi/profile split cannot be calibrated yet.
- Fourier-AVL tooling exists, but this checkout still lacks a promoted current Stage-0-to-pathfinder trace for WO-006 comparison.

## Reopen Risk

- Reopen trigger status: `not_evaluated`.
- Trigger band: `5-8%` drag/power delta.
- Reason: Current pathfinder SU2 is not usable for aerodynamic deltas.

## Engineering Caveats

- Mesh timeout or boundary topology failure is route evidence, not aerodynamic evidence.
- A passing Python test or generated report does not validate CFD convergence, aircraft performance, structure, C04, spar, rib, tail, or procurement.
- The current result should drive a bounded meshing/SU2 route repair before any drag or power conclusion.
