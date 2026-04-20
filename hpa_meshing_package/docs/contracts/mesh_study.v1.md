# mesh_study.v1

`mesh_study.v1` is the fixed machine-readable contract for the package-native baseline mesh study.

## Purpose

It aggregates several package-native baseline runs for the same geometry so the package can answer a narrower question than final validation:

- did coarse / medium / fine style presets really form a sensible mesh ladder?
- did the resulting `CL / CD / CM` spread start to tighten, especially from medium to fine?
- did the convergence verdict improve enough to promote the baseline from `run_only` toward `preliminary_compare`?

## Required Structure

- `contract`
- `study_name`
- `component`
- `geometry`
- `geometry_provider`
- `cases`
- `comparison`
- `verdict`

## Each Case Carries

- the resolved preset (`near_body_size`, `farfield_size`, runtime budget)
- mesh stats (`node_count`, `element_count`, `volume_element_count`)
- baseline CFD result (`CL`, `CD`, `CM`)
- the per-case `convergence_gate.v1` verdict
- paths back to the case-level `report.json`

## Comparison Section

`comparison` is machine-readable and currently reports at least:

- expected vs completed case count
- mesh hierarchy check across coarse / medium / fine
- coefficient spread checks for `all_cases` and `medium_fine`
- convergence progress check focused on whether the finer baseline actually improved

## Verdict Semantics

`verdict.verdict` currently uses:

- `insufficient`
- `still_run_only`
- `preliminary_compare`

`verdict.comparability_level` maps the study back to the downstream gate language:

- `not_comparable`
- `run_only`
- `preliminary_compare`

## Current Minimal v1 Interpretation

- the default package study uses three presets: `coarse`, `medium`, and `fine`
- presets are resolved from a geometry-derived body-span characteristic length, not case-name hacks
- each preset still runs the normal package-native line:
  - provider
  - meshing
  - `mesh_handoff.v1`
  - SU2 baseline
  - `su2_handoff.v1`
  - `convergence_gate.v1`

## Important Limitation

`mesh_study.v1` is still a baseline hardening artifact. It is not an alpha sweep, not component-level force mapping, and not a final high-confidence CFD validation claim.
