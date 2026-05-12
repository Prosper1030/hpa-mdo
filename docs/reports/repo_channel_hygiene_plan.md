# Repo Channel Hygiene Plan

Baseline A data authority is restored only for bounded WO-006 aero calibration. Future AI agents must not treat arbitrary generated outputs as current truth.

## Allowed Truth Sources

- Latest explicit user instruction.
- `CURRENT_MAINLINE.md`, after it names an authority table or current manifest.
- `README.md` only as an entry point, not as a replacement for the authority table.
- `output/baseline_A_team_release/data_authority_table.csv` and `.json` for the known contested numbers.
- Current pipeline geometry manifests only when they are cited by the authority table or current mainline.

## Evidence Only

- `output/baseline_A_team_release/` generated reports and CSV/JSON files.
- `output/current_pathfinder*/` generated pathfinder reports.
- `output/go_mode_main_wing_candidate/final_candidate_package/` candidate artifacts.
- `docs/reports/*` reports, unless `CURRENT_MAINLINE.md` promotes a specific report as current authority.

## Legacy / Experiment Only

- `output/phase*` folders unless the current mainline explicitly promotes a specific artifact.
- Old medium-search, one-off design-space, or manually edited generated output.
- External manuals, papers, and vendor references: useful background, not Baseline A authority.

## Generated Outputs That Must Not Be Promoted Without Authority Table Entry

- P1 mass-closure aggregate `106.828608 kg`.
- Local/splice screening half-span `16.5 m`.
- Stage-0 `-9 W` power warning.
- Coupon/FEM readiness or analytical margin pass language.
- RFQ/vendor screening artifacts.

## Safe Citation Pattern For Old Outputs

Use this shape: `old/path/file.ext reports X as legacy_or_experiment evidence for Y; it is not current Baseline A authority because Z.`

## WO-005 / WO-006 Rule

- WO-005 remains draft/vendor-screening only; RFQ/procurement remains blocked.
- WO-006 SU2 may proceed only as bounded aero calibration using 98.5 kg and current pipeline span authority unless explicitly labeled sensitivity.
- WO-006 output is not release truth, not RFQ/procurement truth, and not final aircraft sign-off.
- QPROP/XROTOR must remain a propulsion lane and cannot pass C04/rib/structural blockers.

## Recorded Skips

The scan recorded skipped paths in `data_authority_claim_inventory.json`; common reasons are binary files, cache/vendor/venv/git internals, or files over the safe text-scan limit.
