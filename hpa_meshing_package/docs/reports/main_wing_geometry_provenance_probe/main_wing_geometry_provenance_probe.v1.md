# Main Wing Geometry Provenance Probe v1

This report reads OpenVSP geometry provenance only; it does not execute Gmsh or SU2.

- geometry_provenance_status: `provenance_available`
- source_path: `/Volumes/Samsung SSD/hpa-mdo/data/blackcat_004_origin.vsp3`
- selected_geom_name: `Main Wing`
- selected_geom_id: `IPAWXFWPQF`
- installation_incidence_deg: `3`
- section_count: `6`
- alpha_zero_interpretation: `alpha_zero_expected_positive_lift_but_not_acceptance_lift`

## Summaries

- twist_summary: `{"status": "available", "min_twist_deg": 0.0, "max_twist_deg": 0.0, "all_sections_zero_twist": true}`
- airfoil_summary: `{"unique_airfoil_names": ["CLARK-Y 11.7% smoothed", "FX 76-MP-140"], "cambered_airfoil_coordinates_observed": true, "max_abs_camber_over_chord": 0.07121500198263675, "max_thickness_over_chord": 0.14107999438419938}`

## Sections

| index | span | root_chord | tip_chord | twist | dihedral | sweep | airfoil | max_camber | max_thickness |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 1 | 1 | 1.3 | 0 | 0 | 0 | FX 76-MP-140 | 0.071215 | 0.14108 |
| 1 | 4.5 | 1.3 | 1.3 | 0 | 1 | 0 | FX 76-MP-140 | 0.071215 | 0.14108 |
| 2 | 3 | 1.3 | 1.175 | 0 | 2 | 0 | FX 76-MP-140 | 0.071215 | 0.14108 |
| 3 | 3 | 1.175 | 1.04 | 0 | 3 | 0.76 | FX 76-MP-140 | 0.071215 | 0.14108 |
| 4 | 3 | 1.04 | 0.83 | 0 | 4 | 0.95 | FX 76-MP-140 | 0.071215 | 0.14108 |
| 5 | 3 | 0.83 | 0.435 | 0 | 5 | 1.91 | CLARK-Y 11.7% smoothed | 0.03555 | 0.11724 |

## Engineering Assessment

- This probe reads OpenVSP geometry provenance only and does not execute Gmsh or SU2.
- Main Wing has Y_Rotation=3 deg, so SU2 alpha=0 freestream is not necessarily a zero-lift geometry point.
- All parsed main-wing sections report zero local twist; the alpha-zero lift source is incidence and airfoil camber, not spanwise twist washout.
- Embedded airfoil coordinates are cambered, supporting a positive alpha-zero CL reading.
- A positive CL around the current smoke value can be physically plausible, but CL below 1 remains an operational lift-acceptance blocker at V=6.5 m/s.

## Next Actions

- `treat_alpha_zero_solver_smoke_as_geometry_incidence_point_not_trim_validation`
- `run_alpha_trim_sanity_probe_only_after_solver_validation_policy_is_respected`
- `keep_cl_gt_one_acceptance_gate_for_convergence_claims`

## Limitations

- This probe reads VSP3 XML and embedded airfoil coordinates; it does not certify aerodynamic performance.
- OpenVSP incidence/twist/camber provenance explains why alpha=0 may have positive lift, not whether the current SU2 run is converged.
