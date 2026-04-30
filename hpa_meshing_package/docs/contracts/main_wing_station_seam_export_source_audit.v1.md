# Main Wing Station-Seam Export Source Audit v1

`main_wing_station_seam_export_source_audit.v1` is a report-only diagnostic
gate for the real main-wing station-seam hotspot. It reads the station-seam
ShapeFix feasibility report, the OpenVSP section station topology fixture, the
generated OpenCSM `rebuild.csm`, and the topology lineage report beside the
selected normalized STEP. It does not run `serveCSM`, Gmsh, SU2, convergence
gates, or change production defaults.

The audit must record:

- source ShapeFix feasibility report path
- source station topology fixture path
- selected normalized STEP path
- generated `rebuild.csm` path
- topology lineage report path
- OpenCSM sketch / rule / dump / union summary
- target station mappings from defect station y-location to OpenCSM rule
  section, topology lineage section, candidate curve tags, and owner surfaces
- export strategy candidates, engineering findings, blockers, next actions,
  and limitations

Current status meanings:

- `single_rule_internal_station_export_source_confirmed`: the source ShapeFix
  report is unrecovered, the generated OpenCSM export uses one multi-section
  `rule` loft, and all target station defects map to internal rule sections.
- `export_source_audit_captured`: the export source and station mapping were
  captured, but the current evidence does not meet the stronger single-rule
  internal-station condition.
- `blocked`: required input artifacts are missing or invalid.

For the current main-wing route, the committed evidence is
`single_rule_internal_station_export_source_confirmed`: `rebuild.csm` contains
one `rule` over 11 sketch sections, and the suspect station curves 36 and 50
map to internal sections at `y=-10.5 m` and `y=13.5 m`.

This is evidence that the next geometry gate should prototype a station-seam
export strategy, such as station PCurve/export rebuild or a split-bay rule-loft
candidate, before spending more solver budget or promoting a Gmsh meshing
policy. Those candidates remain diagnostic proposals, not production defaults.
