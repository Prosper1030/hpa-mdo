# fairing_solid real su2_handoff probe v1

This probe materializes an SU2 case from the real fairing mesh handoff without executing SU2_CFD.

- materialization_status: `su2_handoff_written`
- source_mesh_probe_status: `mesh_handoff_pass`
- source_mesh_handoff_status: `written`
- su2_contract: `su2_handoff.v1`
- input_mesh_contract: `mesh_handoff.v1`
- solver_execution_status: `not_run`
- convergence_gate_status: `not_run`
- wall_marker_status: `fairing_solid_marker_present`
- force_surface_scope: `component_subset`
- component_force_ownership_status: `owned`
- reference_geometry_status: `warn`
- volume_element_count: `153251`
- error: `None`

## Blocking Reasons

- `fairing_solver_not_run`
- `convergence_gate_not_run`
- `fairing_real_reference_geometry_warn`

## HPA-MDO Guarantees

- `real_fairing_mesh_handoff_v1_consumed`
- `su2_handoff_v1_written_for_real_fairing`
- `runtime_cfg_written`
- `su2_mesh_written`
- `solver_not_executed`
- `convergence_gate_not_emitted`
- `production_default_unchanged`
- `fairing_solid_force_marker_owned`

## Limitations

- This probe materializes an SU2 case from the real fairing mesh handoff only; it does not run SU2_CFD.
- convergence_gate.v1 is not emitted because no solver history exists.
- Reference geometry is taken from real fairing provider metadata when available; warn/fail remains a blocker for credibility.
- The upstream mesh is a coarse bounded probe, not production default sizing.
- Production defaults were not changed.
