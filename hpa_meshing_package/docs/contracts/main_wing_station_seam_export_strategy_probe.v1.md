# Main Wing Station-Seam Export Strategy Probe v1

`main_wing_station_seam_export_strategy_probe.v1` is a report-only strategy
probe for the real main-wing station-seam blocker. It consumes the export-source
audit, parses the generated OpenCSM `rebuild.csm`, creates bounded candidate
export sources under the report directory, and can materialize those candidates
with `serveCSM` / `ocsm`. It does not change `esp_rebuilt`, Gmsh routes, SU2
handoff, convergence gates, or production defaults.

The probe must record:

- source export-source audit path
- source `rebuild.csm` path
- target OpenCSM rule-section indices
- candidate rule groups and whether `UNION` is applied
- whether target station sections become rule boundaries
- whether target station sections are duplicated across split rules
- candidate materialization status, candidate CSM/STEP/log paths, and topology
  counts when materialization is requested
- span-bounds preservation against the source station y-range
- engineering findings, blockers, next actions, and limitations

Current status meanings:

- `export_strategy_candidate_materialized_needs_brep_validation`: at least one
  materialized candidate moves target stations to rule boundaries, preserves the
  full station y-range, and imports as one body / one volume. This still is not
  CFD-ready; it needs BRep, mesh handoff, marker, solver, and convergence gates.
- `export_strategy_candidate_materialized_but_topology_risk`: candidates
  materialized, but the topology is not acceptable for promotion.
- `export_strategy_candidate_materialization_failed`: materialization was
  requested, but no candidate produced a STEP.
- `export_strategy_candidate_source_only_ready_for_materialization`: source
  candidates were generated/evaluated, but materialization was not requested.
- `blocked`: required input artifacts are missing or invalid.

For the current main-wing route, the committed evidence is
`export_strategy_candidate_materialized_but_topology_risk`: splitting at rule
sections 2 and 9 moves the defect stations to rule boundaries, but the no-union
candidate materializes as three volumes, while the union candidate materializes
as one volume that does not preserve the full `y=-16.5..16.5 m` station bounds.

The follow-up internal-cap probe confirms this is evidence against promoting a
split-bay OpenCSM export default as the main-wing repair. The no-union
candidate keeps duplicate station cap faces and multiple volumes; the union
candidate truncates the right span and leaves cap fragments. The next gate
should try a PCurve/export rebuild strategy before mesh handoff or solver-budget
work.
