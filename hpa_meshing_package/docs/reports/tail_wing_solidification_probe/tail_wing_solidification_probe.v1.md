# tail_wing solidification probe v1

This probe checks whether naive Gmsh heal/sew/makeSolids can turn the real ESP tail surfaces into OCC volumes.

- solidification_status: `no_volume_created`
- provider_status: `materialized`
- provider_surface_count: `6`
- provider_volume_count: `0`
- best_output_surface_count: `12`
- best_output_volume_count: `0`
- recommended_next: `explicit_caps_or_baffle_volume_route_required`

## Blocking Reasons

- `tail_naive_gmsh_heal_solidification_no_volume`
- `tail_surface_only_mesh_not_su2_volume_handoff`
- `tail_wing_solver_not_run`
- `convergence_gate_not_run`

## Attempts

- `gmsh_heal_make_solids_1`: tolerance=1e-06, fix_small_edges=True, output_volume_count=0
- `gmsh_heal_make_solids_2`: tolerance=1e-05, fix_small_edges=True, output_volume_count=0
- `gmsh_heal_make_solids_3`: tolerance=0.0001, fix_small_edges=True, output_volume_count=0
- `gmsh_heal_make_solids_4`: tolerance=1e-06, fix_small_edges=False, output_volume_count=0
- `gmsh_heal_make_solids_5`: tolerance=1e-05, fix_small_edges=False, output_volume_count=0
- `gmsh_heal_make_solids_6`: tolerance=0.0001, fix_small_edges=False, output_volume_count=0

## Limitations

- mesh_handoff.v1 is not emitted by the solidification probe.
- No farfield subtraction or volume mesh is attempted in this probe.
- Gmsh heal/sew/makeSolids is evidence only; it is not a production repair policy.
- SU2_CFD was not executed.
- convergence_gate.v1 was not emitted.
