# convergence_gate.v1

`convergence_gate.v1` is the fixed machine-readable contract that says whether a completed package-native baseline CFD run is comparable enough for the next workflow step.

## Purpose

It answers three different questions without mixing them together:

- Is the mesh handoff complete enough to treat this as a real baseline mesh?
- Does `history.csv` show enough iterative stability to compare `CL / CD / CM`?
- After combining mesh, iterative, and provenance gates, should this run be treated as `preliminary_compare`, `run_only`, or `not_comparable`?

## Required Structure

- `contract`
- `mesh_gate`
- `iterative_gate`
- `overall_convergence_gate`

Each gate section carries at least:

- `status`
- `confidence`
- `checks`
- `warnings`
- `notes`

Each entry in `checks` is itself machine-readable and carries:

- `status`
- `observed`
- `expected`
- `warnings`
- `notes`

## Current Baseline Interpretation

### `mesh_gate`

The current baseline mesh gate checks:

- `mesh_handoff.v1` is complete and still marked `route_stage=baseline`
- mesh / metadata / marker-summary artifacts exist and are parseable
- `units`, `body_bounds`, and `farfield_bounds` are present and sane
- required wall / farfield / fluid groups exist
- node / element / volume-element counts are positive

### `iterative_gate`

The current baseline iterative gate reads `history.csv` directly and checks:

- the history file exists and is parseable
- iteration count is large enough for a tail window
- residual columns show a usable trend signal
- `CL / CD / CM` become stable over the final tail window

### `overall_convergence_gate`

This combines:

- `mesh_gate`
- `iterative_gate`
- reference provenance gate
- force-surface provenance gate

`comparability_level` maps the final status to downstream meaning:

- `preliminary_compare`
- `run_only`
- `not_comparable`

## Important Limitation

This contract does not claim final high-quality CFD truth. It is only the baseline comparability gate that must exist before mesh study, alpha sweep, or stronger credibility work can build on top of the package-native line.
