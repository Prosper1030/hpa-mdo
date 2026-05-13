# WO-006F SU2 Engineering Result Campaign

Verdict: `wo006f_campaign_incomplete`

## Short Read

- SU2 did not produce a final physically credible CL/CD pair for Baseline A calibration.
- Best final sign-correct run: `attempt_06`, `CL=1.289421542`, `CD=0.5555196327`, exit success but not converged and drag is far too high.
- Sanity bounds are AVL/Tier2 profile-proxy `CL=1.16853`, `CD_total=0.0260200` plus old VSPAERO panel `CL=1.28765`, `CD=0.0450681`; `attempt_06` is roughly 12-21x too draggy.
- Best transient sanity moment: `attempt_08` briefly crossed the operating CL band with positive drag, but the same run drifted to negative drag and was interrupted.
- New route evidence: `attempt_10` proves SU2 fluid-fluid multizone can launch with R6 BL/core probe files after adding `MARKER_FLUID_INTERFACE`; it is not yet force/coefficient evidence.

## Attempt Summary

| attempt_id | solver_status | classification | final_iteration | final_cl | final_cd |
|---|---|---|---|---|---|
| attempt_01_high_mesh_no_bl_inc_ns_cfl0p5 | incomplete_or_interrupted | reject_lift_below_operating_point | 119 | 0.38193 | 0.176004 |
| attempt_02_medium_no_bl_inc_ns_alpha5_zpos | incomplete_or_interrupted | reject_drag_far_above_sanity_bounds | 64 | 1.25491 | 0.525929 |
| attempt_03_medium_no_bl_inc_euler_alpha5_zpos | incomplete_or_interrupted | reject_negative_drag | 64 | 0.967744 | -0.025124 |
| attempt_04_medium_no_bl_inc_rans_sa_wallfn_alpha5_zpos | error_exit | reject_drag_far_above_sanity_bounds | 46 | 1.26694 | 0.548779 |
| attempt_05_medium_compressible_euler_alpha5 | incomplete_or_interrupted | reject_negative_drag | 11 | -4.52355 | -5.66493 |
| attempt_06_medium_no_bl_inc_rans_sa_alpha5_zpos_no_wallfn | exit_success | reject_drag_far_above_sanity_bounds | 159 | 1.28942 | 0.55552 |
| attempt_07_openvsp_gmsh_current_vsp | not_run_or_no_log | no_usable_su2_coefficients |  |  |  |
| attempt_08_medium_no_bl_inc_euler_alpha5_zpos_low_cfl | incomplete_or_interrupted | reject_negative_drag | 282 | 0.7632 | -0.153091 |
| attempt_09_openvsp_native_cfdmesh | not_run_or_no_log | no_usable_su2_coefficients |  |  |  |
| attempt_10_r6_two_zone_multizone_probe | exit_success | solver_or_mesh_probe_no_coefficients |  |  |  |

## Engineering Caveats

- No-BL tet meshes cannot provide wall-shear/profile-drag truth for this low-Re HPA wing.
- Wall-function RANS on the no-BL mesh produced y+ warnings and NaN divergence.
- OpenVSP/Gmsh alternatives are not yet robust against current thin-wing topology defects.
- R6 owned BL topology is promising, but preserved-core quality has non-positive elements and wake/span-cap coupling remains incomplete.
- A passing software test or SU2 exit code is not aerodynamic sign-off.

## Next Repair

Start from the R6 BL/core artifacts, not the no-BL coefficient loop. The highest-value path is either:

- repair preserved-core quality plus wake/span-cap coupling, then write a merged mixed-element SU2 handoff; or
- formalize the multizone route with clean BL/core zone interfaces, force-output ownership, and a core mesh that passes quality gates.
