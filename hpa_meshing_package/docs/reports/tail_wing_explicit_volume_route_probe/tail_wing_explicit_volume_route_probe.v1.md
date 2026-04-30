# Tail Wing Explicit Volume Route Probe v1

- route_probe_status: `explicit_volume_route_blocked`
- mesh_handoff_status: `not_written`
- su2_volume_handoff_status: `not_su2_ready`
- provider_status: `materialized`
- provider_surface_count: `6`
- provider_volume_count: `0`
- surface_loop_volume_status: `volume_created`
- surface_loop_farfield_cut_status: `invalid_fluid_boundary`
- surface_loop_signed_volume: `-0.03945880563457954`
- baffle_fragment_status: `mesh_failed_plc`
- recommended_next: `repair_explicit_volume_orientation_or_baffle_surface_ownership`

## Candidates

| candidate | strategy | status | volumes | farfield surfaces | tail surfaces | mesh |
| --- | --- | --- | --- | --- | --- | --- |
| `surface_loop_volume` | `occ_surface_loop_add_volume` | `volume_created` | `1` | `0` | `6` | `not_attempted` |
| `baffle_fragment_volume` | `occ_baffle_fragment` | `mesh_failed_plc` | `1` | `6` | `12` | `mesh_failed` |

## Blocking Reasons

- `tail_explicit_surface_loop_volume_not_valid_external_flow_handoff`
- `tail_baffle_fragment_mesh_failed_plc`
- `tail_wing_solver_not_run`
- `convergence_gate_not_run`

## Guarantees

- `real_vsp3_source_consumed`
- `esp_rebuilt_tail_wing_geometry_materialized`
- `explicit_occ_surface_loop_add_volume_attempted`
- `baffle_fragment_volume_attempted`
- `mesh_handoff_not_emitted`
- `su2_volume_handoff_not_claimed`
- `production_default_unchanged`

## Limitations

- This is a report-only route probe and does not emit mesh_handoff.v1.
- The existing production default route is unchanged.
- A Gmsh volume tag alone is not treated as a valid external-flow handoff.
- SU2_CFD was not executed.
- convergence_gate.v1 was not emitted.
