# Main Wing Station-Seam Profile Resample Repair Feasibility Probe v1

`main_wing_station_seam_profile_resample_repair_feasibility_probe.v1` is a
report-only bounded repair feasibility gate for the profile-resample
station-seam candidate. It consumes the profile-resample BRep validation report,
uses the candidate-selected station edge / owner-face indices, and runs bounded
in-memory OCCT repair attempts. It does not write repaired geometry, promote a
mesh route, run SU2, or change production defaults.

The probe must record:

- profile-resample BRep validation report path
- candidate STEP path
- candidate target edges and owner face ids
- evaluated ShapeFix / SameParameter operations and tolerances
- baseline station-edge checks
- per-attempt recovery results
- baseline and attempt summaries
- engineering findings, blockers, next actions, and limitations

Current status meanings:

- `profile_resample_station_shape_fix_repair_recovered`: at least one bounded
  in-memory repair attempt made every target station-edge PCurve,
  same-parameter, curve-3D-with-PCurve, and vertex-tolerance check pass.
- `profile_resample_station_shape_fix_repair_not_recovered`: attempts ran, but
  no operation/tolerance combination recovered the candidate station checks.
- `unavailable`: OCCT runtime or repair helper execution was unavailable.
- `blocked`: required input artifacts are missing or invalid.

For the current main-wing route, the committed evidence is
`profile_resample_station_shape_fix_repair_not_recovered`. Six candidate station
edges are evaluated across `y=-10.5 m` and `y=13.5 m`; baseline PCurves are
present but same-parameter / curve-3D-with-PCurve / vertex-tolerance checks do
not pass. A bounded sweep of 25 operation/tolerance combinations has
`recovered_attempt_count = 0`. The engineering conclusion is that the current
profile-resample candidate needs export/section-parametrization repair rather
than direct mesh handoff or more solver budget.
