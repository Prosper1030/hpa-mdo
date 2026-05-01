# Mesh-Native Black Cat Pipeline Validation v1

Date: 2026-05-01

## Objective

Check the current mesh-native Black Cat main-wing route end to end:

```text
AVL geometry input
  -> automatic wing extents and feature boxes
  -> Gmsh size field
  -> coarse/medium/fine SU2 runs
  -> CL/CD/CMy stability selection
  -> million-cell mesh feasibility
```

This report intentionally does not use VSP/ESP STEP/BREP repair.

## Verdict

Mesh route: **pass for geometry, Gmsh volume meshing, marker ownership, SU2 handoff, and 1M-class mesh generation.**

CFD route: **not yet valid for aerodynamic design decisions.**

The pipeline can run SU2 automatically, but the current aerodynamic evidence is not acceptable yet:

- the 20-iteration coarse/medium/fine ladder completed, but all cases failed the iterative convergence gate;
- a 100-iteration `h=0.09` run still failed CD/CMy tail stability and ended with negative CD;
- a JST/CFL probe converged numerically, but also converged to negative CD.

Negative drag on a passive wing is not an acceptable engineering result. Treat it as a force-sign, surface-orientation, solver-setup, or volume-quality diagnostic, not as a valid CFD answer.

## Artifacts

- Combined summary JSON: `mesh_native_blackcat_pipeline_validation.v1.json`
- 20-iteration SU2 ladder:
  `../mesh_native_blackcat_su2_stability_ladder/artifacts/run_20260501_135240/su2_stability_ladder_report.json`
- 100-iteration FDS probe:
  `../mesh_native_blackcat_su2_iteration_probe/artifacts/run_20260501_135400_h009_100iter/su2_stability_ladder_report.json`
- 1M mesh probe:
  `../mesh_native_blackcat_million_mesh_probe/artifacts/run_20260501_140000/coupled_refinement_ladder_report.json`
- JST setup probe:
  `../mesh_native_blackcat_su2_solver_setup_probe/artifacts/jst_cfl100_h009_300iter/`

Large raw mesh, history, log, and solution outputs were removed from the
evidence packet: `.msh`, `.su2`, `history.csv`, `solver.log`, `restart.csv`,
`surface.csv`, and `vol_solution.vtk`.

## SU2 Stability Ladder

Settings:

- `points_per_side = 16`
- `spanwise_subdivisions = 4`
- `feature_refinement_size = 3.0`
- `farfield_mesh_size = 18.0`
- `wing_refinement_radius = 12.0`
- `solver = INC_EULER`
- `iterations = 20`
- `threads = 4`

| h | nodes | tets | quality | iterative gate | CL | CD | CMy |
| -: | -: | -: | :- | :- | -: | -: | -: |
| 0.09 | 35,993 | 107,415 | pass | fail | 0.450608 | 0.091526 | -0.168098 |
| 0.075 | 41,727 | 125,288 | pass, `very_low_min_gamma` | fail | 0.460158 | 0.116098 | -0.180429 |
| 0.06 | 58,829 | 175,019 | pass, `very_low_min_gamma` | fail | 0.440872 | 0.138970 | -0.193797 |

Selection result: `no_stable_mesh`.

All three cases were excluded because `iterative_gate_status = fail`. This is the correct behavior: final coefficients are not allowed to drive mesh selection when the solver is still drifting.

## Iteration Probe

The clean `h=0.09` mesh was rerun for 100 iterations with the existing smoke settings:

- scheme: `FDS`
- CFL: `1.0`
- iterations: `100`
- tets: `107,415`

Final coefficients:

| CL | CD | CMy |
| -: | -: | -: |
| 0.691833 | -0.043595 | 0.034640 |

Gate result: `fail`.

CL tail passed, but CD and CMy were still drifting. The negative CD is also physically suspicious.

## JST Probe

A source-guided solver setup probe reused the same `h=0.09` mesh with:

- scheme: `JST`
- `JST_SENSOR_COEFF = (0.0, 0.02)`
- CFL: `100`
- linear solver error: `1e-12`
- linear solver iterations: `25`
- Cauchy CD epsilon: `1e-6`

SU2 reported convergence at iteration `70`, with `Cauchy[CD] = 7.45569e-7`.

Final coefficients:

| CL | CD | CMy |
| -: | -: | -: |
| 0.696225 | -0.148031 | 0.137433 |

This proves the solver can be made numerically stable on the mesh, but it does not validate the physics. The converged negative CD is a blocking diagnostic.

## Orientation Probe

A temporary all-wing-face reversal probe was run on the same `h=0.09` setup.
It also passed the iterative gate, but still converged to negative CD:

| CL | CD | CMy |
| -: | -: | -: |
| 0.688007 | -0.145600 | 0.139576 |

This suggests the negative drag is not fixed by simply reversing every generated wing face. The next diagnostic should look at force convention, surface-force breakdown, Kutta/trailing-edge behavior, and solver control-volume quality rather than assuming a one-line normal flip.

## Million-Cell Mesh Probe

Pure mesh generation was run without SU2 on the high-density ladder:

| h | nodes | tets | production scale | quality |
| -: | -: | -: | :- | :- |
| 0.025 | 210,476 | 615,453 | under target | pass |
| 0.020 | 305,868 | 883,182 | under target | pass, `very_low_min_gamma` |
| 0.018 | 367,629 | 1,063,040 | meets target | pass |

Selected mesh candidate:

- `h = 0.018`
- `1,063,040` tetrahedra
- `367,629` nodes
- `min_gamma = 1.972e-4`
- `p01_gamma = 0.08780`
- `min_sicn = 0.002039`
- `p01_sicn = 0.08525`
- Gmsh runtime: `297.71 s`
- peak memory: about `1.92 GB`

This is the current best evidence that the mesh-native route can reach the million-cell credibility class without STEP/BREP.

## Engineering Assessment

What is valid now:

- geometry input to indexed wing surface works;
- automatic feature extents and Gmsh size fields work;
- Gmsh can generate 100k-class SU2 meshes and 1M-class pure meshes;
- SU2 reads the generated mesh and runs;
- marker ownership is preserved as `wing_wall` and `farfield`;
- automatic mesh selection now refuses unconverged cases.

What is not valid yet:

- no converged, physically credible SU2 aero result exists;
- no cheapest stable CFD mesh can be selected yet;
- negative CD blocks aerodynamic interpretation;
- solver dual-control-volume quality warnings suggest local topology/quality hotspots still matter.

Recommended next actions:

1. Add a source-controlled SU2 numerics profile instead of hardcoded smoke settings.
2. Audit force-sign convention and surface-force breakdown; all-wing face reversal did not remove negative CD.
3. Investigate dual-control-volume quality hotspots before spending longer high-density SU2 runs.
4. Only run medium/fine SU2 stability after one clean mesh gives nonnegative, converged coefficients.

## Source Notes

- SU2 incompressible setup conventions were checked against the official SU2 physical-definition documentation.
- The JST probe was based on SU2's official incompressible inviscid hydrofoil tutorial configuration style.
