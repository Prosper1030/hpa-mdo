# fairing_solid_reference_override_su2_handoff_probe.v1

`fairing_solid_reference_override_su2_handoff_probe.v1` records a gated SU2
handoff materialization for the real fairing mesh using the neighboring fairing
project reference policy.

It is not a solver run and not a production-default change.

## Guarantees

- consumes `fairing_solid_reference_policy_probe.v1`
- consumes `fairing_solid_real_su2_handoff_probe.v1`
- applies external `REF_AREA`, `REF_LENGTH`, velocity, density, viscosity, and
  temperature through `SU2RuntimeConfig.reference_override`
- maps external marker `fairing` to hpa-mdo marker `fairing_solid`
- writes `su2_handoff.v1`, `mesh.su2`, and `su2_runtime.cfg`
- preserves reference override warnings in `su2_handoff.v1` provenance
- does not execute `SU2_CFD`
- does not emit `convergence_gate.v1`
- does not change production defaults

## Key Fields

- `materialization_status`
- `reference_override_status`
- `marker_mapping_status`
- `previous_reference`
- `applied_reference`
- `moment_origin_policy_status`
- `reference_geometry_status`
- `component_force_ownership_status`
- `hpa_mdo_guarantees`
- `blocking_reasons`

`reference_override_status=applied_with_moment_origin_warning` means drag
coefficient normalization has explicit fairing policy evidence, but moment
coefficients remain blocked until a non-borrowed moment-origin policy exists.
