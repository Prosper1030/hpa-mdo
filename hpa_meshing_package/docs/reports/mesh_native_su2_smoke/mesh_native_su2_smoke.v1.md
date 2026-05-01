# Mesh-Native SU2 Smoke Report v1

Date: 2026-05-01

## Objective

Prove that the mesh-native route can produce a SU2-readable volume mesh and a
marker-consistent SU2 runtime case without VSP/ESP STEP/BREP export or CAD
repair in the critical path.

## Route Tested

`mesh_native_structured_box_shell_su2_smoke_case`

This is a parser and marker-ownership smoke route. The wing boundary is
represented by the wing bounding box, not the true wing surface. The output is
therefore not valid for aerodynamic coefficient interpretation.

## Artifacts

- Mesh: `artifacts/structured_box_shell/mesh.su2`
- Runtime config: `artifacts/structured_box_shell/su2_runtime.cfg`
- Solver log: `artifacts/structured_box_shell/solver.log`
- History: `artifacts/structured_box_shell/history.csv`
- Case report: `artifacts/structured_box_shell/mesh_native_su2_smoke_report.json`

## Mesh Gate

- `NDIME = 3`
- `NELEM = 26`
- `NPOIN = 64`
- `NMARK = 2`
- `wing_wall`: 6 quad marker faces
- `farfield`: 54 quad marker faces
- Marker audit: pass
- Missing config markers: none
- Unassigned mesh markers: none
- Zero-element markers: none

## SU2 Smoke

Command:

```text
SU2_CFD -t 1 su2_runtime.cfg
```

Runtime:

- Solver: `INC_EULER`
- Velocity: `6.5 m/s`
- Alpha: `0 deg`
- Iterations requested: `3`
- `REF_AREA = 2.0`
- `REF_LENGTH = 1.0`
- Wall BC: `MARKER_EULER = ( wing_wall )`
- Farfield BC: `MARKER_FAR = ( farfield )`

Result:

- Exit status: success
- History rows: 3
- Final iteration: 2
- Final `CL`: `-2.308114465e-09`
- Final `CD`: `-0.007227698717`

## Engineering Assessment

Pass for SU2 readability and deterministic marker ownership.

No aerodynamic conclusion should be drawn from `CL` or `CD`: the mesh is only 26
hexahedra, the wing is a rectangular bounding-box obstacle, there is no true
airfoil surface, no boundary-layer strategy, and the run stops at a 3-iteration
smoke limit.

One physics-setup caveat remains visible in `solver.log`: SU2 reports a dynamic
pressure table value of `0`, while `RefForce = 51.75625` is consistent with
`0.5 * rho * V^2 * Sref` for `rho = 1.225`, `V = 6.5`, and `Sref = 2.0`.
This does not block the parser/marker smoke, but it must be audited before any
future coefficient-validation claim.

## Verdict

The pipeline reaches SU2 without STEP/BREP repair:

```text
mesh-native wing input
  -> deterministic wing/farfield bounds
  -> structured SU2 smoke volume mesh
  -> marker audit
  -> SU2_CFD run
  -> history.csv
```

Next required step is not to interpret this case aerodynamically; it is to
replace the bounding-box inner obstacle with the real mesh-native wing boundary
or a robust Gmsh/discrete-volume route, while keeping this smoke as the
readability and marker-regression canary.
