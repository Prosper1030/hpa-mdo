# fairing_solid_real_geometry_smoke.v1

`fairing_solid_real_geometry_smoke.v1` records provider-only geometry evidence
for the real fairing route.

It is intentionally pre-mesh:

- it consumes a real fairing `.vsp3` source, defaulting to the external
  `HPA-Fairing-Optimization-Project` `best_design.vsp3` artifact when present
- it selects an OpenVSP `Fuselage` geometry as the fairing candidate
- it runs `openvsp_surface_intersection` to materialize a normalized STEP
- it records closed-solid topology counts from the provider topology probe
- it does not run Gmsh meshing
- it does not emit `mesh_handoff.v1`
- it does not run `SU2_CFD`
- it does not emit `su2_handoff.v1` or `convergence_gate.v1`
- it does not change production defaults

## Required Top-Level Fields

- `schema_version`: fixed string `fairing_solid_real_geometry_smoke.v1`
- `component`: fixed string `fairing_solid`
- `source_fixture`
- `geometry_provider`: fixed string `openvsp_surface_intersection`
- `geometry_family`: fixed string `closed_solid`
- `execution_mode`: fixed string `provider_geometry_only_no_mesh_no_su2`
- `no_gmsh_meshing_execution`: must be `true`
- `gmsh_topology_probe_status`
- `no_su2_execution`: must be `true`
- `no_bl_runtime`: must be `true`
- `production_default_changed`: must be `false`
- `geometry_smoke_status`
- `provider_status`
- `validation_status`
- `mesh_handoff_status`
- `su2_handoff_status`
- `selected_geom_*`
- topology counts, unit-scaling evidence, paths, guarantees, blocking reasons,
  and limitations

## Pass Meaning

A pass means hpa-mdo can consume a real fairing VSP source, select a Fuselage
candidate, materialize a normalized STEP, and observe closed-solid topology.

It does **not** mean the fairing route is mesh-ready or CFD-ready. The next gate
is a real-geometry `mesh_handoff.v1`; the synthetic fairing box mesh and SU2
handoff smokes remain useful route-materialization evidence, not real fairing
aerodynamic evidence.
