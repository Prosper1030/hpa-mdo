# WO-006 Current-GO CFD Completion Evidence

Completion gate: `pass`

## Route

- route: `current_go_mesh_native_no_bl_hxt_completion`
- boundary-layer route: `not_used_no_bl_route`
- symmetry marker: `not_used_full_span_current_go_mesh_native_route`

## Authority

- design mass: `98.5 kg`
- full span: `34.332286 m`
- half span: `17.166143 m`
- geometry source: `/Volumes/Samsung SSD/hpa-mdo/output/go_mode_main_wing_candidate/final_candidate_package/geometry_exports/avl_parity/current_avl_compromise_conservative_closed/section_table.csv`

## Mesh

- mesh: `output/baseline_A_team_release/wo006_su2_baseline_validation/wo006_current_go_cfd_completion/mesh.su2`
- quality gate: `pass`
- volume elements: `490116`
- non-positive volumes: `0`
- markers: `['farfield', 'wing_wall']`

## SU2

- config: `output/baseline_A_team_release/wo006_su2_baseline_validation/wo006_current_go_cfd_completion/su2_runtime.cfg`
- history: `output/baseline_A_team_release/wo006_su2_baseline_validation/wo006_current_go_cfd_completion/history.csv`
- iterations completed: `159`
- CL: `1.106421874`
- CD: `0.4752310368`
- NaN/Inf status: `pass`
- residual status: `pass`

## Engineering Trust Boundary

No-BL RANS on a tet mesh is acceptable here only as finite SU2 route/force evidence. It is not BL-resolved drag, power, y+, grid V&V, RFQ, or final aircraft sign-off evidence.
