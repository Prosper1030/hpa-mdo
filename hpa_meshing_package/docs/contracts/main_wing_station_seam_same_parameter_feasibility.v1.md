# Main Wing Station-Seam Same-Parameter Feasibility v1

`main_wing_station_seam_same_parameter_feasibility.v1` is a report-only
feasibility gate for the real main-wing station-seam hotspot. It reads the BRep
hotspot probe, loads the selected normalized STEP, and tests whether a bounded
in-memory same-parameter repair can recover the suspect station edges. It does
not write a repaired STEP, does not run Gmsh, does not run SU2, and does not
change production defaults.

The probe must record:

- source BRep hotspot probe path
- selected normalized STEP path
- requested curve and surface tags inherited from the hotspot probe
- target edge ids and owner face ids
- documented API semantics for the repair/check functions used
- baseline per-edge/per-face PCurve, same-parameter,
  curve-3D-with-PCurve, and vertex-tolerance checks
- per-tolerance repair attempts
- baseline and attempt summaries
- engineering findings, blockers, next actions, and limitations

Current status meanings:

- `same_parameter_repair_recovered`: at least one bounded in-memory
  same-parameter repair attempt recovered the target station checks.
- `same_parameter_repair_not_recovered`: the target station checks remained
  unrecovered across the configured tolerance sweep.
- `unavailable`: required runtime support for the feasibility check is
  unavailable.
- `blocked`: required input artifacts are missing or invalid.

For the current main-wing route, the committed evidence is
`same_parameter_repair_not_recovered`: target PCurves are present before repair,
but baseline same-parameter / curve-3D-with-PCurve / vertex-tolerance checks do
not all pass, and `BRepLib.SameParameter` attempts at `1e-7`, `1e-6`, `1e-5`,
`1e-4`, and `1e-3` recover zero targets.

This is evidence against treating a simple OCCT same-parameter pass as the
station-seam repair. The next gate should inspect or rebuild the station
PCurves / station-seam geometry before promoting a compound meshing policy or
spending more solver budget.
