# WO-006H Reopened CFD Campaign

Verdict: `su2_local_hard_limit_proven_with_executable_hpc_case`

## Authority

- design mass: `98.5 kg`
- span: `34.332286 m` full / `17.166143 m` half

## Gate Status

- physical_result: `False`
- low_confidence_result: `False`
- serious_no_bl_success: `True`
- failed_finer_no_bl_rungs: `True`
- serious_bl_core_blocker: `True`
- hpc_targets_missing_cases: `True`

## Engineering Read

Local evidence now separates two facts: no-BL HXT can mesh a serious 3.8M-cell control case, but finer no-BL rungs and BL/core routes fail at current surface/PLC/topology gates before credible viscous CFD. The HPC package targets those missing finer and BL/viscous cases rather than rerunning only already-successful coarser no-BL meshes.

## HPC Target Cases

- `bl_core_preserve_alg10_32x2`
- `bl_core_preserve_alg1_32x2`
- `mesh_h004_delaunay`
- `mesh_h004_hxt`
- `mesh_h005_hxt`

## Attempt Summary

- attempts read: `12`
- coefficients remain non-interpretable unless a later final mesh/solver gate says otherwise

## Key Local Evidence

- `core_preserve_interface_alg1_h1p0_900s`; status `meshed`; h `1.0`; Gmsh alg `1`; cells `20582`; nodes `56947`; elapsed `182.90 s`; quality `fail`; unmatched core `158`; unmatched BL `4672`
- `attempt_full_bl_boundary_core_preserve_alg1_h1p0`; status `failed`; elapsed `325.38 s`; error `PLC Error:  A segment and a facet intersect at point`
- `no_bl_h_0p04_alg1_delaunay`; status `failed`; h `0.04`; Gmsh alg `1`; elapsed `8.43 s`; error `Invalid boundary mesh (overlapping facets) on surface 869 surface 992`
- `no_bl_h_0p055`; status `meshed`; h `0.055`; cells `3790657`; nodes `675820`; elapsed `83.30 s`; quality `pass`
- `no_bl_h_0p05`; status `failed`; h `0.05`; elapsed `1.65 s`; error `HXT 3D mesh failed`
- `core_preserve_alg10_h1p0`; status `timeout`; elapsed `180.01 s`
- `core_preserve_alg1_h1p0`; status `timeout`; elapsed `180.01 s`
- `core_remesh_alg10_h0p5`; status `meshed`; h `0.5`; Gmsh alg `10`; cells `24252`; nodes `61701`; elapsed `30.52 s`; quality `pass`; unmatched core `158`; unmatched BL `4672`
- `no_bl_h_0p04`; status `failed`; h `0.04`; elapsed `1.93 s`; error `HXT 3D mesh failed`
- `no_bl_h_0p06`; status `meshed`; h `0.06`; cells `3596163`; nodes `638397`; elapsed `76.05 s`; quality `pass`
- `no_bl_h_0p08`; status `meshed`; h `0.08`; cells `3046012`; nodes `533411`; elapsed `67.45 s`; quality `pass`
- `no_bl_h_0p1`; status `meshed`; h `0.1`; cells `1605198`; nodes `291077`; elapsed `47.45 s`; quality `pass`
