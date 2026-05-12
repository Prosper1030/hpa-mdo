# Baseline A Gate Debt Register

This register tracks docs/scripts/tests that encode stale assumptions or old constants.

| Item | Classification | Reason | Recommended action |
|---|---|---|---|
| `scripts/build_baseline_a_release.py` | `keep_current` | Reads P1 generated mass/CG closure but emits authority metadata, keeps the aggregate as suspect screening evidence, and unblocks only bounded WO-006. | Keep the checker in CI/manual verification before release wording changes. |
| `scripts/build_carbon_tube_rfq_pack.py` | `keep_current` | RFQ pack stays draft/vendor-screening and labels 16.5 m as local/splice screening only while WO-006 proceeds separately. | Do not restore procurement wording without station/span and vendor evidence. |
| `tests/test_baseline_a_release_builder.py` | `keep_current` | Now asserts authority classification instead of stale current truth. | Keep authority assertions when release-builder wording changes. |
| `tests/test_build_carbon_tube_rfq_pack.py` | `keep_current` | Now asserts draft/vendor-screening and release/procurement-only blocker language. | Keep draft-only assertions until procurement authority is restored. |
| `output/phase*` | `legacy_only` | Old output phases can contain useful evidence but are not current Baseline A authority. | Cite only as legacy_or_experiment unless CURRENT_MAINLINE explicitly promotes a specific artifact. |
| `tests/test_ansys_crossval.py:83` | `repair_needed` | Test references authority-sensitive value: tip_deflection_mm = _extract_metric_value(report_text, "Tip deflection (uz, y=16.5m)", "mm") | Label as legacy/screening fixture or replace with authority-class assertion. |
| `tests/test_ansys_crossval.py:97` | `repair_needed` | Test references authority-sensitive value: # APDL keypoints: 1..nn for the single equivalent FEM beam. | Label as legacy/screening fixture or replace with authority-class assertion. |
| `tests/test_ansys_crossval.py:106` | `repair_needed` | Test references authority-sensitive value: # APDL ASEC sections should map 1:1 to equivalent FEM elements. | Label as legacy/screening fixture or replace with authority-class assertion. |
| `tests/test_ansys_crossval.py:138` | `repair_needed` | Test references authority-sensitive value: # Equivalent material cards should match the back-computed internal FEM E/G. | Label as legacy/screening fixture or replace with authority-class assertion. |
| `tests/test_ansys_crossval.py:172` | `repair_needed` | Test references authority-sensitive value: """Sum of equivalent FK,*,FZ loads matches internal FEM nodal load total.""" | Label as legacy/screening fixture or replace with authority-class assertion. |
| `tests/test_ansys_dual_beam_production_check.py:24` | `repair_needed` | Test references authority-sensitive value: "Tip deflection (uz, y=16.5m)        2500.000 mm", | Label as legacy/screening fixture or replace with authority-class assertion. |
| `tests/test_ansys_export.py:230` | `repair_needed` | Test references authority-sensitive value: """Validation mode should use the same equivalent A/I/J as the internal FEM.""" | Label as legacy/screening fixture or replace with authority-class assertion. |
| `tests/test_avl_exporter.py:225` | `repair_needed` | Test references authority-sensitive value: VSPSection(0.0, 16.5, 0.81280, 0.435, 0.0, "clarkysm"), | Label as legacy/screening fixture or replace with authority-class assertion. |

Classification key:

- `keep_current`: safe current contract.
- `repair_needed`: must be fixed before release/WO-006/RFQ use.
- `legacy_only`: useful only as old evidence.
- `delete_candidate_later`: do not delete now; consider after migration.
- `needs_owner_decision`: requires user/project owner decision.
