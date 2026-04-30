# Main Wing Station-Seam ShapeFix Feasibility v1

`main_wing_station_seam_shape_fix_feasibility.v1` is a report-only feasibility
gate for the real main-wing station-seam hotspot. It reads the station-seam
same-parameter feasibility report, loads the selected normalized STEP, and tests
whether bounded in-memory `ShapeFix_Edge` operations can recover the target
station checks. It does not write a repaired STEP, does not run Gmsh, does not
run SU2, and does not change production defaults.

The probe must record:

- source same-parameter feasibility report path
- selected normalized STEP path
- requested curve and surface tags inherited from the source report
- target edge ids and owner face ids
- documented operation semantics and recovery definition
- baseline per-edge/per-face PCurve, same-parameter,
  curve-3D-with-PCurve, and vertex-tolerance checks
- per-operation and per-tolerance repair attempts
- baseline and attempt summaries
- engineering findings, blockers, next actions, and limitations

Current status meanings:

- `shape_fix_repair_recovered`: at least one bounded in-memory `ShapeFix_Edge`
  attempt recovered all target station checks.
- `shape_fix_repair_not_recovered`: all configured `ShapeFix_Edge` attempts
  failed to recover the target station checks.
- `unavailable`: required runtime support for the feasibility check is
  unavailable.
- `blocked`: required input artifacts are missing or invalid.

For the current main-wing route, the committed evidence is
`shape_fix_repair_not_recovered`: target PCurves are present before repair, but
baseline station checks fail, and 25 attempts across five operations and five
tolerances recover zero targets.

This is evidence against spending more time on generic OCCT edge-fix sweeps
until the PCurve generation / station-seam export strategy changes. The next
gate should rebuild station PCurves or export station seams differently before
promoting a compound meshing policy or spending more solver budget.
