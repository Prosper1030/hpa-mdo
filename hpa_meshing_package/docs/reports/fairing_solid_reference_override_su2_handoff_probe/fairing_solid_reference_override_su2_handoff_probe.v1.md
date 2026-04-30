# fairing_solid reference override su2_handoff probe v1

This probe materializes an SU2 handoff with the neighboring fairing project reference policy, without executing SU2_CFD.

- materialization_status: `su2_handoff_written`
- reference_override_status: `applied_with_moment_origin_warning`
- marker_mapping_status: `mapped_external_fairing_to_fairing_solid`
- reference_geometry_status: `warn`
- component_force_ownership_status: `owned`
- applied_ref_area: `1.0`
- applied_ref_length: `2.82880659`
- applied_velocity_mps: `6.5`
- moment_origin_policy_status: `borrowed_zero_origin_for_drag_only`
- solver_execution_status: `not_run`
- convergence_gate_status: `not_run`
- error: `None`

## Blocking Reasons

- `fairing_solver_not_run`
- `convergence_gate_not_run`
- `fairing_moment_origin_policy_incomplete_for_moment_coefficients`

## HPA-MDO Guarantees

- `external_fairing_reference_override_applied`
- `su2_handoff_v1_written_with_user_declared_reference`
- `runtime_cfg_written`
- `su2_mesh_written`
- `solver_not_executed`
- `convergence_gate_not_emitted`
- `production_default_unchanged`
- `fairing_solid_force_marker_owned`
- `external_fairing_marker_mapped_to_fairing_solid`

## Limitations

- This probe materializes an SU2 handoff with an explicit external fairing reference override; it does not run SU2_CFD.
- The external fairing marker is mapped to the hpa-mdo fairing_solid marker, not used as a new mesh marker.
- Moment-origin policy remains incomplete when the source origin is zero; drag coefficients may be reference-policy corrected, but moment coefficients are not promoted.
- Production defaults were not changed.
- reference_wing_quantities_unavailable_using_vspaero_settings
- geometry_derived_moment_origin_is_zero_vector
- borrowed_zero_moment_origin_from_source_su2_handoff
