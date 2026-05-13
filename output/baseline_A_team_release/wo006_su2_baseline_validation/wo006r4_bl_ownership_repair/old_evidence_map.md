# WO-006R4 Old Evidence Map

This campaign starts from prior evidence instead of rerunning every old path.

## wo006r2_current_go_adapter_blocker

- Artifact: `/Volumes/Samsung SSD/hpa-mdo/output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r2_cfd_recovery_campaign`
- Read: current GO BL and high-mesh attempts blocked in Gmsh HXT PLC recovery
- Use in R4: blocker localization
- Not used for: coefficient truth

## old_hxt_bl_wing_h_0p20

- Artifact: `hpa_meshing_package/docs/reports/mesh_native_hxt_thread_profile/mesh_native_hxt_thread_profile.v1.md`
- Read: 1,125,409 cells; 992,352 BL prisms; marker-owned short smoke
- Use in R4: serious BL target/template
- Not used for: current Baseline A coefficient truth

## old_hxt_bl_wing_h_0p15

- Artifact: `hpa_meshing_package/docs/reports/mesh_native_hxt_thread_profile/mesh_native_hxt_thread_profile.v1.md`
- Read: 1,515,251 cells; two non-positive BL quality items
- Use in R4: finer-mesh BL quality warning boundary
- Not used for: solver-ready mesh

## wo006r3_high_mesh_no_bl_handoff

- Artifact: `/Volumes/Samsung SSD/hpa-mdo/output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r3_surface_topology_repair/mesh_handoff.v1.json`
- Read: 936,017 no-BL tets; marker audit pass; SU2 reached iteration 75
- Use in R4: current GO no-BL readability handoff baseline
- Not used for: BL/y+ handoff or drag/power truth
