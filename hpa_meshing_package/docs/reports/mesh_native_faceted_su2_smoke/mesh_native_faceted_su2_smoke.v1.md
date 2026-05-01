# Mesh-Native Faceted SU2 Smoke Report v1

Date: 2026-05-01

## Objective

Prove that the mesh-native route can move beyond a bounding-box canary and hand
a faceted mesh-native wing boundary to Gmsh for volume meshing, then to SU2 for
a solver smoke run, without STEP/BREP repair.

## Route Tested

`mesh_native_faceted_gmsh_volume_su2_smoke_case`

The wing boundary is built from mesh-native panels and converted into Gmsh
built-in `PlaneSurface` facets. The fluid volume is created from a farfield
surface loop with the wing surface loop as the internal void. This uses Gmsh as
a volume mesher, not as a CAD exchange repair path.

## Artifacts

- Gmsh mesh: `artifacts/faceted_rect_wing/mesh.msh`
- SU2 mesh: `artifacts/faceted_rect_wing/mesh.su2`
- Runtime config: `artifacts/faceted_rect_wing/su2_runtime.cfg`
- Solver log: `artifacts/faceted_rect_wing/solver.log`
- History: `artifacts/faceted_rect_wing/history.csv`
- Case report: `artifacts/faceted_rect_wing/mesh_native_faceted_su2_smoke_report.json`

## Mesh Gate

- Gmsh volume count: `1`
- Gmsh nodes: `135`
- Gmsh/SU2 volume elements: `407`
- Volume element type: tetrahedron
- Mesh-native source facets: `36`
- SU2 `NMARK`: `2`
- `wing_wall`: 24 triangular marker faces
- `farfield`: 220 triangular marker faces
- Marker audit: pass
- Missing config markers: none
- Unassigned mesh markers: none
- Zero-element markers: none
- SU2 preprocessing: all volume elements correctly oriented; SU2 re-oriented 228 triangular surface elements

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
- Final `CL`: `0.0104840086`
- Final `CD`: `-0.006009687423`

## Engineering Assessment

This is a stronger geometry-pipeline smoke than the structured box-shell canary:
the SU2 wall marker now comes from the mesh-native wing facets rather than from
the wing bounding box.

It is still not aerodynamic evidence. The wing fixture is intentionally tiny
and rectangular: 3 stations, 4 points per station, 407 tet volume elements,
no boundary-layer prism mesh, close farfield, and only 3 solver iterations.
The final `CL/CD` values are solver-readability smoke outputs only.

The same incompressible-SU2 setup caveat remains: `solver.log` reports dynamic
pressure as `0` in the properties table while `RefForce = 51.75625` is consistent
with `0.5 * rho * V^2 * Sref` for `rho = 1.225`, `V = 6.5`, and `Sref = 2.0`.
This needs a physics-setup audit before coefficient validation.

## Verdict

The faceted mesh-native pipeline reaches SU2:

```text
mesh-native wing panels
  -> Gmsh plane-surface faceted volume
  -> SU2 mesh export
  -> marker audit
  -> SU2_CFD run
  -> history.csv
```

Next engineering step: replace the rectangular toy wing with the actual HPA
station input and add mesh-size guardrails/quality gates before attempting any
coefficient comparison.
