# Baseline A Data-Authority Audit

Verdict: `baseline_A_release_claims_unreliable` until authority repair is complete.

- Files scanned: `6540`
- Claims extracted: `53148`
- Blocking current-channel violations after repair: `0`
- Skipped paths recorded: `2467`

## Authority Class Counts

- `conflict_blocked`: 43
- `current_pipeline_truth`: 232
- `generated_output`: 11374
- `legacy_or_experiment`: 25198
- `screening_estimate`: 3994
- `unknown`: 12197
- `user_authority`: 110

## Governing Authority Table

| ID | Topic | Number | Class | Allowed use | Disallowed use | Procurement |
|---|---|---:|---|---|---|---|
| `design_gross_mass_98p5` | mass / CG / rebalance | 98.5 kg | `user_authority` | Current design gross mass standard until the user explicitly changes it. | Do not overwrite with P1 aggregate, release ledger sum, vendor response, or generated output. | yes, but only as design standard input, not measured order mass |
| `p1_screening_mass_106p828608` | mass / CG / rebalance | 106.828608 kg | `screening_estimate` | May appear as suspect P1 screening aggregate evidence. | Must not be current design gross mass, mission mass, RFQ truth, or release truth. | no |
| `pipeline_full_span_34p332286` | span / half-span / station / rib spacing | 34.332286 m | `current_pipeline_truth` | Current pipeline full-span evidence unless superseded by newer authority. | Do not round or replace with local splice data for procurement. | not alone; procurement needs repaired station/span manifest |
| `pipeline_half_span_17p166143` | span / half-span / station / rib spacing | 17.166143 m | `current_pipeline_truth` | Current pipeline half-span evidence unless superseded by newer authority. | Do not replace with 16.5 m for RFQ/shop/procurement truth. | not alone; procurement needs repaired station/span manifest |
| `local_splice_half_span_16p5` | span / half-span / station / rib spacing | 16.5 m | `screening_estimate` | May appear as local/splice screening reference. | Must not be current pipeline half-span, RFQ control span, shop span, or procurement truth. | no |
| `wo003_stage0_power_warning_minus9` | drag / power / mission margin | -9 W | `screening_estimate` | Power-budget watch item only. | Must not be latest full-pipeline mission verdict or release fail/pass. | no |
| `p1_c04_original_peel_margin` | structure margin / C04 / coupon FEM | -0.893 margin | `screening_estimate` | Fail evidence for original eccentric peel path. | Must not be hidden by installed-fix readiness language. | no |
| `p1_c04_installed_fix_margin` | structure margin / C04 / coupon FEM | 0.8876 margin | `screening_estimate` | May support coupon/local FEM readiness only. | Must not be final aircraft, adhesive, laminate, buckling, or hardware sign-off. | no |
| `wo005_rfq_pack` | spar / splice / RFQ / procurement | WO-005 verdict | `conflict_blocked` | Draft/vendor-screening only after wording repair. | Must not be purchase-ready, supplier selection, shop drawing release, or procurement truth. | no |

## Top Blocking Conflicts

- `C-001` mass / CG / rebalance: 98.5 kg is current design mass authority; 106.828608 kg is a suspect P1 screening aggregate and cannot drive current design mass, mission, CG, or RFQ truth.
- `C-002` span / half-span / station / rib spacing: Current pipeline evidence is 34.332286 m full span / 17.166143 m half-span; 16.5 m is local structural/splice screening only.
- `C-003` spar / splice / RFQ / procurement: WO-005 RFQ artifacts were built from screening/local span and generated outputs. They are vendor-screening only, not purchase-ready.
- `C-004` drag / power / mission margin: WO-003 -9 W is only Stage-0 quick-screen warning, not latest full-pipeline mission truth.
- `C-005` structure margin / C04 / coupon FEM: P1/C04 evidence is coupon/local FEM readiness. It is not adhesive, laminate, buckling, hardware, or aircraft sign-off.
- `C-006` tail / trim / stability / control: Tail/CG/trim/stability claims remain screening assumptions, not measured CG, tail hardware, actuator, or flight-dynamics sign-off.
- `C-007` propulsion lane contamination: QPROP/XROTOR must not pass or fail C04/rib/structural blockers.
- `C-008` verdict / sign-off overclaim: Release, ready, pass, RFQ, and FEM-readiness verdicts were too easy to read as current truth or final aircraft sign-off.
- `C-009` tests that preserve stale constants: Some tests asserted stale constants as expected truth instead of checking authority classification.
- `C-010` scripts that read old generated outputs as truth: Release/RFQ scripts read generated P1/splice/manufacturing outputs as if they were release authority.

