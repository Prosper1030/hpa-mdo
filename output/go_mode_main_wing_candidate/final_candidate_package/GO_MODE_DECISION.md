# HPA Wing Go Mode Decision

## Decision

Selected engineering endpoint: `screening_closed_compromise_candidate`.

The current best production-facing review candidate is:

`current_avl_compromise_conservative_closed`

This is the candidate to send to geometry inspection and FEM/APDL spot-check. It is not a final production release, and it does not replace production ranking yet. The evidence supports one conservative, query-pass, structure-budgeted candidate for the next engineering review step, while also proving a blocker for the stricter low-Z / 6-7 deg interpretation of the current model.

## Final Recommendation

1. Promote `current_avl_compromise_conservative_closed` as the single production-facing screening candidate for manual geometry inspection and structural spot-check.
2. Do not promote it as final production truth until the spar beam-line Z proxy is mapped to the aerodynamic surface / quarter-chord geometry and the APDL/FEM spot-check clears the support, deflection, and reaction-load questions.
3. If the production requirement is strictly "6-7 deg total effective dihedral under the present beam-line contract", treat that path as blocked by the current structure and geometry model. The current contract only clears mass and ground clearance at a higher beam-line target, around 2.700 m tip Z / 8.939 deg beam-line proxy.

## Selected Candidate Metrics

| item | value |
| --- | ---: |
| assignment | `root:dae31|mid1:dae31|mid2:dae31|tip:cst_tip_nsga2_g05_child_0032_70ef8136` |
| selected role | `conservative_best` |
| query quality | `actual_loaded_shape_query_pass` |
| closure status | `closed_for_screening` |
| structure trust label | `daily_screening_not_final_truth` |
| P crank | 174.600 W |
| conservative P crank | 178.882 W |
| CL | 1.16853 |
| CDi | 0.0127613 |
| e_CDi | 0.9564 |
| profile CD | 0.00936885 |
| CD0 total | 0.01325873 |
| tube mass | 10.8736 kg |
| total structural mass | 13.3736 kg |
| jig ground clearance | 42.39 mm |
| wire tension | 3024 N |
| equivalent tip deflection | 1.543 m |
| target main tip Z | 2.700 m |
| beam-line effective dihedral proxy | 8.939 deg |

## Blocker Proven By This Loop

The 5-7 deg beam-line samples do not clear the full screening contract under the final selected-airfoil spanload:

| target | tube mass | total structural mass | clearance | blocker |
| --- | ---: | ---: | ---: | --- |
| 6.0 deg / 1.804 m | 13.982 kg | 16.482 kg | -116.2 mm | mass and clearance |
| 6.5 deg / 1.956 m | 13.982 kg | 16.482 kg | -32.5 mm | mass and clearance |
| 7.0 deg / 2.108 m | 11.926 kg | 14.426 kg | -86.8 mm | clearance |

The lowest sampled state that clears the current compromise contract is 2.700 m / 8.939 deg, with 10.874 kg tube mass and 42.4 mm clearance.

This is not a proof that a 6-7 deg real aircraft wing is impossible. It proves that, with the current beam-line Z contract and current AVL/structure coupling, the 6-7 deg states are not physically acceptable enough to promote. Recovering a lower-Z production candidate needs either a better aero-surface to beam-line mapping, a real chord/twist/load-authority redesign, or a structural architecture change.

## Aero And Airfoil Read

The conservative assignment is the only promotable airfoil result from this loop. It is query-pass, under the nominal and conservative crank-power targets, and closes aero-structure screening with zero reloop deltas after the selected-airfoil spanload loopback.

The raw assignment is rejected. It carries `actual_loaded_shape_query_warning_not_mission_grade`, has query-warning airfoil usage, and reruns to 276.104 W nominal / 281.456 W conservative. It should stay a diagnostic, not a candidate.

The Fourier-AVL bridge remains an active authority warning: the bridge report classifies the sampled calibration set as `outer_underloaded_authority_limited`. This candidate is therefore a practical compromise route, not evidence that the Fourier command space can freely realize the desired production spanload.

## Structure And FEM Read

The structure numbers are plausible enough for an HPA screening candidate but not comfortable enough for release:

- 13.37 kg total structural mass on a 34.33 m span main wing is aggressive but not absurd.
- 42 mm jig clearance is a thin margin for build tolerance, wire setup, runway surface variation, and support/joint compliance.
- 3024 N wire tension and 1.543 m equivalent tip deflection require a calibrated support and shell/beam spot-check before production confidence.
- The current Z basis is `main_beam_loaded_shape_spar_data_root_offset_removed_as_avl_section_z_proxy`, so it is still a spar beam-line proxy, not final aerodynamic-surface geometry truth.

Use FEM/APDL only as a spot-check on this candidate and the B2/B5 calibration path. Do not use FEM as a broad search loop.

## Geometry Package

Two OpenVSP/AVL inspection exports were written:

- `geometry_exports/avl_parity/current_avl_compromise_conservative_closed/`
- `geometry_exports/production_inspection/current_avl_compromise_conservative_closed/`

The AVL-parity export passes parity. The production-inspection export has an expected twist parity warning because it adds the explicit 0.18015 deg cruise incidence offset. Both write `.avl`, `.vsp3`, `.vspscript`, `section_table.csv`, `geometry_manifest.json`, and `export_report.md`.

## Required Next Engineering Step

Run this exact candidate through a focused structural trust step:

1. Confirm or regenerate the APDL B2/B5 calibration package.
2. Spot-check the selected candidate for support/wire reactions, equivalent deflection, local stress concentration, and clearance sensitivity.
3. Build the aero-surface to spar beam-line Z mapping so "6-7 deg effective dihedral" and "8.939 deg beam-line proxy" stop being mixed as if they were the same physical quantity.
4. Only after those checks should production ranking be updated.
