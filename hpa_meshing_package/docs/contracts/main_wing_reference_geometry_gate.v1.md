# main_wing_reference_geometry_gate.v1

`main_wing_reference_geometry_gate.v1` records report-only provenance checks for
the reference values used by the real main-wing SU2 handoff.

It is intentionally non-runtime:

- it reads the main-wing real geometry smoke
- it reads the main-wing real mesh handoff probe
- it reads the main-wing real SU2 handoff probe
- it reads the applied SU2 reference values
- it cross-checks declared span against real geometry bounds
- it keeps reference chord and moment-origin provenance explicit
- it does not run Gmsh
- it does not run `SU2_CFD`
- it does not edit `su2_runtime.cfg`
- it does not change production defaults

## Required Top-Level Fields

- `schema_version`: fixed string `main_wing_reference_geometry_gate.v1`
- `component`: fixed string `main_wing`
- `execution_mode`: fixed string `reference_geometry_report_only_no_solver`
- `production_default_changed`: must be `false`
- `reference_gate_status`
- `source_fixture`
- source geometry, mesh-probe, SU2-probe, and SU2-handoff paths
- `observed_velocity_mps`
- `applied_reference`
- `derived_full_span_m`
- `geometry_bounds_span_y_m`
- `selected_geom_full_span_y_m`
- `selected_geom_chord_x_m`
- `geometry_bounds_chord_x_m`
- `checks`
- guarantees, blocking reasons, and limitations

## Pass Meaning

`pass` may only mean the applied positive reference values are supported by
independent provenance checks required by this gate.

`warn` means the route has useful reference evidence but must remain blocked for
comparability. The current committed report cross-checks the 33 m full span
against real geometry bounds, but the 1.05 m reference chord and quarter-chord
moment origin are still not independently certified.

## Promotion Rule

This gate can move reference geometry from vague warning to explicit blocker
labels. It cannot make solver coefficients credible until:

1. reference chord provenance is independently owned
2. moment-origin or aircraft-CG policy is documented and owned
3. the solver run has a passing convergence gate
4. the mesh sizing / BL policy is promoted separately
