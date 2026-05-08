# current_avl_compromise_conservative_closed

Diagnostic OpenVSP export from previously evaluated Phase 6/7 sidecar geometry.

**Export mode:** `avl_parity`

**Warning:** This file is for AVL/VSP parity only. Alpha=0 is not necessarily cruise. Do not use directly for production layout.

- Source AVL: `/Volumes/Samsung SSD/hpa-mdo/output/go_mode_main_wing_candidate/current_avl_compromise_conservative_closed_tier2_airfoil/runs/conservative_best/conservative_best_loaded_shape_airfoils.avl`
- Source report: `/Volumes/Samsung SSD/hpa-mdo/output/go_mode_main_wing_candidate/current_avl_compromise_conservative_closed_tier2_airfoil/tier2_loaded_shape_airfoil_report.md`
- Assignment: `root:dae31|mid1:dae31|mid2:dae31|tip:cst_tip_nsga2_g05_child_0032_70ef8136`
- Chord mode: `original_inverse_chord`
- Incidence mode: `avl_body_axis`
- VSP alpha=0 is cruise: `False`
- Chord monotonicity enforced: `False`
- Incidence offset: 0.000000000 deg (avl_body_axis_no_offset)
- Sref / Bref / Cref: 33.420059598 / 34.332286000 / 1.003721543
- Computed area / span: 33.420059598 / 34.332286000
- Loaded tip z: 2.628560870 m
- VSP status: `vsp3_written`
- VSP airfoil mode: `file_airfoil_imported`

## Parity Checks

- pass: section_count (observed=9, expected=9, delta=0.0, tol=0.0)
- pass: span_difference_m (observed=34.332286, expected=34.332286, delta=0.0, tol=1e-06)
- pass: Sref_vs_computed_area_m2 (observed=33.4200595978741, expected=33.420059598, delta=-1.2590106734933215e-10, tol=0.05)
- pass: root_chord_difference_m (observed=1.256773096, expected=1.256773096, delta=0.0, tol=1e-09)
- pass: tip_chord_difference_m (observed=0.64500409, expected=0.64500409, delta=0.0, tol=1e-09)
- pass: loaded_tip_z_difference_m (observed=2.62856087, expected=2.62856087, delta=0.0, tol=1e-09)
- pass: exported_avl_section_count (observed=9, expected=9, delta=0.0, tol=0.0)
- pass: twist_distribution_max_delta_deg (observed=0.0, expected=0.0, delta=0.0, tol=1e-09)
- pass: airfoil_assignment_match (observed=True, expected=True, delta=0.0, tol=0.0)
- pass: loaded_z_nonzero (observed=2.62856087, expected=nonzero, delta=None, tol=None)

## Section Table

- 0: eta=0.000000, y=0.000000, z=0.000000, chord=1.256773, twist=5.633710, airfoil=dae31
- 1: eta=0.160000, y=2.746583, z=0.088493, chord=1.171565, twist=5.959416, airfoil=dae31
- 2: eta=0.350000, y=6.008150, z=0.306084, chord=1.067328, twist=6.062433, airfoil=dae31
- 3: eta=0.520000, y=8.926394, z=0.643125, chord=0.970372, twist=5.670963, airfoil=dae31
- 4: eta=0.700000, y=12.016300, z=1.186643, chord=0.862164, twist=4.843813, airfoil=dae31
- 5: eta=0.820000, y=14.076237, z=1.675614, chord=0.784941, twist=4.246063, airfoil=cst_tip_nsga2_g05_child_0032_70ef8136
- 6: eta=0.900000, y=15.449529, z=2.064279, chord=0.729402, twist=3.928193, airfoil=cst_tip_nsga2_g05_child_0032_70ef8136
- 7: eta=0.950000, y=16.307836, z=2.335349, chord=0.691495, twist=3.729525, airfoil=cst_tip_nsga2_g05_child_0032_70ef8136
- 8: eta=1.000000, y=17.166143, z=2.628561, chord=0.645004, twist=3.650057, airfoil=cst_tip_nsga2_g05_child_0032_70ef8136

## Limitations

- No VSPAero or aerodynamic analysis was run.
- The source is wing-only AVL sidecar geometry, so this export is for wing manual inspection.
- If `vsp_uses_airfoil_shapes` is false in the manifest, inspect the adjacent `airfoils/*.dat` files as the airfoil source of truth.
