# main_wing_geometry_provenance_probe.v1

`main_wing_geometry_provenance_probe.v1` records source OpenVSP geometry
provenance needed to interpret main-wing alpha-zero solver smokes.

## Purpose

This probe answers whether the selected real `Main Wing` geometry has built-in
incidence, twist, and cambered airfoil evidence before spending more solver
time on alpha or convergence questions.

It does not run Gmsh, does not run SU2, and does not certify aerodynamic
performance.

## Required Top-Level Fields

- `schema_version`: fixed string `main_wing_geometry_provenance_probe.v1`
- `component`: fixed string `main_wing`
- `execution_scope`: `vsp3_geometry_provenance_no_solver`
- `production_default_changed`: must be `false`
- `geometry_provenance_status`
- `source_path`
- `selected_geom_id`
- `selected_geom_name`
- `x_rotation_deg`
- `y_rotation_deg`
- `z_rotation_deg`
- `installation_incidence_deg`
- `section_count`
- `sections`
- `twist_summary`
- `airfoil_summary`
- `alpha_zero_interpretation`
- engineering assessment, guarantees, limitations, and next actions

## Pass Meaning

`provenance_available` means the VSP3 source was parsed and `Main Wing`
provenance was recorded. It is geometry evidence only.

For the current Blackcat source, a positive `Y_Rotation` plus cambered embedded
airfoil coordinates means `alpha=0 deg` in SU2 should not be interpreted as a
zero-lift geometric condition. A positive low CL can be physically plausible,
but `CL <= 1.0` remains a main-wing lift-acceptance blocker at the HPA standard
`V=6.5 m/s`.

## Promotion Rule

This probe can support a future alpha/trim sanity probe by making the geometry
interpretation explicit. It cannot promote a solver smoke to converged CFD.
