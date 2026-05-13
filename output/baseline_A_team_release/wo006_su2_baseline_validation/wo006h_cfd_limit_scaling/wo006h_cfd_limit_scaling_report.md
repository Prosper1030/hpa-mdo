# WO-006H CFD Limit Scaling Campaign

Verdict: `wo006h_hard_limit_escalation_package_ready_after_serious_scaling`

## Authority

- design mass: `98.5 kg`
- span: `34.332286 m` full / `17.166143 m` half
- Sref/Cref/Bref: `33.420059598 m^2`, `1.003721543 m`, `34.332286 m`
- required CL at 6.5 m/s: `1.117`

## Local No-BL Scaling

| attempt_id | status | mesh_size | volume_element_count | node_count | mesh_quality_status | marker_audit_status | failure_code | elapsed_seconds |
|---|---|---|---|---|---|---|---|---|
| no_bl_h_0p04 | failed | 0.04 |  |  |  |  | Exception | 1.926 |
| no_bl_h_0p06 | meshed | 0.06 | 3596163 | 638397 | pass | pass |  | 76.05 |
| no_bl_h_0p08 | meshed | 0.08 | 3046012 | 533411 | pass | pass |  | 67.45 |
| no_bl_h_0p1 | meshed | 0.1 | 1605198 | 291077 | pass | pass |  | 47.45 |

## BL/Core Variants

| attempt_id | status | mesh_algorithm3d | preserve_boundary_mesh | volume_element_count | mesh_quality_status | unmatched_core_interface_face_count | unmatched_bl_boundary_face_count | elapsed_seconds |
|---|---|---|---|---|---|---|---|---|
| core_preserve_alg10_h1p0 | timeout |  |  |  |  |  |  | 180 |
| core_preserve_alg1_h1p0 | timeout |  |  |  |  |  |  | 180 |
| core_remesh_alg10_h0p5 | meshed | 10 | False | 24252 | pass | 158 | 4672 | 30.52 |

## Engineering Read

Local run reached 3596163 no-BL cells or a higher attempted rung, but the only scalable current route is still no-BL. BL/core variants did not clear the quality/interface gate. Therefore local output is not physically defensible CFD; the useful result is the executable larger-compute package plus hard gate evidence.

The HPC package is in `hpc_escalation_package/`. Lower-order AVL/XFOIL/VSPAERO remain sanity checks only.
