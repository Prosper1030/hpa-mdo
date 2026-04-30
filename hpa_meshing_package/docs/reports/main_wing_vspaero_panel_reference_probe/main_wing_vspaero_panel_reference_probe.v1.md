# Main Wing VSPAERO Panel Reference Probe v1

This report reads existing VSPAERO panel-mode artifacts only; it does not run VSPAERO, Gmsh, or SU2.

- panel_reference_status: `panel_reference_available`
- hpa_standard_flow_status: `hpa_standard_6p5_observed`
- lift_acceptance_status: `pass`
- minimum_acceptable_cl: `1.0`
- source_polar_path: `/Volumes/Samsung SSD/hpa-mdo/output/dihedral_sweep_fixed_alpha_smoke_rerun/origin_vsp_panel_fixed_alpha_baseline/black_cat_004.polar`
- source_setup_path: `/Volumes/Samsung SSD/hpa-mdo/output/dihedral_sweep_fixed_alpha_smoke_rerun/origin_vsp_panel_fixed_alpha_baseline/black_cat_004.vspaero`

## Selected Case

- AoA: `0`
- CLtot: `1.28765`
- CDtot: `0.0450681`
- L/D: `28.5711`
- Vinf: `6.5`
- Sref: `35.175`

## SU2 Smoke Comparison

- comparison: `{"status": "available", "panel_reference_cl": 1.287645495943, "selected_su2_smoke_cl": 0.263161913, "cl_delta_panel_minus_su2": 1.024483582943, "panel_to_su2_cl_ratio": 4.892978171742504, "selected_su2_runtime_max_iterations": 80, "selected_su2_report_path": "/Volumes/Samsung SSD/hpa-mdo/hpa_meshing_package/docs/reports/main_wing_openvsp_reference_solver_smoke_probe_iter80/main_wing_real_solver_smoke_probe.v1.json", "interpretation": "panel_reference_supports_cl_gt_one_gate_current_su2_smoke_low_lift"}`

## Engineering Assessment

- This probe reads existing VSPAERO panel-mode artifacts only and does not run VSPAERO, Gmsh, or SU2.
- VSPAERO panel evidence is a lower-order aerodynamic reference, not high-fidelity CFD convergence.
- The selected panel-mode reference reports CL=1.28765 at alpha=0 deg and V=6.5 m/s.
- This supports treating CL <= 1.0 as an HPA operating-point blocker, not as an arbitrary software threshold.
- The current SU2 smoke CL is far below the panel-mode reference; that gap should be treated as route/trim/mesh/reference risk until isolated.

## Engineering Flags

- `vspaero_panel_reference_cl_gt_one`
- `su2_smoke_below_vspaero_panel_reference`

## Next Actions

- `use_vspaero_panel_reference_as_sanity_baseline_not_cfd_truth`
- `keep_main_wing_cl_gt_one_acceptance_gate_for_hpa_operating_point`
- `separate_su2_low_lift_gap_into_alpha_trim_mesh_quality_and_reference_checks`

## Limitations

- The selected VSPAERO panel artifact is lower-order aerodynamic reference evidence, not SU2 convergence evidence.
- This probe reads integrated polar coefficients and does not certify force-marker ownership for a SU2 mesh.
- A panel-vs-SU2 CL gap identifies route risk; it does not by itself identify whether alpha, trim, mesh quality, or reference geometry is the root cause.
