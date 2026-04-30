# main_wing_esp_rebuilt_geometry_smoke.v1

`main_wing_esp_rebuilt_geometry_smoke.v1` records provider-only geometry
evidence for the main-wing route.

It is intentionally pre-mesh:

- it consumes `data/blackcat_004_origin.vsp3`
- it selects the OpenVSP `Main Wing` geometry as `main_wing`
- it runs the experimental `esp_rebuilt` provider
- it writes a normalized STEP and provider topology artifacts
- it does not run Gmsh
- it does not emit `mesh_handoff.v1`
- it does not run `SU2_CFD`
- it does not emit `su2_handoff.v1` or `convergence_gate.v1`
- it does not change production defaults

## Required Top-Level Fields

- `schema_version`: fixed string `main_wing_esp_rebuilt_geometry_smoke.v1`
- `component`: fixed string `main_wing`
- `source_fixture`
- `geometry_provider`: fixed string `esp_rebuilt`
- `geometry_family`: fixed string `thin_sheet_lifting_surface`
- `execution_mode`: fixed string `provider_geometry_only_no_gmsh_no_su2`
- `no_gmsh_execution`: must be `true`
- `no_su2_execution`: must be `true`
- `no_bl_runtime`: must be `true`
- `production_default_changed`: must be `false`
- `geometry_smoke_status`
- `provider_status`
- `validation_status`
- `mesh_handoff_status`
- `su2_handoff_status`
- `effective_component`
- `selected_geom_*`
- topology counts, paths, guarantees, blocking reasons, and limitations

## Pass Meaning

A pass means hpa-mdo can select the real main-wing surface from the VSP model
and materialize an ESP-normalized thin lifting-surface STEP.

It does **not** mean the main-wing route is mesh-ready or CFD-ready. The next
gate is a real-geometry `mesh_handoff.v1`; synthetic main-wing slab mesh and
SU2 handoff evidence are not substitutes for that.
