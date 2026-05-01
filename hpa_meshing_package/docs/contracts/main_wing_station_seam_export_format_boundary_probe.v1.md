# Main Wing Station-Seam Export Format Boundary Probe v1

`main_wing_station_seam_export_format_boundary_probe.v1` is a report-only
diagnostic for the side-aware main-wing station-seam route. It materializes the
same report-local side-aware CSM candidate through multiple OpenCSM `DUMP`
formats and compares the station-edge metadata gate across those exported files.

The probe must record:

- profile-parametrization audit path
- export-metadata source-audit path
- source `rebuild.csm`
- requested export formats
- materialization status for each format
- station-edge validation status for each format
- source evidence for OpenCSM / EGADS export-format support
- blockers, next actions, engineering findings, and limitations

Current status meanings:

- `export_format_boundary_all_formats_station_gate_valid`: all requested
  formats pass the station metadata gate.
- `export_format_boundary_step_loss_suspected`: STEP fails but a non-STEP
  format passes the same comparable station metadata gate.
- `export_format_boundary_step_suspect_non_step_validation_unavailable`: STEP is
  suspect, but the current non-STEP validation path is not comparable yet.
- `export_format_boundary_partial_recovery`: at least one requested format passes
  but the pattern is not a clean STEP-loss classification.
- `export_format_boundary_rule_loft_metadata_suspect`: all comparable imported
  formats fail the station metadata gate.
- `export_format_boundary_materialization_failed`: no requested format
  materialized.
- `export_format_boundary_validation_unavailable`: materialization happened but
  no station metadata validation could be interpreted.
- `export_format_boundary_source_only_ready_for_materialization`: CSM candidates
  are buildable but materialization was not requested.
- `blocked`: required input artifacts are missing or invalid.

This probe must not promote any export format into production defaults. A
materialized STEP, BREP, or EGADS candidate is still not mesh-ready or CFD-ready
until station metadata, mesh handoff, marker ownership, SU2 handoff, solver,
lift acceptance, and convergence gates pass. In the HPA main-wing route, CL
acceptance at `V=6.5 m/s` still requires `CL > 1.0`; short solver execution is
not convergence.
