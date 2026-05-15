# Rerun Instructions

## Important Path Rule

OpenFOAM v2512 on this machine rejects case paths containing the space in `/Volumes/Samsung SSD/...`. Rerun OpenFOAM cases from a no-space path such as `/tmp/hpa_mdo_openfoam_phase3/...`, then copy logs/results back into this output bundle.

## Strict Snappy Evidence Cases

Example rerun for the closest rejected case:

```bash
CASE_SRC="/Volumes/Samsung SSD/hpa-mdo/output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0_verification_grade/generated_cases/snappy_absolute_wall_resolved_target"
CASE_RUN="/tmp/hpa_mdo_openfoam_phase3/generated_cases_snappy_absolute_wall_resolved_target_rerun"
rm -rf "$CASE_RUN"
rsync -a "$CASE_SRC/" "$CASE_RUN/"
/opt/homebrew/bin/openfoam -c "cd $CASE_RUN && blockMesh && surfaceFeatureExtract && snappyHexMesh -overwrite && checkMesh -meshQuality && simpleFoam && simpleFoam -postProcess -func yPlus -latestTime"
```

The other strict fallback cases are:

- `generated_cases/snappy_absolute_wall_function_target/`
- `generated_cases/snappy_absolute_intermediate_target/`
- `generated_cases/snappy_absolute_wall_resolved_target/`

## cfMesh / Gmsh Attempts

The cfMesh and Gmsh attempts under `generated_cases/` preserve their input STL/geo/log files. They are failure evidence, not accepted cases. Re-running them is useful only to reproduce the bounded route failures listed in `mesh_route_attempts_report.md`.

## Toolchain Logs

pyHyp/PETSc failure logs are stored under `toolchain_logs/`.

## Accepted Case Configs

There are no accepted verification-grade case configs in this bundle because no accepted case exists. The generated case directories are retained as bounded failure/sanity evidence.
