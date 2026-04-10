# Dual-Spar High-Fidelity Spot-Check Workflow

## Purpose

The `dual_spar` ANSYS model is a higher-fidelity inspection model with two
beam lines and rigid rib links. It is **not** the Phase I validation gate.

Use this workflow after the equivalent-beam validation has passed to judge
whether the internal equivalent-beam optimization model is adequate for design
decisions. The goal is to detect model-form risk, not to replace the official
gate.

## What To Look For

The spot check should answer these engineering questions:

- Did the active constraint change away from the internal model expectation?
- Did the design feasibility judgment flip?
- Did rear spar load transfer, rib-link forces, or torsion become dominant?
- Would nearby candidate designs change ranking under the higher-fidelity model?

## Generate A Dual-Spar Package

```bash
uv run python scripts/ansys_dual_spar_spotcheck.py export
```

Default output:

```text
output/blackcat_004_dual_spar_spotcheck/ansys/
  spar_model.mac
  spar_model.bdf
  spar_data.csv
  crossval_report.txt
```

This command runs the same production optimization path and exports the
resulting design in `dual_spar` mode. It does not run ANSYS.

To choose a different output root:

```bash
uv run python scripts/ansys_dual_spar_spotcheck.py export \
  --output-dir output/my_dual_spar_check
```

## Run ANSYS Manually

Run the generated `spar_model.mac` in ANSYS/MAPDL and keep the result files in
the same ANSYS output directory, or copy the generated `crossval_report.txt`
and `spar_model.mac` into the ANSYS result directory before comparing.

## Classify The Result

After ANSYS produces an RST file:

```bash
uv run --with ansys-mapdl-reader python scripts/ansys_dual_spar_spotcheck.py compare \
  --ansys-dir "/path/to/ANSYS_Result" \
  --baseline-report "/path/to/ANSYS_Result/crossval_report.txt" \
  --rst file.rst
```

If your RST is named `hpo.rst`, use:

```bash
uv run --with ansys-mapdl-reader python scripts/ansys_dual_spar_spotcheck.py compare \
  --ansys-dir "/Volumes/Samsung SSD/SyncFile/ANSYS_Result" \
  --baseline-report "/Volumes/Samsung SSD/SyncFile/ANSYS_Result/crossval_report.txt" \
  --rst hpo.rst
```

Optional report output:

```bash
uv run --with ansys-mapdl-reader python scripts/ansys_dual_spar_spotcheck.py compare \
  --ansys-dir "/path/to/ANSYS_Result" \
  --baseline-report "/path/to/ANSYS_Result/crossval_report.txt" \
  --rst file.rst \
  --output output/dual_spar_spotcheck_report.txt
```

## Classification

The workflow uses three non-gating labels:

| Label | Meaning |
|-------|---------|
| CONSISTENT | Higher-fidelity response is close enough for this spot check. |
| NOTICEABLE DISCREPANCY | Difference is large enough to document and sample further. |
| MODEL-FORM RISK | Difference may change active constraints, feasibility, or ranking. |

Current numeric bands used by the helper script:

| Metric | CONSISTENT | MODEL-FORM RISK |
|--------|------------|-----------------|
| Tip deflection | <= 5% | > 15% |
| Max vertical displacement | <= 5% | > 15% |
| Support reaction Fz, all supports | <= 1% | > 3% |
| Spar mass | <= 1% | > 3% |

Values between those bands are `NOTICEABLE DISCREPANCY`.

Stress remains provisional/non-gating unless ANSYS beam stress extraction has
been validated as apples-to-apples with the internal stress recovery.

## Interpretation Rules

- Do not call a dual-spar mismatch a Phase I validation failure.
- Do not change equivalent-beam gate thresholds based on this workflow.
- Treat `MODEL-FORM RISK` as a prompt for engineering investigation and
additional spot checks, not as an automatic solver refactor trigger.
- If multiple candidate designs are close in mass or constraint margin, run the
same dual-spar spot check on each design before trusting simplified-model
ranking.
