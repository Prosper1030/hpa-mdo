# main_wing_vspaero_panel_reference_probe.v1

`main_wing_vspaero_panel_reference_probe.v1` records existing VSPAERO
panel-mode evidence for the main-wing high-fidelity route readiness discussion.

## Purpose

This probe preserves a lower-order aerodynamic sanity reference without
promoting it to SU2 convergence or high-fidelity CFD evidence.

It reads committed/local VSPAERO `.polar` and `.vspaero` artifacts, compares the
integrated panel-mode `CLtot` against the HPA operating-point lift gate
(`CL > 1.0` at `V=6.5 m/s`), and optionally compares that value to the current
SU2 smoke selected by `main_wing_lift_acceptance_diagnostic.v1`.

It does not run VSPAERO, Gmsh, or SU2.

## Required Top-Level Fields

- `schema_version`: fixed string `main_wing_vspaero_panel_reference_probe.v1`
- `component`: fixed string `main_wing`
- `execution_scope`: `report_only_existing_vspaero_panel_artifacts`
- `production_default_changed`: must be `false`
- `panel_reference_status`
- `source_polar_path`
- `source_setup_path`
- `hpa_standard_flow_status`
- `minimum_acceptable_cl`
- `lift_acceptance_status`
- `selected_case`
- `setup_reference`
- `su2_smoke_comparison`
- engineering assessment, flags, guarantees, limitations, and next actions

## Pass Meaning

`panel_reference_available` means a VSPAERO panel `.polar` case was parsed and
its setup reports the HPA standard `V=6.5 m/s`.

`lift_acceptance_status=pass` only means the lower-order panel reference has
`CLtot > 1.0`. It supports the engineering reasonableness of the main-wing
`CL > 1.0` acceptance gate; it is not a SU2 convergence claim.

## Promotion Rule

The panel reference can be used as an external sanity baseline for alpha/trim
and coefficient magnitude. It cannot certify mesh quality, force-marker
ownership, SU2 convergence, or final aircraft performance.
