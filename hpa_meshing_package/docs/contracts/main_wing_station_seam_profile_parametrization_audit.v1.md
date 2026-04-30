# Main Wing Station-Seam Profile Parametrization Audit v1

`main_wing_station_seam_profile_parametrization_audit.v1` is a report-only
diagnostic gate for the profile-resample main-wing station-seam candidate. It
reads the profile-resample strategy report and the candidate BRep validation
report, parses the generated CSM section segments, and correlates selected
station-edge lengths with the candidate profile segment layout. It does not
materialize a new candidate, does not run Gmsh, does not run SU2, and does not
change production defaults.

The audit must record:

- source profile-resample strategy report path
- source BRep validation report path
- source and candidate CSM paths
- target station `y` values
- source and candidate profile point-count summaries
- per-target station candidate/source section segment summaries
- per-target station curve-to-segment correlations
- station-edge PCurve failure summary
- engineering findings, blockers, next actions, and limitations

Current status meanings:

- `profile_parametrization_seam_fragment_correlation_observed`: the audit
  captured station-edge failures, terminal `linseg` fragment matches, and
  spline-rest-arc matches on the current candidate.
- `profile_parametrization_audit_captured`: the audit ran and produced
  evidence, but did not capture the full seam-fragment correlation pattern.
- `blocked`: required input artifacts are missing or invalid.

For the current main-wing route, the committed evidence is
`profile_parametrization_seam_fragment_correlation_observed`: all six
candidate station-edge checks still fail PCurve consistency, four short station
curves match the profile terminal `linseg` segments, and two long station
curves match the spline rest arcs.

This is evidence for changing export / section parametrization before mesh
handoff or solver-budget work. The next gate should prototype a side-aware
profile parametrization candidate that preserves upper/lower correspondence and
rerun the profile-resample BRep validation before any promotion.
