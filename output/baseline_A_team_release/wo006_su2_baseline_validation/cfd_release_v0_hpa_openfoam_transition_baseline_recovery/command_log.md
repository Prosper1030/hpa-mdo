# WO-006 Transition Recovery Command Log

This is the complete solver, case-mutation, postprocess and acceptance command
log for the 2026-08-02 recovery. Read-only source inspection is documented in
`primary_source_input_audit.md`. All OpenFOAM solves were serial; no
`pimpleFoam`, SU2, new mesh or design-power command was run.

## Startup and qualification

```bash
git status --short
git rev-parse HEAD
git branch --show-current
PYTHONPATH=src ./.venv/bin/python scripts/check_baseline_a_data_authority.py --check-only
./.venv/bin/pytest -q tests/test_wo006_hpa_model_architecture_sensitivity.py
python3 scripts/run_wo006_hpa_model_architecture_sensitivity.py --summarize-only
```

The first LM dry-run used the work-order scratch path literally and failed
before a solver was launched because OpenFOAM v2512 rejects a case path with a
space:

```bash
python3 scripts/run_wo006_hpa_model_architecture_sensitivity.py \
  --cases lm_Tu0p5_L0p001c_r2 --resume --iterations 50 \
  --np 1 --max-rss-gb 10 \
  --tmp-root "/Volumes/Samsung SSD/hpa-cfd-tmp/architecture_sensitivity"
```

The recovery then used a 64-GiB APFS sparsebundle physically backed on the
Samsung SSD and mounted at the no-space solver-visible path
`/Volumes/hpa-cfd-tmp`. `hdiutil info` records the backing image as
`/Volumes/Samsung SSD/hpa-cfd-tmp/architecture_sensitivity/hpa-cfd-tmp.sparsebundle`.
Before each actual solve, the runner's 20-GB free-space gate passed.

## Bounded solver attempts

Each line below was run separately. Attempts 1 and 5 were preflight-only and
did not advance simulation time. The two identical SST lines are distinct:
the first stopped at dry-run after the temporary duplicate-yPlus error; the
second is the corrected 2050-to-2100 solver chunk.

```bash
python3 scripts/run_wo006_hpa_model_architecture_sensitivity.py \
  --cases lm_Tu0p5_L0p001c_r2 --resume --iterations 50 --np 1 --max-rss-gb 10
python3 scripts/run_wo006_hpa_model_architecture_sensitivity.py \
  --cases lm_Tu0p5_L0p001c_r2 --resume --iterations 50 --np 1 --max-rss-gb 10
python3 scripts/run_wo006_hpa_model_architecture_sensitivity.py \
  --cases sst_Tu0p5_L0p001c --resume --iterations 50 --np 1 --max-rss-gb 10
python3 scripts/run_wo006_hpa_model_architecture_sensitivity.py \
  --cases sst_Tu0p5_L0p001c --resume --iterations 50 --np 1 --max-rss-gb 10
python3 scripts/run_wo006_hpa_model_architecture_sensitivity.py \
  --cases sst_Tu0p5_L0p001c --resume --iterations 50 --np 1 --max-rss-gb 10
```

Exact attempt outcomes, elapsed seconds, RSS, warning counts and stop decisions
are in `recovery_attempt_ledger.jsonl`. Actual solver time was 4960.224 s
(82.670 min). The campaign maximum process-tree RSS was 8,245,035,008 bytes,
below the 10,000,000,000-byte guard.

## Compact postprocess

```bash
./.venv/bin/python scripts/analyze_wo006_openfoam_transition_recovery.py \
  --case-dir output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0_hpa_model_architecture_sensitivity/openfoam_cases/lm_Tu0p5_L0p001c_r2 \
  --output-dir output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0_hpa_openfoam_transition_baseline_recovery \
  --case-name lm_Tu0p5_L0p001c_r2
./.venv/bin/python scripts/analyze_wo006_openfoam_transition_recovery.py \
  --case-dir output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0_hpa_model_architecture_sensitivity/openfoam_cases/sst_Tu0p5_L0p001c \
  --output-dir output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0_hpa_openfoam_transition_baseline_recovery/sst_fully_turbulent \
  --case-name sst_Tu0p5_L0p001c --skip-surface-bins
```

Final verification commands and their results are recorded in
`verification.md`.
