# Main Wing Station-Seam Export Metadata Source Audit v1

`main_wing_station_seam_export_metadata_source_audit.v1` is a report-only
source-boundary audit for the side-aware main-wing station-seam route. It reads
the hpa-mdo CSM writers, the current opcode-variant negative-control report,
and an optional local OpenCSM / EGADS source tree inventory.

The audit must record:

- opcode-variant probe path
- source files inspected
- hpa-mdo controls versus external OpenCSM / EGADS / OCCT controls
- source evidence for CSM script generation and post-export repair probes
- current negative-control summary
- external source inventory
- engineering findings, blockers, next actions, and limitations

Current status meanings:

- `export_metadata_generation_source_boundary_captured`: hpa-mdo CSM-script
  ownership and external metadata-generation ownership are separated clearly.
- `export_metadata_generation_source_boundary_incomplete`: source evidence is
  present but the boundary is not complete enough for the next probe.
- `blocked`: required input artifacts or source files are missing.

For the current main-wing route, hpa-mdo owns section coordinates, sketch opcode
policy, rule grouping, and the `DUMP !export_path 0 1` invocation. The export
metadata itself is not owned in the CSM writers: rule-loft PCurves, STEP export
metadata, and post-import ShapeAnalysis truth live in OpenCSM / EGADS / OCCT.

The next engineering gate is a format-boundary probe: materialize the same
side-aware candidate through STEP, BREP, and EGADS exports and run the same
station-edge metadata gate after each import. This separates metadata born bad
inside the rule loft from metadata lost across STEP serialization. This audit
does not run Gmsh, SU2, convergence, or CL acceptance.
