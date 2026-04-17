# ANSYS Equivalent-Beam Validation PASS

Date: 2026-04-10

## Current Status

This note is kept as **historical Phase I parity evidence**.

- It documents that the old `equivalent_beam` ANSYS parity gate passed against
  the internal equivalent-beam FEM assumptions.
- It does **not** mean `equivalent_beam` is still the current production
  structural truth.
- For current design judgement, producer workflows, jig validation, and future
  hi-fi comparison targets, prefer `dual_beam_production` and the newer
  dual-beam / jig artifacts.

## Scope

This document records the historical Phase I ANSYS validation result for the
internal structural solver. At that stage the official gate was the
**equivalent-beam validation mode**, because it compared ANSYS against the same
effective beam model assumptions used by the internal FEM and optimizer.

The internal MDO solver remains the optimization engine. ANSYS validation must
therefore compare the same equivalent section properties, support assumptions,
and nodal loads before higher-fidelity model-form differences are interpreted.

## Result

Equivalent-beam ANSYS validation passed all four Phase I gating metrics:

| Metric | Internal FEM | ANSYS | Error | Gate |
|--------|-------------:|------:|------:|------|
| Tip deflection | 2500.000 mm | 2483.328 mm | 0.67% | <= 5% |
| Max vertical displacement | 2500.000 mm | 2483.328 mm | 0.67% | <= 5% |
| Support reaction Fz, all constrained supports | 817.783 N | 817.783 N | ~0.00% | <= 1% |
| Spar beam mass, full-span | 9.454 kg | 9.470 kg | 0.17% | <= 1% |

Overall verdict: **PASS** for equivalent-beam Phase I validation.

## Stress Status

Stress comparison remains **provisional and non-gating**. The tested ANSYS RST
did not include ENS nodal stresses, and BEAM188 stress extraction has not yet
been proven apples-to-apples with the internal tube stress recovery.

Do not claim a Python stress bug or use stress as a Phase I gate until the
ANSYS beam/fiber stress extraction path is explicitly validated.

## Dual-Spar Interpretation

The existing `dual_spar` ANSYS export remains useful as a higher-fidelity
inspection model. Any discrepancy from that model is a **model-form
discrepancy**, not a Phase I validation failure.

Use dual-spar ANSYS spot checks to look for adequacy risks such as changed
active constraints, feasibility flips, rib/rear-spar load transfer dominance,
or design-ranking sensitivity. Do not promote dual-spar discrepancies to a
formal Phase I PASS/FAIL gate.

## Commands Used

Generate equivalent-beam validation package:

```bash
uv run python scripts/ansys_crossval.py --export-mode equivalent_beam
```

Compare manually-run ANSYS result:

```bash
uv run --with ansys-mapdl-reader python scripts/ansys_compare_results.py \
  --ansys-dir "/Volumes/Samsung SSD/SyncFile/ANSYS_Result" \
  --baseline-report "/Volumes/Samsung SSD/SyncFile/ANSYS_Result/crossval_report.txt" \
  --rst hpo.rst
```
