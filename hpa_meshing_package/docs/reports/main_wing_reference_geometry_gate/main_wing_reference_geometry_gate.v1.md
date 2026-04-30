# main_wing reference geometry gate v1

This report checks the provenance of the reference quantities used by the real main-wing SU2 handoff.

- reference_gate_status: `warn`
- observed_velocity_mps: `6.5`
- ref_area: `34.65`
- ref_length: `1.05`
- derived_full_span_m: `33.0`
- geometry_bounds_span_y_m: `33.0`
- selected_geom_full_span_y_m: `32.94930391715896`
- selected_geom_chord_x_m: `1.3023502084398801`
- geometry_bounds_chord_x_m: `1.3035885811941128`

## Checks

| check | status |
|---|---|
| `positive_reference_values` | `pass` |
| `declared_span_vs_bounds_y` | `pass` |
| `declared_span_vs_selected_geom_span` | `pass` |
| `ref_length_independent_source` | `warn` |
| `moment_origin_policy` | `warn` |

## Blocking Reasons

- `main_wing_reference_geometry_incomplete`
- `main_wing_reference_chord_not_independently_certified`
- `main_wing_moment_origin_not_certified`

## HPA-MDO Guarantees

- `reference_geometry_gate_evaluated`
- `reference_geometry_not_promoted_to_pass`
- `production_default_unchanged`
- `ref_area_ref_length_and_origin_present`
- `declared_span_crosschecked_against_real_geometry_bounds`
- `hpa_standard_flow_conditions_6p5_mps_observed`

## Limitations

- This gate is report-only and does not change the SU2 runtime config.
- Span is cross-checked against real geometry bounds, but the reference chord is still user-declared.
- Moment origin is a declared quarter-chord probe policy, not a certified aircraft CG or aerodynamic-reference policy.
- A reference-geometry warn must remain a comparability blocker for solver/convergence results.
