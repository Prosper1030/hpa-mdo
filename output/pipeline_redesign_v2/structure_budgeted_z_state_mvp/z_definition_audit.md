# Z Definition Audit

Case: smooth_tier2_production_baseline.

## Current Exported Smooth Geometry

| quantity | value | source / meaning |
| --- | ---: | --- |
| aerodynamic_tip_z_m | 1.050582 | tip z_m in section_table.csv, aerodynamic exported section line |
| quarter_chord_tip_z_m | n/a | not exported as an independent field in this production package |
| root_z_reference | 0.000000 | section_table root z_m; aerodynamic geometry root reference |
| built_in_geometric_z_m | 1.050582 | aerodynamic_tip_z_m minus root_z_reference |
| total_cruise_effective_z_m | 1.050582 | exported loaded aero surface tip height relative to aerodynamic root for the current smooth geometry |
| effective_dihedral_deg | 3.502179 | atan(total_cruise_effective_z_m / semi_span) |

## Canonical Beam-Line Target Shape

| quantity | value | source / meaning |
| --- | ---: | --- |
| target_main_tip_z_m | 1.065003 | selected.target_loaded_shape.main_nodes_m tip z in canonical inverse summary |
| target_rear_tip_z_m | 1.058991 | selected.target_loaded_shape.rear_nodes_m tip z in canonical inverse summary |
| main/root beam z | 0.071439 | beam-line structural root coordinate, not the aerodynamic root reference |
| rear/root beam z | 0.065186 | beam-line structural root coordinate, not the aerodynamic root reference |
| elastic_deflection_z_m | 0.370902 | selected.equivalent_tip_deflection_m when available; beam-line recovery metric |
| target_main_effective_dihedral_deg | 3.550133 | atan(target_main_tip_z_m / semi_span); beam-line proxy only |

## Frozen Interpretation

- Canonical inverse design consumes the beam-line requested loaded shape: `target_loaded_shape.main_nodes_m` and `target_loaded_shape.rear_nodes_m`. In this MVP the sweep controls that state through `--target-shape-z-scale`, but the reported source of truth is the `selected.target_loaded_shape` object written by `scripts/direct_dual_beam_inverse_design.py`.
- The 5-7 deg HPA guideline should be compared against total cruise effective Z of the physical loaded wing/aero surface, preferably quarter-chord or the explicitly defined aerodynamic section reference. For this smooth production package the independent quarter-chord Z is not exported, so the section-table tip `z_m` is the best available aerodynamic reference.
- `target_main_tip_z_m` and `target_rear_tip_z_m` are beam-line structural quantities. They are valid control variables for inverse jig design, but they should not be treated as final aerodynamic effective dihedral unless the beam-to-aero-surface offset is explicitly mapped.
- The sweep CSV includes `effective_dihedral_deg = atan(target_main_tip_z_m / semi_span)` as an MVP beam-line proxy so the result can be compared consistently with earlier z-state work.

## Sweep Span

- lowest sampled beam-line target_main_tip_z_m: 1.804 m (6.000 deg proxy)
- highest sampled beam-line target_main_tip_z_m: 4.250 m (13.906 deg proxy)
