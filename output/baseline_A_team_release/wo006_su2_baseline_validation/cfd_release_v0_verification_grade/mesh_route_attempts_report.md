# Mesh Route Attempts Report

| route | attempt | case/evidence | changed parameters | failure class | failure mode |
| --- | --- | --- | --- | --- | --- |
| cfMesh/cartesianMesh | 1 | `cfmesh_attempt_01_wall_function_coarse` | cartesianMesh coarse wall-function intent; regex patch selection failed; no usable intended BL | mesh_quality | checkMesh failed: 10,049,350 cells, failed 2 checks, 1329 meshQualityFaces; farfield/patch setup also not clean |
| cfMesh/cartesianMesh | 2 | `cfmesh_attempt_02_exact_patch_wall_function` | exact split patch names; 12 boundary layers; farfield corrected | mesh_quality | checkMesh failed 6 checks; 7,787,391 cells; zero/negative volume cells and extreme aspect ratio around layer stack |
| cfMesh/cartesianMesh | 3 | `cfmesh_attempt_03_low_layer_wall_function` | 3 layers and coarser surface/core controls | mesh_quality | checkMesh failed 4 checks; 1,436,232 cells; wrong-oriented faces plus non-orthogonality/skewness/determinant errors |
| cfMesh/cartesianMesh | 4 | `cfmesh_attempt_04_optimised_low_layer_wall_function` | low-layer case plus cfMesh layer optimisation/smoothing controls | mesh_quality | checkMesh failed 3 checks; 1,282,289 cells; 5862 meshQualityFaces and one wrong-oriented face |
| cfMesh/cartesianMesh | 5 | `cfmesh_attempt_05_no_layer_core_quality_probe` | no boundary layers to isolate core/surface quality | mesh_quality | checkMesh failed 2 checks; 722,697 cells; 547 meshQualityFaces even without layers |
| cfMesh/pMesh | 6 | `cfmesh_attempt_06_pmesh_optimised_low_layer_wall_function` | pMesh instead of cartesianMesh with optimised low-layer setup | mesh_tool_failure | pMesh fatal exit 134 after inverted boundary faces; table lookup fatal error during topological adjustment |
| pyHyp/body-fitted hyperbolic | 1 | `pyhyp_make_homebrew_petsc_3p24` | local pyHyp v2.6.3 source build against Homebrew PETSc 3.24.6 and CGNS 4.5.2 | toolchain_install | Fortran build fails in PETSc calls MatSetValuesBlocked, PCASMGetSubKSP, MatCreateDense, and MatSetValues; log saved in toolchain_logs |
| pyHyp/body-fitted hyperbolic | 2 | `petsc_3p21_source_configure` | source PETSc 3.21.6, matching MDO Lab tested/latest line, local prefix, no sudo | toolchain_install | PETSc configure cannot link Fortran libraries with C linker because Homebrew gcc libraries resolve through the external-drive path containing a space; log tail saved in toolchain_logs |
| Gmsh CAD-first | 1 | `gmsh_attempt_01_step_surface_loop_volume` | STEP import, surface loop, farfield volume, HXT 3D | cad_surface_mesh | self-intersecting facets; constrained-line/triangle recovery failed; no volume elements |
| Gmsh CAD-first | 2 | `gmsh_attempt_02_step_surface_loop_delaunay` | same STEP surface loop with Delaunay/Netgen-style 3D controls | cad_surface_mesh | invalid boundary mesh with overlapping facets between surfaces 57 and 58; no volume elements |
| Gmsh surface-based mature route | 3 | `gmsh_attempt_03_surface_based_current_stl_core` | current generated meter-scale split-patch STL; ClassifySurfaces/CreateGeometry; surface loop | surface_mesh | 3D meshing failed from overlapping facets after classification; no usable core mesh |
| strict snappy absolute-layer fallback | 1 | `snappy_absolute_wall_function_target` | relativeSizes false; firstLayerThickness 0.0025 m; 6 layers; expansion 1.25 | near_wall_yplus | solver ran, checkMesh acceptable as smoke, but yPlus mean/p95/max far above wall-function acceptance and layer coverage collapsed below target |
| strict snappy absolute-layer fallback | 2 | `snappy_absolute_intermediate_target` | relativeSizes false; firstLayerThickness 0.0005 m; 12 layers; expansion 1.20 | mesh_quality_and_yplus | checkMesh rejected with custom mesh-quality error; yPlus still high; solver run is not acceptable CFD evidence |
| strict snappy absolute-layer fallback | 3 | `snappy_absolute_wall_resolved_target` | relativeSizes false; firstLayerThickness 0.0001 m; 30 layers; expansion 1.15 | near_wall_yplus | force history finite and stable-ish, checkMesh smoke-clean, but actual layer coverage is under two layers average and yPlus remains high |

## Route-Level Decision

- Route 1, cfMesh/cartesianMesh/pMesh: bounded at six attempts. It was installable, but could not produce a clean core/layer mesh for the fixed split-patch wing.
- Route 2, pyHyp/body-fitted: bounded at two installation/toolchain attempts. It did not become usable on this Mac/Homebrew PETSc/MPI/Fortran stack.
- Route 3, Gmsh CAD-first/surface route: bounded at three attempts. STEP and current STL paths both failed before clean BL/core generation because the boundary surfaces were overlapping or self-intersecting.
- Route 4, strict snappy absolute-layer fallback: bounded at the three requested target cases. It ran finite OpenFOAM cases, but actual layer insertion and yPlus did not meet wall-function or wall-resolved acceptance.

The route order was exhausted without hand-repairing cells, reviving retired custom topology, changing geometry/flow/reference definitions, or merging diagnostic patches into the primary wall.
