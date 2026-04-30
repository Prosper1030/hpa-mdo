# fairing_solid_reference_policy_probe.v1

`fairing_solid_reference_policy_probe.v1` records report-only evidence for the
real fairing reference policy used by the neighboring fairing optimization
project.

It is intentionally non-runtime:

- it reads the external fairing project fluid-condition config
- it reads an external fairing SU2 config when available
- it compares those values with the current hpa-mdo real fairing SU2 handoff
- it does not run Gmsh
- it does not run `SU2_CFD`
- it does not change production defaults

## Required Top-Level Fields

- `schema_version`: fixed string `fairing_solid_reference_policy_probe.v1`
- `component`: fixed string `fairing_solid`
- `execution_mode`: fixed string `external_fairing_reference_policy_report_only`
- `source_project_root`
- `reference_policy_status`
- `external_reference_status`
- `hpa_current_reference_status`
- `marker_mapping_status`
- `external_reference`
- `hpa_current_reference`
- `reference_mismatch_fields`
- `recommended_runtime_policy`
- guarantees, blocking reasons, and limitations

## Pass Meaning

`candidate_available` means the external fairing project provided complete
positive reference values for `REF_AREA`, `REF_LENGTH`, velocity, density, and
viscosity.

`reference_mismatch_observed` means a usable external candidate exists, but the
current hpa-mdo real fairing SU2 handoff does not yet use the same reference
policy. This is useful evidence, not a runtime apply.

## Promotion Rule

This probe can move the fairing route from vague `reference_geometry_status=warn`
to a concrete reference-policy mismatch. It cannot make solver coefficients
credible until hpa-mdo explicitly applies an approved reference override and then
records solver plus convergence evidence.
