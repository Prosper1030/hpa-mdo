# main_wing real su2_handoff probe v1

This probe materializes an SU2 case from the real main-wing mesh handoff without executing SU2_CFD.

- materialization_status: `blocked_before_su2_handoff`
- source_mesh_probe_status: `mesh_handoff_blocked`
- source_mesh_handoff_status: `missing`
- reference_policy: `openvsp_geometry_derived`
- su2_contract: `None`
- input_mesh_contract: `None`
- solver_execution_status: `not_run`
- convergence_gate_status: `not_run`
- wall_marker_status: `unavailable`
- force_surface_scope: `None`
- component_force_ownership_status: `insufficient_evidence`
- reference_geometry_status: `None`
- observed_velocity_mps: `None`
- runtime_max_iterations: `None`
- volume_element_count: `0`
- error: `Wrong topology of boundary mesh for parametrization`

## Blocking Reasons

- `main_wing_real_mesh_handoff_not_available`
- `main_wing_real_su2_handoff_not_materialized`

## HPA-MDO Guarantees


## Limitations

- The upstream real main-wing mesh handoff probe did not provide a written mesh_handoff.v1.
