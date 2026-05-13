/goal In /Volumes/Samsung SSD/hpa-mdo, execute WO-006R5: implement the conformal mesh-native BL+core merge needed after WO-006R4.

Start from:
- output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r4_bl_ownership_repair/
- route_decision.json
- blocker_register.csv
- owned_bl_block_summary.json
- core_probe_artifacts/
- hpa_meshing_package/src/hpa_meshing/mesh_native/near_wall_block.py
- hpa_meshing_package/src/hpa_meshing/mesh_native/gmsh_polyhedral.py

Current WO-006R4 verdict: `wo006r4_adapter_limitation_proven`.
First blocker: `Gmsh HXT PLC segment/facet intersection`.

Repair target:
write a conformal BL+core ownership merge that preserves bl_outer_interface, wake_cut, and span_cap faces, then export mixed prisms/pyramids/tets to SU2 with wing_wall/farfield ownership and quality gates.

Hard constraints:
- Preserve 98.5 kg, 34.332286 m full span, 17.166143 m half span, Sref/Cref/Bref.
- Do not change Baseline A external shape to make the mesh pass.
- Do not promote no-BL, tiny-smoke, old Black Cat, or unconverged coefficients.
- Only emit bl_mesh_handoff.v1.json after a conformal mixed BL+core SU2 mesh has
  marker audit pass, wall/farfield ownership, BL quality gate, and readability evidence.
