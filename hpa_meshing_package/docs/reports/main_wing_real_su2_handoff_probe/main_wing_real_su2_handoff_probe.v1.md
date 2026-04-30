# main_wing real su2_handoff probe v1

This probe materializes an SU2 case from the real main-wing mesh handoff without executing SU2_CFD.

- materialization_status: `su2_handoff_written`
- source_mesh_probe_status: `mesh_handoff_pass`
- source_mesh_handoff_status: `written`
- su2_contract: `su2_handoff.v1`
- input_mesh_contract: `mesh_handoff.v1`
- solver_execution_status: `not_run`
- convergence_gate_status: `not_run`
- wall_marker_status: `main_wing_marker_present`
- force_surface_scope: `component_subset`
- component_force_ownership_status: `owned`
- reference_geometry_status: `warn`
- observed_velocity_mps: `6.5`
- runtime_max_iterations: `12`
- volume_element_count: `584460`
- error: `None`

## Blocking Reasons

- `main_wing_solver_not_run`
- `convergence_gate_not_run`
- `main_wing_real_reference_geometry_warn`

## HPA-MDO Guarantees

- `real_main_wing_mesh_handoff_v1_consumed`
- `su2_handoff_v1_written_for_real_main_wing`
- `runtime_cfg_written`
- `su2_mesh_written`
- `hpa_standard_flow_conditions_6p5_mps`
- `solver_not_executed`
- `convergence_gate_not_emitted`
- `production_default_unchanged`
- `main_wing_force_marker_owned`

## Limitations

- This probe materializes an SU2 case from the real main-wing mesh handoff only; it does not run SU2_CFD.
- convergence_gate.v1 is not emitted because no solver history exists.
- Reference geometry is a declared Blackcat main-wing full-span reference; warn/fail remains a blocker for credibility.
- The upstream mesh is a coarse bounded probe, not production default sizing.
- Production defaults were not changed.
