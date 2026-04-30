# Main Wing Station-Seam Side-Aware Parametrization Probe v1

`main_wing_station_seam_side_aware_parametrization_probe.v1` is a report-only
candidate-generation gate for the main-wing station-seam route. It reads the
profile parametrization audit, parses the source `rebuild.csm`, resamples upper
and lower airfoil sides independently to preserve side correspondence, and can
materialize a candidate STEP through the existing OpenCSM batch path. It does
not change production defaults, does not run Gmsh, and does not run SU2.

The probe must record:

- source profile parametrization audit path
- source `rebuild.csm` path
- target station `y` values
- source and candidate profile point counts
- target upper/lower side point counts
- per-section upper/lower side counts
- TE/LE anchor deltas
- materialized candidate topology summary when requested
- station cap-face checks at target stations
- engineering findings, blockers, next actions, and limitations

Current status meanings:

- `side_aware_parametrization_candidate_materialized_needs_brep_validation`: the
  candidate materialized as one full-span volume with no target-station cap
  faces; station BRep/PCurve validation still has to run before mesh handoff.
- `side_aware_parametrization_candidate_topology_risk`: the candidate
  materialized but has volume/span/cap-face topology risk.
- `side_aware_parametrization_candidate_materialization_failed`: OpenCSM batch
  materialization failed or did not write a STEP.
- `side_aware_parametrization_source_only_ready_for_materialization`: the CSM
  candidate text can be generated, but materialization was not requested.
- `blocked`: required inputs are missing or invalid.

For the current main-wing route, the committed evidence is
`side_aware_parametrization_candidate_materialized_needs_brep_validation`: the
candidate uses 30 upper-side and 30 lower-side points per section, preserves
TE/LE anchors exactly, materializes as `1 volume / 32 surfaces`, preserves the
full `y=-16.5..16.5 m` span, and has no station-plane cap faces at
`y=-10.5 m` or `y=13.5 m`.

This is not mesh-ready or CFD-ready evidence. The next gate must run candidate
station BRep/PCurve validation on the side-aware STEP before any mesh handoff,
solver-budget work, or convergence claims. That downstream gate now exists as
`main_wing_station_seam_side_aware_brep_validation_probe.v1`; current evidence
shows the side-aware candidate remains blocked at station-edge PCurve
consistency, so this parametrization status must not be read as mesh-ready.
