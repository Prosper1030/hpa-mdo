# Main Wing Station-Seam Profile Resample BRep Validation Probe v1

`main_wing_station_seam_profile_resample_brep_validation_probe.v1` is a
report-only BRep/PCurve gate for the profile-resample main-wing station-seam
candidate. It consumes the profile-resample strategy report, resolves the
candidate STEP, geometrically selects station-y seam edges from that candidate
topology, and validates OCCT BRep / PCurve checks for those edges and their
owner faces. It must not replay old station-fixture curve or surface tags as
evidence.

The probe must record:

- profile-resample report path
- candidate STEP path
- target station `y` values and station tolerance
- target-selection mode, selected candidate curve tags, selected candidate
  surface tags, and whether source fixture tags were replayed
- per-station candidate edge checks, including PCurve presence,
  curve-3D-with-PCurve, same-parameter, vertex-tolerance, PCurve-range,
  same-parameter flag, same-range flag, BRepCheck validity, and length match
- owner-face wire checks
- engineering findings, blockers, next actions, and limitations

Current status meanings:

- `profile_resample_candidate_station_brep_edges_valid`: station edges were
  selected geometrically from the candidate STEP, all target stations were
  covered, shape and owner faces were valid, and all station-edge PCurve /
  same-parameter / vertex-tolerance checks passed. This still does not make the
  candidate mesh-ready or CFD-ready.
- `profile_resample_candidate_station_brep_edges_suspect`: the candidate STEP
  was inspected, but station-edge BRep/PCurve checks did not all pass.
- `profile_resample_candidate_station_brep_validation_unavailable`: OCCT/Gmsh
  runtime or BRep helper inspection was unavailable.
- `blocked`: required input artifacts are missing or invalid.

For the current main-wing route, the committed evidence is
`profile_resample_candidate_station_brep_edges_suspect`. The candidate remains
`1 volume / 32 surfaces`, and station seam edges are selected by candidate
station-y geometry rather than old tags. Six station edges are found at
`y=-10.5 m` and `y=13.5 m`; PCurves are present and owner-face wires are
closed/connected/ordered, but curve-3D-with-PCurve, same-parameter-by-face, and
vertex-tolerance-by-face checks are still suspect. Therefore the profile-
resample candidate is not mesh-ready, and the next gate is a station PCurve /
export repair before bounded mesh handoff.
