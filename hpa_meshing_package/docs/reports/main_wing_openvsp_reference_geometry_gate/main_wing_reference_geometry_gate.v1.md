# main_wing reference geometry gate v1

This report checks the provenance of the reference quantities used by the real main-wing SU2 handoff.

- reference_gate_status: `warn`
- observed_velocity_mps: `6.5`
- ref_area: `35.175`
- ref_length: `1.0425`
- openvsp_reference_status: `available`
- openvsp_sref: `35.175`
- openvsp_cref: `1.0425`
- derived_full_span_m: `33.0`
- derived_full_span_method: `area_provenance.details.wing_quantities.bref`
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
| `ref_length_independent_source` | `pass` |
| `applied_ref_area_vs_openvsp_sref` | `pass` |
| `moment_origin_policy` | `warn` |

## Blocking Reasons

- `main_wing_reference_geometry_incomplete`
- `main_wing_moment_origin_not_certified`

## HPA-MDO Guarantees

- `reference_geometry_gate_evaluated`
- `reference_geometry_not_promoted_to_pass`
- `production_default_unchanged`
- `ref_area_ref_length_and_origin_present`
- `declared_span_crosschecked_against_real_geometry_bounds`
- `reference_span_provenance_recorded`
- `ref_length_crosschecked_against_openvsp_cref`
- `hpa_standard_flow_conditions_6p5_mps_observed`

## Limitations

- This gate is report-only and does not change the SU2 runtime config.
- Span is cross-checked against real geometry bounds, and reference chord is cross-checked against OpenVSP/VSPAERO cref when available.
- A reference-geometry warn must remain a comparability blocker for solver/convergence results.
- Moment origin is a declared quarter-chord probe policy and still needs aerodynamic-reference policy approval.
