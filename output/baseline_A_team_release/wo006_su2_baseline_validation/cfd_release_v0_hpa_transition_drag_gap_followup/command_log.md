# WO-006 Transition/Turbulence Drag-Gap Follow-up Command Log

Working note: OpenFOAM runs were launched from `/tmp` because the wrapper rejects the space-containing repository path.

1. `pgrep -fl 'simpleFoam|postProcess|checkMesh|gmsh' || true`
2. Read committed transition case fields and dictionaries: `2000/{k,omega,gammaInt,ReThetat,nut}`, `system/{fvSolution,fvSchemes,controlDict}`, `constant/turbulenceProperties`.
3. Read native OpenFOAM tutorial pattern: `/Volumes/OpenFOAM-v2512/tutorials/incompressible/simpleFoam/T3A/0.orig/{k,omega,gammaInt,ReThetat,nut}` and `system/{fvSolution,fvSchemes}`.
4. Generated four temporary probe cases under `/tmp/hpa_lm_gap_attempts` by symlinking the existing Fine `polyMesh`, `U`, `p`, and `phi`, and copying/editing only turbulence fields and solver dictionaries.
5. `openfoam -c 'simpleFoam -case /tmp/hpa_lm_gap_attempts/LM_L0p007c_relaxed'`
6. `openfoam -c 'simpleFoam -case /tmp/hpa_lm_gap_attempts/LM_L0p001c_relaxed'`
7. `openfoam -c 'simpleFoam -case /tmp/hpa_lm_gap_attempts/LM_L0p001c_tutorialBC'`
8. `openfoam -c 'simpleFoam -case /tmp/hpa_lm_gap_attempts/SST_L0p001c_warmstart'`
9. Extended best LM probe: edited endTime to 2020, then `openfoam -c 'simpleFoam -case /tmp/hpa_lm_gap_attempts/LM_L0p001c_relaxed'`.
10. `openfoam -c 'postProcess -case /tmp/hpa_lm_gap_attempts/LM_L0p001c_relaxed -latestTime -funcs "(fieldMinMax(gammaInt) fieldMinMax(ReThetat) fieldMinMax(nut))"'`
11. Queried existing Tier2 full-alpha airfoil database for representative root/mid/outboard clean and rough section cd values.
12. Read existing invalid 2D OpenFOAM section `checkMesh` logs under `cfd_release_v0_swept_cgrid_structured_hexa_smoke/openfoam_cases`.
