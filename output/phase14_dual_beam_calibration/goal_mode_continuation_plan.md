# Goal-Mode Continuation Plan

## Current Round Boundary

This report package is Round 1:

- inventory,
- evidence classification,
- benchmark ladder design,
- and risk framing.

No production model code was changed here.

## Common Guardrails For Future Rounds

### Allowed direction

- controlled benchmark export
- external beam-deck generation
- comparison tooling
- report-only calibration artifacts
- targeted regression tests for the new benchmark tooling

### Forbidden changes unless a later user goal explicitly widens scope

- no change to aerodynamic ranking
- no change to hard gates
- no broad aero optimization
- no calibration factor inserted into production code
- no modification of `dual_beam_production` equations as part of Round 2
- no promotion of `equivalent_beam` back into production truth
- no use of one old APDL case as the only final validation truth

### Mandatory engineering review checklist for every future round

- Are units consistent between internal and external models?
- Is the case half-span or full-span in both places?
- Is mass compared as tube-only or total structural mass?
- Is lift applied to the same beam line in both places?
- Is wire support represented the same way?
- Is pretension represented the same way?
- Is torque applied as `MY`, as a front/rear couple, or turned off?
- Are link modes actually the same topology?
- Is the compare route beam-only, or did shell/mesh artifacts leak in?
- Would the proposed fix change current ranking or gates?

## Round 2: Controlled Benchmark Export And External Compare

### Objective

Implement or reuse controlled export for Benchmarks 1 to 5, run external beam solves only when the solver route is actually available, and produce comparison artifacts without changing production structural equations.

### Allowed files

- New scripts under `scripts/` for benchmark export or compare plumbing
- New focused helpers under `src/hpa_mdo/structure/` only if they are export or report scaffolding, not physics changes
- New tests under `tests/` for benchmark export and compare contracts
- New artifacts under `output/phase14_dual_beam_calibration/`

### Strongly preferred read-only files unless a tiny helper extraction is unavoidable

- `src/hpa_mdo/structure/dual_beam_mainline/load_split.py`
- `src/hpa_mdo/structure/dual_beam_mainline/types.py`
- `src/hpa_mdo/structure/dual_beam_mainline/solver.py`
- `src/hpa_mdo/structure/dual_beam_mainline/optimizer_view.py`

### Forbidden changes

- no edits that alter `AnalysisModeName.DUAL_BEAM_PRODUCTION` ownership or equations
- no edits that alter optimizer gates or ranking
- no edits that reinterpret old parity reports as new truth

### Round 2 tasks

1. Freeze benchmark input specs for B1 to B5.
2. Build benchmark export plumbing that can emit internal metrics plus external decks.
3. Reuse ANSYS export where the existing contract is already clean.
4. Add a minimal external-beam compare path for CalculiX only if `ccx` is available and the case stays apples-to-apples.
5. Run comparisons and write:
   - `output/phase14_dual_beam_calibration/internal_vs_fem_comparison.csv`
   - `output/phase14_dual_beam_calibration/comparison_summary.md`
6. Stop before any production-physics edits.

### Candidate commands

```bash
./.venv/bin/python scripts/phase14_export_beam_benchmarks.py \
  --manifest output/phase14_dual_beam_calibration/benchmark_manifest.csv \
  --output-dir output/phase14_dual_beam_calibration/round2_benchmarks
```

```bash
./.venv/bin/python scripts/validate_benchmark_contract.py \
  --ai-json ... \
  --ccx-inp ... \
  --ccx-dat ... \
  --ccx-frd ...
```

```bash
./.venv/bin/python -m pytest \
  tests/test_ansys_export.py \
  tests/test_ansys_crossval.py \
  tests/test_dual_beam_mainline.py \
  tests/test_phase14_benchmark_export.py -q
```

### Expected artifacts

- frozen benchmark spec files
- exported ANSYS and or CalculiX beam decks
- per-benchmark internal metrics JSON
- `internal_vs_fem_comparison.csv`
- `comparison_summary.md`
- a short unresolved-issues note if any benchmark is blocked

### Stop conditions

- `ccx` is still unavailable and no approved installation path exists
- Benchmark 1 or Benchmark 2 fails by more than the planned tolerance band
- the production torque export contract is still ambiguous for Benchmark 5
- the implementation starts pressuring a change to production physics

### Commit boundaries

- One commit for benchmark export scaffolding
- One commit for benchmark contract tests
- One commit for comparison reports

Follow the repo rule: each independent task gets its own commit; do not merge export plumbing and report generation into one large undifferentiated commit.

## Round 3: Diagnosis, Report-Only Calibration Proposal, And Trust Policy

### Objective

Use the Round 2 comparison results to diagnose mismatches above tolerance, propose physically meaningful calibration factors or code fixes in report form only, and formalize what the team should and should not trust.

### Allowed files

- Analysis or compare scripts under `scripts/`
- New tests under `tests/`
- Report-only outputs under `output/phase14_dual_beam_calibration/`
- Documentation updates if the user later asks to align repo wording with the new trust policy

### Forbidden changes

- no production-equation edits without explicit authorization
- no silent gate changes
- no ranking changes
- no backdoor insertion of calibration multipliers into `dual_beam_production`

### Round 3 tasks

1. Diagnose each failed or warning benchmark by source category:
   - section and units
   - taper mapping
   - link topology
   - wire support
   - torque ownership
   - production-case replay
2. Write report-only:
   - `output/phase14_dual_beam_calibration/calibration_factors.yaml`
   - `output/phase14_dual_beam_calibration/final_trust_policy.md`
   - `output/phase14_dual_beam_calibration/diagnosis_matrix.md`
3. Add regression tests for any new export or comparison logic, or write a CI-safe test plan if full external execution cannot run in CI.
4. If the diagnosis points to a real production-physics bug, stop and ask for explicit authorization before touching production model equations.

### Candidate commands

```bash
./.venv/bin/python scripts/phase14_analyze_benchmark_deltas.py \
  --comparison-csv output/phase14_dual_beam_calibration/internal_vs_fem_comparison.csv \
  --output-dir output/phase14_dual_beam_calibration
```

```bash
./.venv/bin/python -m pytest \
  tests/test_phase14_benchmark_export.py \
  tests/test_phase14_benchmark_compare.py -q
```

### Expected artifacts

- `internal_vs_fem_comparison.csv`
- `comparison_summary.md`
- `diagnosis_matrix.md`
- `calibration_factors.yaml`
- `final_trust_policy.md`
- either real regression tests or a CI-safe execution plan

### Stop conditions

- a proposed calibration factor only compensates for a benchmark-contract mistake
- torque ownership is still ambiguous
- the only way to “pass” is to change current ranking or gate semantics
- the remaining mismatch is clearly shell-mesh-specific rather than beam-model-specific

### Commit boundaries

- One commit for diagnostic tooling
- One commit for regression tests or CI-safe test-plan artifacts
- One commit for final report-only trust policy and calibration proposal

## Recommended Go / No-Go Rule Before Any Later Physics Edit

Do not authorize a production-physics edit unless all of the following are true:

- Benchmarks 1 and 2 are clean.
- Benchmarks 3 and 4 are at least interpretable with no contract ambiguity.
- Benchmark 5 has an explicit torque-ownership decision.
- The proposed edit improves the right benchmark for the right reason.
- The team accepts the ranking and gate impact consciously rather than by accident.
