# Section C/O-Grid Algorithm

This implementation uses the allowed O-grid option rather than a wake C-grid.

1. Load true Baseline A airfoils from `/Volumes/Samsung SSD/hpa-mdo/output/go_mode_main_wing_candidate/final_candidate_package/geometry_exports/production_inspection/current_avl_compromise_conservative_closed/section_table.csv`.
2. Resample each section to `n_perim=192` with cosine LE spacing.
3. Build the local 2D grid from the airfoil wall loop to a circular farfield curve.
4. Use wall-normal first-layer offset for `first_layer_height_m=5e-5`, then blend
   outward to a section-parametric circular farfield.
5. Mark wall segments as `wing_upper`, `wing_lower`, and `te_wall`; keep tip and
   farfield patches separate in the swept 3D mesh.
6. Sweep adjacent accepted section grids into hexa cells.  This is not the old
   single global inflated-body mapping.
