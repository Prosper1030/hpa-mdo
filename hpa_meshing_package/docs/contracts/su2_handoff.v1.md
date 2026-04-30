# su2_handoff.v1

`su2_handoff.v1` is the fixed contract for the package-native baseline SU2 route.

## Purpose

It packages:

- the input mesh handoff
- runtime configuration
- reference quantity provenance
- force-surface provenance
- case output paths
- parsed final history coefficients

## Required Fields

- `contract`
- `route_stage`
- `source_contract`
- `geometry_family`
- `units`
- `input_mesh_artifact`
- `mesh_markers`
- `reference_geometry`
- `runtime`
- `runtime_cfg_path`
- `case_output_paths`
- `history`
- `run_status`
- `solver_command`
- `force_surface_provenance`
- `provenance_gates`
- `convergence_gate`
- `provenance`

## Current Formal v1 Interpretation

- `source_contract` must be `mesh_handoff.v1`
- wall markers are resolved from the mesh handoff:
  - `aircraft` for the formal aircraft-assembly baseline
  - `main_wing`, `tail_wing`, `horizontal_tail`, or `vertical_tail` for single lifting-surface component routes when those markers are present in `mesh_handoff.v1`
  - `fairing_solid` for the closed-solid fairing route
- materializing the handoff writes `su2_handoff.json`, `mesh.su2`, and
  `su2_runtime.cfg`; solver execution is a separate step
- `run_status` becomes `completed` only after `SU2_CFD` finishes and `history.csv` is parsed
- `history` is the authoritative package-native baseline summary for final `CL`, `CD`, and `CM`
- `convergence_gate` is the authoritative machine-readable verdict for baseline comparability
- the canonical example artifact is `artifacts/su2/alpha_0_baseline/su2_handoff.json`

## Important Limitation

This contract represents a baseline CFD route. It is not, by itself, a claim that the mesh has passed convergence or that the result should be treated as final high-quality truth.
