# fairing_solid reference policy probe v1

This report compares external fairing project reference policy evidence with the current hpa-mdo real fairing SU2 handoff probe.

- reference_policy_status: `reference_mismatch_observed`
- external_reference_status: `candidate_available`
- hpa_current_reference_status: `warn`
- marker_mapping_status: `compatible_mapping_required`
- external_ref_area: `1.0`
- external_ref_length: `2.82880659`
- external_velocity_mps: `6.5`
- hpa_ref_area: `100.0`
- hpa_ref_length: `1.0`
- hpa_velocity_mps: `10.0`
- reference_mismatch_fields: `ref_area, ref_length, velocity_mps`

## Blocking Reasons

- `hpa_current_reference_policy_mismatch`
- `hpa_current_reference_geometry_warn`
- `solver_not_run`
- `convergence_gate_not_run`

## Limitations

- This is report-only evidence; it does not apply the external fairing reference policy to hpa-mdo runtime defaults.
- The external fairing marker `fairing` must be explicitly mapped to hpa-mdo marker `fairing_solid` before runtime use.
- Solver and convergence evidence remain absent in this hpa-mdo probe.
