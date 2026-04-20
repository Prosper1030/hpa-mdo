# Origin VSP Aero Sweep and SU2 Integration Attempt Design

**Goal**

Add a formal, repo-owned aerodynamic analysis entrypoint for the reference
`origin.vsp3` that quickly produces a reusable VSPAero result bundle, while in
the same round proving how SU2 alpha-sweep results can plug into the same
analysis/report path.

**What This Round Must Deliver**

- A formal CLI for `origin.vsp3 -> VSPAero`
- Stable output artifacts for:
  - `alpha`
  - `CL`
  - `CD`
  - `CM`
  - `Lift`
  - `Drag`
- Plot/report artifacts that are easy to inspect and compare
- A first-pass SU2 integration path that can read alpha-sweep results into the
  same bundle
- A concrete smoke artifact showing how SU2 data enters the analysis contract

**What This Round Does Not Need To Fully Solve**

- Full production-grade SU2 backend ownership for all workflows
- Automatic 3D CFD meshing for arbitrary HPA geometries
- Finalized SU2 marker/mesh generation for every downstream use case
- Replacing the existing structural high-fidelity route

## User-Facing Shape Of The Feature

The primary interface should be a single CLI that starts from the repo-owned
reference aircraft geometry and writes a compact analysis bundle.

Recommended command shape:

```bash
python scripts/origin_aero_sweep.py \
  --config configs/blackcat_004.yaml \
  --alpha-start -2 \
  --alpha-end 8 \
  --alpha-step 2 \
  --output-dir output/origin_aero_sweep
```

The same CLI should optionally accept SU2 sweep inputs that were produced by a
manual or semi-manual CFD run:

```bash
python scripts/origin_aero_sweep.py \
  --config configs/blackcat_004.yaml \
  --read-su2-dir output/origin_aero_sweep/su2_alpha_sweep \
  --output-dir output/origin_aero_sweep
```

## Output Contract

The CLI should write a single analysis folder containing:

- `vspaero_results.csv`
- `vspaero_results.json`
- `vspaero_results.md`
- `vspaero_plots.png`
- `analysis_bundle.json`

If SU2 results are provided/read successfully, the folder should also contain:

- `su2_results.csv`
- `su2_results.json`
- `su2_results.md`
- `comparison_plots.png`
- SU2-related section merged into `analysis_bundle.json`

## Data Model

The implementation should normalize both solvers into the same table shape.

Minimum normalized columns:

- `solver`
- `alpha_deg`
- `cl`
- `cd`
- `cm`
- `lift_n`
- `drag_n`
- `source_path`
- `notes`

For VSPAero:

- `alpha_deg` comes from `.history` / `.lod`
- `cl`, `cd`, `cm` should use whole-aircraft coefficient output
- `lift_n`, `drag_n` should be dimensionalized using the current config flight
  condition and reference area

For SU2:

- `alpha_deg` comes from per-case metadata or directory/config naming
- `cl`, `cd`, `cm` should come from SU2 history columns
- `lift_n`, `drag_n` should be dimensionalized from coefficients using the same
  flight condition/reference values used in the report

## Architecture

### 1. VSPAero formalization layer

Use the existing `VSPBuilder.run_vspaero()` path to execute VSPAero from the
reference `.vsp3`. Reuse `VSPAeroParser` for strip-load parsing, but add a new
history/polar-oriented summary path for whole-aircraft coefficient extraction.

### 2. Shared aero result normalization layer

Introduce a small, focused module that converts solver-specific outputs into one
shared result schema. This keeps the CLI thin and makes SU2 integration easier.

### 3. SU2 integration-attempt layer

Do not build a full general-purpose SU2 backend yet. Instead:

- define how an SU2 alpha sweep is laid out on disk
- reuse fairing-project style history parsing ideas
- read one or more SU2 case folders into the shared aero result schema
- prove that VSPAero and SU2 can land in the same analysis bundle

## SU2 Integration Attempt Scope

This round should support at least one clear convention for SU2 alpha sweep
results, for example:

- one case directory per alpha
- each case has:
  - `su2_case.cfg` or `su2_runtime.cfg`
  - `history.csv` or `history.dat`
  - optional metadata file describing `alpha_deg`

The code should be able to:

- discover candidate SU2 case directories
- locate history files
- read coefficient columns robustly
- recover `alpha_deg`
- produce normalized rows for comparison/reporting

If a real SU2 case is available, the round should try a real smoke. If not, the
implementation must still leave behind a valid reader path and test fixtures
that lock the contract down.

## Testing Strategy

### Must-have tests

- VSPAero result normalization from real or fixture output
- CLI output bundle creation
- SU2 history parsing for uppercase / mixed column variants
- SU2 directory discovery and alpha extraction
- Combined bundle generation with both solver families present

### Smoke verification

- real VSPAero smoke against `data/blackcat_004_origin.vsp3`
- first-pass SU2 integration smoke using either:
  - a real SU2 case if available, or
  - a realistic fixture that matches the expected directory contract

## Risks and Boundaries

- Whole-aircraft coefficient ownership and wing-only strip-load ownership should
  not be mixed silently. Reports must say what came from which file/path.
- SU2 alpha recovery may be ambiguous if the case directory naming contract is
  loose. The implementation should require or derive a single explicit rule.
- The first round should optimize for traceability and inspectability rather
  than maximum automation.
