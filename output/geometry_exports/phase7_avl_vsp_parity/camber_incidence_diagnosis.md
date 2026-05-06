# Camber And Incidence Diagnosis

## Findings

- `policy_A_performance_candidate`: AVL alpha_at_CL_req `4.840 deg`; VSPAERO thin/VLM alpha_at_CL_req `5.110 deg`.
- `policy_C_conservative_baseline`: AVL alpha_at_CL_req `4.423 deg`; VSPAERO thin/VLM alpha_at_CL_req `4.974 deg`.

## Interpretation

- The VSP files preserve loaded z, chord, twist, and file-airfoil assignments from the sidecar export; the original export manifests reported `file_airfoil_imported` with no airfoil import errors.
- VSPAERO thin/VLM generated thin surfaces and reported `No high lift data file found`, `StallModel = 0`, `Clo2D = 0`, and `CLMax2D = 1` in the run log. That means the sweep is not using the full-alpha/XFOIL polar database for zero-lift, stall, or profile drag.
- The nonzero alpha=0 lift in VSPAERO comes from the geometric incidence/twist/camber represented in the degenerate thin geometry. It should be treated as a VLM geometry/camber result, not as a full-polar airfoil-quality query.
- Policy A and Policy C differ slightly in AVL trim alpha because AVL directly reads the airfoil AFILE geometry. Any smaller VSPAERO A/C difference should be interpreted as a thin-geometry camber treatment difference, not as evidence that the full-polar sidecar profile drag changed.

## Answer

The observed +4 to +5 deg cruise alpha is primarily a coordinate/incidence convention issue: the exported VSP is AVL-parity body-axis geometry. It is not evidence that the sidecar geometry has the wrong mission trim.

There is also a solver-model difference: VSPAERO thin/VLM needs about `+0.27 deg` more alpha than AVL for Policy A and `+0.55 deg` more for Policy C on the un-normalized body-axis files. After AVL-calibrated cruise normalization, VSPAERO alpha=0 still under-predicts mission CL by about `0.048` for Policy A and `0.075` for Policy C. That is consistent with a VSPAERO thin-geometry/camber/reference mismatch relative to AVL AFILE behavior, not with a missing loaded-z or wrong airfoil-assignment export.

A cruise-normalized copy should add a uniform incidence offset while preserving relative twist. This does not change the aircraft ranking or sidecar policy evidence.
