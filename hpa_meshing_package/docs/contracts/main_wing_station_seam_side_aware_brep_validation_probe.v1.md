# Main Wing Station-Seam Side-Aware BRep Validation Probe v1

`main_wing_station_seam_side_aware_brep_validation_probe.v1` is a report-only
gate for the main-wing side-aware station-seam candidate. It reads the
side-aware parametrization report, resolves the candidate STEP, selects target
station edges by candidate station-y geometry, and records BRep / PCurve checks
without replaying old fixture curve or surface tags.

The probe must record:

- source side-aware parametrization probe path
- candidate STEP path
- target station `y` values and station tolerance
- geometry-driven target selection summary
- whether old fixture curve / surface tags were replayed
- selected candidate curve and owner surface tags
- station-edge PCurve presence, curve-3D-with-PCurve, same-parameter-by-face,
  vertex-tolerance-by-face, and range checks
- owner-face BRep and wire checks
- engineering findings, blockers, next actions, and limitations

Current status meanings:

- `side_aware_candidate_station_brep_edges_valid`: candidate station edges and
  owner faces pass the BRep / PCurve consistency gate. This only permits a
  bounded mesh-handoff comparison; it does not promote production defaults.
- `side_aware_candidate_station_brep_edges_suspect`: candidate station edges
  or owner faces were found, but one or more BRep / PCurve consistency checks
  failed.
- `side_aware_candidate_station_brep_validation_unavailable`: the OCP or Gmsh
  runtime needed for the shared station-y BRep collector was unavailable.
- `blocked`: required inputs are missing or invalid.

For the current main-wing route, the committed evidence is
`side_aware_candidate_station_brep_edges_suspect`: the candidate remains a
single full-span volume with 32 surfaces, and target station edges were selected
geometrically (`source_fixture_tags_replayed=false`), but all 6 selected station
edges fail the combined PCurve consistency checks. PCurves are present and the
owner-face wires are closed / connected / ordered; the blocker is the
curve-3D-with-PCurve, same-parameter-by-face, and vertex-tolerance-by-face
layer.

This is not mesh-ready or CFD-ready evidence. The next route gate is to repair
the OpenCSM / export-side PCurve generation for the side-aware candidate before
any Gmsh mesh handoff, solver-budget campaign, or convergence claim.
