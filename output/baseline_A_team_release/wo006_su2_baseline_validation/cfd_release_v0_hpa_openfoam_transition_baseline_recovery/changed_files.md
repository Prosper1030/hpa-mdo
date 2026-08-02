# WO-006 Recovery Change Inventory

## Executable and tests

- `scripts/run_wo006_hpa_model_architecture_sensitivity.py`: serial lock,
  no-space external scratch gate, process-tree return status, restart-safe force
  parsing, 100-row/CmPitch/checkpoint qualification, attempt ledger, finite
  force guard, model-compatible SST-to-LM warm-start guard, and discovery of all
  existing cases for an unfiltered summary.
- `scripts/analyze_wo006_openfoam_transition_recovery.py`: compact force,
  residual/continuity, finite-field, yPlus, LM surface-intermittency, dictionary,
  mesh-hash and accepted-SA comparison evidence.
- `tests/test_wo006_hpa_model_architecture_sensitivity.py` and
  `tests/test_analyze_wo006_openfoam_transition_recovery.py`: 37 focused tests
  covering the above guards and analysis primitives.

## Mainline documents

- `README.md`
- `CURRENT_MAINLINE.md`
- `docs/work_orders/QUEUE.md`
- Architecture artifact `command_log.md`, summary CSV/JSON, and
  `model_architecture_sensitivity_verdict.md`.

`docs/AI_WORK_ORDER_PROTOCOL.md` is unchanged because this recovery did not
alter the program-wide work-order protocol; its changes are WO-006-specific.

## Compact committed evidence

At this directory root (LM r2):

- `recovery_report.md`, `primary_source_input_audit.md`, `command_log.md`,
  `recovery_attempt_ledger.jsonl`, `attempt_status.csv`, `verification.md`.
- `final_100_force_history.csv`, `force_gate.json`,
  `sa_fine_comparison.csv`, `solver_log_summary.json`.
- `checkpoint_field_ranges.csv`, `checkpoint_field_changes.csv`,
  `yplus_summary.csv`, `transition_surface_bins.csv`.
- `configuration_manifest.json`, `openfoam_dictionary_diff.patch`, and exact
  snapshots under `dictionary_snapshots/`.

Under `sst_fully_turbulent/`:

- The same force/gate/SA/log, field, yPlus, manifest, dictionary diff and
  snapshot set. LM-only surface-intermittency output is intentionally absent.

The large OpenFOAM cases, raw solver logs, full fields, APFS sparsebundle and
scratch data are not committed. The compact manifests preserve their hashes,
paths and relevant numerical summaries.

Pre-existing dirty Coarse campaign files and
`scripts/analyze_wo006_hpa_solver_campaign_repair.py` are unrelated and are
explicitly excluded from this task's staging.
