# fairing_solid real mesh_handoff probe v1

This probe tries the real fairing geometry against the current Gmsh closed-solid handoff route.
It records handoff, timeout, or blocker evidence without running SU2.

- probe_status: `mesh_handoff_pass`
- mesh_probe_status: `completed`
- mesh_handoff_status: `written`
- provider_status: `materialized`
- marker_summary_status: `component_wall_and_farfield_present`
- fairing_force_marker_status: `component_specific_marker_present`
- provider_volume_count: `1`
- volume_element_count: `153251`
- backend_rescale_applied: `True`
- error: `None`

## Blocking Reasons

- `fairing_real_geometry_su2_handoff_not_run`
- `fairing_solver_not_run`
- `convergence_gate_not_run`

## Limitations

- This is a bounded coarse real-geometry probe, not production default sizing.
- It does not run BL runtime.
- It does not run SU2_CFD.
- convergence_gate.v1 was not emitted.
- A mesh handoff pass is not solver credibility without SU2 and convergence evidence.
