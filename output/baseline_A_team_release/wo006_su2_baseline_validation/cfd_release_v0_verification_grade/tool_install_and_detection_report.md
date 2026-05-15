# Tool Install And Detection Report

## Verdict

The open-source toolchain was exercised beyond the previous OpenFOAM route-smoke. OpenFOAM and Gmsh are available, cfMesh was installed successfully through a maintained OpenFOAM-compatible fork, SU2 is available, and pyHyp was attempted from source but did not become usable on this Mac/Homebrew toolchain.

This is not an installation-only deliverable: the installed tools were used in bounded mesh/solver attempts, and the blocker remained near-wall verification-grade meshing rather than simple tool absence.

## Detected Tools

| tool | status | evidence |
|---|---|---|
| OpenFOAM | available | `/opt/homebrew/bin/openfoam`, `WM_PROJECT_VERSION=v2512`, `WM_OPTIONS=darwin64ClangDPInt32Opt` |
| cfMesh / cartesianMesh | installed inside OpenFOAM env | HISA cfMesh fork commit `53fb863`; binaries available as `cartesianMesh`, `pMesh`, `surfaceToFMS`, `tetMesh` under `/Users/linyuan/OpenFOAM/linyuan-v2512/platforms/darwin64ClangDPInt32Opt/bin/` |
| Gmsh | available | `/opt/homebrew/bin/gmsh`, version `4.15.2-git` |
| SU2 | available | `/Users/linyuan/.local/opt/su2/current/bin/SU2_CFD`, help banner `SU2 v8.4.0 "Harrier"` |
| Python | available | `/Library/Frameworks/Python.framework/Versions/3.11/bin/python3`, Python `3.11.0` |
| pyHyp | not usable | source build attempted; import still fails with `ModuleNotFoundError: No module named 'pyhyp'` |

Homebrew packages observed after the route work: `cgns 4.5.2`, `gmsh 4.15.2`, `hdf5-mpi 2.1.1`, `open-mpi 5.0.9`, `petsc 3.24.6`.

## cfMesh Installation Evidence

The OpenFOAM community integration source at `/Users/linyuan/.local/src/integration-cfmesh-v2512` was tried first and failed to compile against OpenFOAM v2512. The maintained HISA fork at `/Users/linyuan/.local/src/hisa-cfmesh-v2512`, commit `53fb863`, built successfully and supplied the route-1 binaries.

## pyHyp Evidence

Official pyHyp documentation states that pyHyp requires CGNS and PETSc and follows a source-build workflow, with tagged releases recommended for stability: [pyHyp installation docs](https://mdolab-pyhyp.readthedocs-hosted.com/en/latest/install.html). The MDO Lab dependency guide lists PETSc `3.21.*`, CGNS `4.5.0`, and Python `3.11.*` in its latest tested column, and also says unsupported dependency versions leave the user essentially on their own: [MDO Lab third-party package guide](https://mdolab-mach-aero.readthedocs-hosted.com/en/latest/installInstructions/install3rdPartyPackages.html).

Bounded local attempts:

| attempt | evidence |
|---|---|
| Homebrew PETSc `3.24.6` | pyHyp build failed in PETSc Fortran interface calls: `MatSetValuesBlocked`, `PCASMGetSubKSP`, `MatCreateDense`, `MatSetValues`. Log: `toolchain_logs/pyhyp_make_homebrew_petsc_3p24.log`. |
| source PETSc `3.21.6` | configure failed because the Homebrew gcc library path on the external drive was split at the space in `/Volumes/Samsung SSD/...`, yielding linker search paths like `/Volumes/Samsung` and missing Fortran libraries. Log tail: `toolchain_logs/petsc_3p21_configure_failure_tail.log`. |

Engineering interpretation: pyHyp remains the preferred open-source style for deterministic wall-normal spacing, but it was not a usable mature route on this Mac without deeper compiler/MPI/PETSc rebuilding and a structured surface-grid input path that preserves the required split markers.
