# Phase 14 Mac-local FEM + APDL Windows Package Summary

Validation tooling only. This route does not change aerodynamic ranking, hard gates, dual_beam_production physics, or calibration factors.

## B2 Shell FEM Convergence

| Mesh | Elements | Tip UZ [m] | Root RFZ [N] | Max VM [Pa] | Conv to fine [%] |
| --- | ---: | ---: | ---: | ---: | ---: |
| b2_shell_coarse | 6144 | -5.742950e-02 | 7.999998e+01 | 2.117640e+07 | 5.889584e+01 |
| b2_shell_medium | 24576 | -1.138100e-01 | 7.999994e+01 | 3.731698e+08 | 1.854248e+01 |
| b2_shell_fine | 55296 | -1.397170e-01 | 7.999998e+01 | 2.338997e+08 | 0.000000e+00 |

## B2 Comparison

- Fine shell FEM is closer to `calculix_b32r_pipe` (shell-vs-internal 22.268%, shell-vs-B32R 12.921%).
- This is a directionally useful sanity comparison, but not an agreement-quality shell validation yet.

## B5 Torsion

| Route | Theta FEM [rad] | Theta theory [rad] | Theta err [%] | Root section torque [N m] | Torque err [%] |
| --- | ---: | ---: | ---: | ---: | ---: |
| shell_fem_tip_torque | 1.083339e-02 | 4.679201e-02 | 7.684779e+01 |  |  |
| calculix_b32r_pipe_section_forces |  | 4.679201e-02 |  | 9.999940e+01 | 6.000000e-04 |

## Engineering Interpretation

- B5 shell torsion theta is 1.083339e-02 rad versus 4.679201e-02 rad from T L / GJ.
- B5 B32R PIPE section-force torque is 9.999940e+01 N m for a 100.000 N m applied torque.
- The simplified dual-beam vertical force couple has the same external moment as direct MY, but it remains a load-path surrogate because it introduces bending/shear coupling in the linked dual-beam topology.

## APDL Windows Package

- Package directory: `/Volumes/Samsung SSD/hpa-mdo/output/phase14_dual_beam_calibration/apdl_windows_package`
- Copy the entire `apdl_windows_package` folder to Windows.
- Run `run_all_phase14.mac` from ANSYS Mechanical APDL and send back `phase14_apdl_results.csv`.
