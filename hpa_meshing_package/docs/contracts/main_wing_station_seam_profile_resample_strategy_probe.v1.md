# Main Wing Station-Seam Profile Resample Strategy Probe v1

`main_wing_station_seam_profile_resample_strategy_probe.v1` is a report-only
OpenCSM export-variant probe for the real main-wing station-seam blocker. It
consumes the station-seam export-source audit and its generated `rebuild.csm`,
then writes a candidate CSM that keeps a single OpenCSM `rule` while resampling
all section sketches to a uniform closed-profile point count. It does not change
`esp_rebuilt`, Gmsh routes, SU2 handoff, convergence gates, or production
defaults.

The probe must record:

- source export-source audit path
- source `rebuild.csm` path
- source section profile point counts
- target uniform profile point count
- target defect station `y` values
- candidate materialization status, CSM/STEP/log paths, and OCC/Gmsh topology
  counts when materialization is requested
- span-bounds preservation against the source station y-range
- target-station plane-face counts
- engineering findings, blockers, next actions, and limitations

Current status meanings:

- `profile_resample_candidate_materialized_needs_brep_validation`: the
  materialized candidate imports as one body / one volume, preserves the full
  station y-range, and has no target-station cap faces. This is not mesh-ready
  or CFD-ready; it still needs station BRep/PCurve validation and a bounded
  mesh-handoff probe before any route promotion.
- `profile_resample_candidate_materialized_but_topology_risk`: materialization
  succeeded, but topology is still not acceptable for the next BRep gate.
- `profile_resample_candidate_materialization_failed`: materialization was
  requested, but no usable STEP was produced.
- `profile_resample_candidate_source_only_ready_for_materialization`: source
  candidates were generated/evaluated, but materialization was not requested.
- `blocked`: required input artifacts are missing or invalid.

For the current main-wing route, the committed evidence is
`profile_resample_candidate_materialized_needs_brep_validation`. The source
section profile point counts are `57/59`, and the candidate uniformizes them to
`59` while keeping a single `rule`. It materializes as `1 volume / 32 surfaces`,
preserves `y=-16.5..16.5 m`, and has zero station-plane cap faces at
`y=-10.5 m` and `y=13.5 m`.

This is a plausible geometry-rebuild candidate, not a product route. The next
gate is station BRep/PCurve validation on the profile-resample STEP before any
mesh handoff or solver-budget campaign.
