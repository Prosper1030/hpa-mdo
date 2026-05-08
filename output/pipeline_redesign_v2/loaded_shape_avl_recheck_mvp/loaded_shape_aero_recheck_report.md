# Loaded-Shape AVL Recheck MVP

This is a report-only MVP3 artifact. It does not change production ranking, add hard gates, rerun broad CST/NSGA, run broad FEM, or promote structure to final truth.

## Geometry Basis

- AVL section z basis: `main_beam_loaded_shape_spar_data_root_offset_removed_as_avl_section_z_proxy`.
- The Stage2 main-beam loaded-shape root Z offset is removed before AVL export; this is a beam-line proxy for aerodynamic-surface Z, not final geometry truth.
- Baseline chord, twist, airfoil files, Sref/Cref/Bref, and AVL trim CL are inherited from the pre-structure smooth Tier2 AVL artifact.

## Recheck Summary

| case | CDi pre | CDi loaded | e_CDi pre | e_CDi loaded | max Cl | Re min | stall margin min | root bending ratio |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| target_main_tip_z_4p250m | 0.012456 | 0.011998 | 0.9831 | 1.0099 | 1.294 | 291577 | -0.094 | 1.002 |

## Warning Flags

- `target_main_tip_z_4p250m`: superunit_loaded_shape_e_cdi_check_reference_convention; negative_diagnostic_stall_margin_not_gate; beam_line_z_proxy_not_aero_surface_truth

## Engineering Read

- Treat any aerodynamic deltas as screening evidence because the Z transfer uses main-beam loaded shape as a proxy for aerodynamic-surface Z.
- `e_CDi > 1` is kept as an AVL/reference-convention warning for this nonplanar loaded proxy, not as proof of a physically superior final wing.
- A negative diagnostic stall margin is a warning for MVP4 airfoil selection, not a gate in this MVP.
- The high-Z screening candidate remains structurally report-only; the recheck answers the aero consequence question, not final manufacturability.

## Required Outputs

- `loaded_shape_avl_recheck.csv`
- `loaded_shape_spanload_comparison.csv`
- `loaded_shape_local_cl_re_envelope.csv`
- `loaded_shape_aero_recheck_report.md`
