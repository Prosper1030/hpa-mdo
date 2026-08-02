# WO-006 Recovery Verification

Verification date: 2026-08-02 Asia/Taipei.

## Automated checks

```text
focused pytest: 37 passed
ruff: All checks passed
git diff --check: passed
Baseline A data-authority checker: passed
runner --summarize-only: passed; seven existing cases retained
```

Focused command:

```bash
./.venv/bin/pytest -q \
  tests/test_wo006_hpa_model_architecture_sensitivity.py \
  tests/test_analyze_wo006_openfoam_transition_recovery.py
```

The final unfiltered summary includes `lm_Tu0p5_L0p001c_r2` and
`sst_Tu0p5_L0p001c`, both at time 2100 with 100 rows and explicit
`force-window-unstable` status.

## Artifact integrity

- Each final force CSV has 101 lines: one header plus exactly 100 data rows.
- Both final windows are finite, unique, contiguous 2001-to-2100 and aligned
  with checkpoint 2100; both formal force gates are false.
- Both configuration manifests compute `same_mesh=true` by matching all five
  Fine `polyMesh` SHA-256 values, rather than by assertion.
- Every required saved volume field is finite and has exactly 6,090,240
  internal values.
- Both upper/lower yPlus patches have the expected 37,440 faces, finite values,
  max below 5 and zero faces above 20.
- LM surface evidence has 200 data rows plus header; no wall-owner bin has
  `gammaInt max>0.9`.
- Both solver-log summaries report normal process termination and finite logged
  residual/continuity numbers while separately preserving all bounding and LM
  correlation warning counts.
- `recovery_attempt_ledger.jsonl` has six valid JSON records; the CSV view has
  six data rows plus header.
- Candidate dictionary diff labels are lane-specific; SST is not mislabeled as
  LM. SST manifest marks LM-only `gammaInt/ReThetat` inputs not applicable.
- No `simpleFoam`, `pimpleFoam`, SU2 or WO-006 controller process remained after
  copy-back. Solver-visible scratch was empty and mounted from the Samsung-SSD
  sparsebundle.

## Engineering review gate

Operational checks passing does not qualify the aerodynamics. The formal force
gate is false in both lanes, turbulence fields continue to grow, and model
warnings accumulate. The only defensible enum verdict is
`transition_route_not_established`; no coefficient or power update follows.