## Scan Boundaries
Skipped paths were recorded because they were binary, cache/vendor/venv/git internals, or too large for safe text scan:
- `docs/.DS_Store`: non_text_or_binary
- `docs/research/.DS_Store`: non_text_or_binary
- `docs/research/xfoil_fx76mp140_re410000/cl_vs_cd.png`: non_text_or_binary
- `docs/research/xfoil_fx76mp140_re410000/cd_vs_alpha.png`: non_text_or_binary
- `docs/research/xfoil_fx76mp140_re410000/cl_vs_alpha.png`: non_text_or_binary
- `docs/research/xfoil_fx76mp140_re410000/run_xfoil.in`: non_text_or_binary
- `docs/research/xfoil_fx76mp140_re410000/fx76mp140_re410000.polar`: non_text_or_binary
- `docs/research/xfoil_fx76mp140_re410000/clcd_vs_alpha.png`: non_text_or_binary
- `docs/research/seedless_selection_behavior/production-probe_root_clean_vs_rough_cd.png`: non_text_or_binary
- `docs/research/seedless_selection_behavior/production-probe_root_cm_vs_cl.png`: non_text_or_binary
- `docs/research/seedless_selection_behavior/production-probe_tip_cd_vs_cl.png`: non_text_or_binary
- `docs/research/seedless_selection_behavior/smoke_mid1_cm_vs_cl.png`: non_text_or_binary
- `docs/research/seedless_selection_behavior/production-probe_tc_camber_summary.png`: non_text_or_binary
- `docs/research/seedless_selection_behavior/smoke_tip_clean_vs_rough_cd.png`: non_text_or_binary
- `docs/research/seedless_selection_behavior/smoke_root_clean_vs_rough_cd.png`: non_text_or_binary
- `docs/research/seedless_selection_behavior/smoke_mid2_clean_vs_rough_cd.png`: non_text_or_binary
- `docs/research/seedless_selection_behavior/production-probe_tip_clean_vs_rough_cd.png`: non_text_or_binary
- `docs/research/seedless_selection_behavior/smoke_root_cm_vs_cl.png`: non_text_or_binary
- `docs/research/seedless_selection_behavior/production-probe_tip_shape_overlay.png`: non_text_or_binary
- `docs/research/seedless_selection_behavior/smoke_mid2_cd_vs_cl.png`: non_text_or_binary
- `docs/research/seedless_selection_behavior/smoke_tip_cd_vs_cl.png`: non_text_or_binary
- `docs/research/seedless_selection_behavior/smoke_tc_camber_summary.png`: non_text_or_binary
- `docs/research/seedless_selection_behavior/smoke_mid1_shape_overlay.png`: non_text_or_binary
- `docs/research/seedless_selection_behavior/production-probe_root_shape_overlay.png`: non_text_or_binary
- `docs/research/seedless_selection_behavior/smoke_mid1_cd_vs_cl.png`: non_text_or_binary
- `docs/research/seedless_selection_behavior/production-probe_tip_cm_vs_cl.png`: non_text_or_binary
- `docs/research/seedless_selection_behavior/production-probe_root_cd_vs_cl.png`: non_text_or_binary
- `docs/research/seedless_selection_behavior/smoke_tip_cm_vs_cl.png`: non_text_or_binary
- `docs/research/seedless_selection_behavior/smoke_root_shape_overlay.png`: non_text_or_binary
- `docs/research/seedless_selection_behavior/smoke_tip_shape_overlay.png`: non_text_or_binary
- `docs/research/seedless_selection_behavior/smoke_mid2_cm_vs_cl.png`: non_text_or_binary
- `docs/research/seedless_selection_behavior/smoke_root_cd_vs_cl.png`: non_text_or_binary
- `docs/research/seedless_selection_behavior/smoke_mid1_clean_vs_rough_cd.png`: non_text_or_binary
- `docs/research/seedless_selection_behavior/smoke_mid2_shape_overlay.png`: non_text_or_binary
- `docs/Paper/drela-2012-low-reynolds-number-airfoil-design-for-the-m-i-t-daedalus-prototype-a-case-study.pdf`: non_text_or_binary
- `docs/Paper/hpa_structure.pdf`: non_text_or_binary
- `docs/Paper/Flight Test Results for the Daedalus and Light Eagle Human Powered Aircraft.pdf`: non_text_or_binary
- `docs/可能的廠商資訊/台灣碳纖維管製造商型號與規格深度調查報告.pdf`: non_text_or_binary
- `docs/可能的廠商資訊/台灣HPA用碳纖維管供應商與適配性分析報告.pdf`: non_text_or_binary
- `docs/Manual/ccx_2.22.pdf`: non_text_or_binary
- `docs/Manual/.DS_Store`: non_text_or_binary
- `docs/Manual/gmsh.pdf`: non_text_or_binary
- `docs/Manual/ASWING_Extended_User_Manual.pdf`: non_text_or_binary
- `docs/Manual/su2_wiki_minimal/.DS_Store`: non_text_or_binary
- `docs/Manual/su2_wiki_minimal/_includes/gsoc_section_nav.html`: non_text_or_binary
- `docs/Manual/su2_wiki_minimal/_includes/docs_v7_nav.html`: non_text_or_binary
- `docs/Manual/su2_wiki_minimal/_includes/js_files.html`: non_text_or_binary
- `docs/Manual/su2_wiki_minimal/_includes/gsoc_nav.html`: non_text_or_binary
- `docs/Manual/su2_wiki_minimal/_includes/section_nav.html`: non_text_or_binary
- `docs/Manual/su2_wiki_minimal/_includes/consent.html`: non_text_or_binary
- `docs/Manual/su2_wiki_minimal/_includes/tutorials_section_nav.html`: non_text_or_binary
- `docs/Manual/su2_wiki_minimal/_includes/topnav.html`: non_text_or_binary
- `docs/Manual/su2_wiki_minimal/_includes/vandv_nav.html`: non_text_or_binary
- `docs/Manual/su2_wiki_minimal/_includes/vandv_section_nav.html`: non_text_or_binary
- `docs/Manual/su2_wiki_minimal/_includes/tutorials_nav.html`: non_text_or_binary
- `docs/Manual/su2_wiki_minimal/_includes/ga.js`: non_text_or_binary
- `docs/Manual/su2_wiki_minimal/_includes/head.html`: non_text_or_binary
- `docs/Manual/su2_wiki_minimal/_includes/su2gui_section_nav.html`: non_text_or_binary
- `docs/Manual/su2_wiki_minimal/_includes/footer.html`: non_text_or_binary
- `docs/Manual/su2_wiki_minimal/_includes/su2gui_nav.html`: non_text_or_binary
- `docs/Manual/su2_wiki_minimal/_includes/docs_nav.html`: non_text_or_binary
- `docs/Manual/su2_wiki_minimal/_includes/section_docs_v7_nav.html`: non_text_or_binary
- `docs/Manual/su2_wiki_minimal/css/main.scss`: non_text_or_binary
- `docs/Manual/su2_wiki_minimal/css/font-awesome.min.css`: non_text_or_binary
- `docs/Manual/su2_wiki_minimal/docs_files/square.su2`: non_text_or_binary
- `docs/Manual/su2_wiki_minimal/docs_files/LW_example.png`: non_text_or_binary
- `docs/Manual/su2_wiki_minimal/docs_files/zones.png`: non_text_or_binary
- `docs/Manual/su2_wiki_minimal/docs_files/NACA0012_coef_pres.png`: non_text_or_binary
- `docs/Manual/su2_wiki_minimal/docs_files/square.cpp`: non_text_or_binary
- `docs/Manual/su2_wiki_minimal/docs_files/NACA0012_surf_sens.png`: non_text_or_binary
- `docs/Manual/su2_wiki_minimal/docs_files/pr_develop_branch.png`: non_text_or_binary
- `docs/Manual/su2_wiki_minimal/docs_files/square.f90`: non_text_or_binary
- `docs/Manual/su2_wiki_minimal/docs_files/advection_example.png`: non_text_or_binary
- `docs/Manual/su2_wiki_minimal/docs_files/naca0012_pressure.png`: non_text_or_binary
- `docs/Manual/su2_wiki_minimal/docs_files/logoSU2_v3_3.png`: non_text_or_binary
- `docs/Manual/su2_wiki_minimal/docs_files/windows_quick_start_04.png`: non_text_or_binary
- `docs/Manual/su2_wiki_minimal/docs_files/pr_create_branch.png`: non_text_or_binary
- `docs/Manual/su2_wiki_minimal/docs_files/windows_quick_start_05.png`: non_text_or_binary
- `docs/Manual/su2_wiki_minimal/docs_files/NACA0012_mach_field.png`: non_text_or_binary
- `docs/Manual/su2_wiki_minimal/docs_files/windows_quick_start_06.png`: non_text_or_binary
- `docs/Manual/su2_wiki_minimal/docs_files/Class_Structure_Geometry.png`: non_text_or_binary
- `docs/Manual/su2_wiki_minimal/docs_files/windows_quick_start_02.png`: non_text_or_binary
- `docs/Manual/su2_wiki_minimal/docs_files/Class_Structure_Numerics.png`: non_text_or_binary
- `docs/Manual/su2_wiki_minimal/docs_files/class_c_driver__coll__graph.png`: non_text_or_binary
- `docs/Manual/su2_wiki_minimal/docs_files/SU2_Color_NoBackground.png`: non_text_or_binary
- `docs/Manual/su2_wiki_minimal/docs_files/class_c_variable__inherit__graph.png`: non_text_or_binary
- `docs/Manual/su2_wiki_minimal/docs_files/windows_quick_start_03.png`: non_text_or_binary
- `docs/Manual/su2_wiki_minimal/docs_files/class_c_solver__inherit__graph.png`: non_text_or_binary
- `docs/Manual/su2_wiki_minimal/docs_files/windows_quick_start_01.png`: non_text_or_binary
- `docs/Manual/su2_wiki_minimal/docs_files/TV_example.png`: non_text_or_binary
- `docs/Manual/su2_wiki_minimal/docs_files/NACA0012_pressure_field.png`: non_text_or_binary
- `docs/Manual/su2_wiki_minimal/docs_files/naca0012_mesh.png`: non_text_or_binary
- `docs/Manual/su2_wiki_minimal/docs_files/windows_system_variable_03.png`: non_text_or_binary
- `docs/Manual/su2_wiki_minimal/docs_files/naca0012_sensitivity.png`: non_text_or_binary
- `docs/Manual/su2_wiki_minimal/docs_files/windows_system_variable_02.png`: non_text_or_binary
- `docs/Manual/su2_wiki_minimal/docs_files/naca0012_psirho.png`: non_text_or_binary
- `docs/Manual/su2_wiki_minimal/docs_files/logoSU2_v3.3.jpg`: non_text_or_binary
- `docs/Manual/su2_wiki_minimal/docs_files/windows_system_variable_01.png`: non_text_or_binary
- `docs/Manual/su2_wiki_minimal/docs_files/windows_system_variable_05.png`: non_text_or_binary
- `docs/Manual/su2_wiki_minimal/docs_files/square.png`: non_text_or_binary
- plus `2367` additional skipped paths in the JSON inventory metadata
