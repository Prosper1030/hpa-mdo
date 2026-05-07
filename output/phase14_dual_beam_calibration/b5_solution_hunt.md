# B5 Solution Hunt

## Candidate Summary

| Mode | Applied moment [N m] | Twist proxy [rad] | Main root torque [N m] | Main max |torque| [N m] | Rear max |torque| [N m] | Root torque err [%] |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| main_beam_my_about_main_spar | 40.000 | 0.001343 | 38.333700 | 38.333700 | 0.000000 | 0.000957 |
| front_rear_vertical_couple | 40.000 | -0.003145 | -0.000000 | 0.000000 | 0.000000 |  |
| cm_off_control | 0.000 | 0.001343 | -0.000000 | 0.000000 | 0.000000 |  |

## Engineering Interpretation

- The direct `main_beam_my_about_main_spar` route now has a clean observable: main-beam section torque is 38.334 N m at the root section and 38.334 N m max, versus an expected 38.333 N m from the distributed nodal `MY` loads. The root torque error is 0.001%.
- The `cm_off_control` case stays near numerical zero in section-force torque (2.470e-09 N m main, 1.276e-09 N m rear) even though the old centerline twist proxy was nonzero. That confirms the old proxy mixed in non-torsional deformation modes.
- The `front_rear_vertical_couple` case still changes the centerline twist proxy (-0.003145 rad), but its beam-axis section torque stays near zero on both beams (2.342e-09 / 6.851e-10 N m). In engineering terms, this load path is acting like a coupled bending/shear surrogate in the current linked dual-beam topology, not like the same torsional observable as direct `MY`.
- That means B5 should not be treated as one blended parity gate. Direct `MY` ownership is now observable in CalculiX via `SECTION FORCES`; the front/rear vertical-couple route should remain a separate surrogate experiment, not a truth-equivalent replacement.

## APDL Truth Decks

- `main_beam_my_about_main_spar`: `/Volumes/Samsung SSD/hpa-mdo/output/phase14_dual_beam_calibration/apdl_truth_decks/b5_main_beam_my_about_main_spar.apdl`
- `front_rear_vertical_couple`: `/Volumes/Samsung SSD/hpa-mdo/output/phase14_dual_beam_calibration/apdl_truth_decks/b5_front_rear_vertical_couple.apdl`
- `cm_off_control`: `/Volumes/Samsung SSD/hpa-mdo/output/phase14_dual_beam_calibration/apdl_truth_decks/b5_cm_off_control.apdl`

## Verdict

B5 is no longer blocked by lack of a CalculiX torque observable. The real remaining question is policy: direct `MY` can be checked through section forces, but the vertical-couple surrogate should not be promoted to the same truth status without external confirmation.
