# Black Cat mesh-native SU2 smoke v1

This report records a full pipeline smoke run using repository-owned Black Cat
main-wing data:

```text
data/blackcat_004_full.avl
  -> mesh-native full-span WingSpec
  -> mesh-native faceted wing surface
  -> Gmsh faceted tet volume
  -> SU2 mesh/config marker audit
  -> SU2_CFD INC_EULER smoke run
```

No STEP, BREP, OpenVSP export, ESP export, or CAD repair step is used in this
critical path.

## Source gate

- Source geometry: `data/blackcat_004_full.avl`
- Section source: `Main Wing` AVL `SECTION` blocks with inline `AIRFOIL`
  coordinates
- Full-span station count: `11`
- Points per station after deterministic resampling: `14`
- Reference values from AVL:
  - `Sref_full = 35.175 m2`
  - `Cref = 1.130189765 m`
  - `Bref_full = 33.0 m`
- Recovered mesh-native planform area: `35.175000000000004 m2`
- Recovered full span: `33.0 m`

## Mesh gate

- Gmsh route: `mesh_native_faceted_gmsh_volume`
- Gmsh volume count: `1`
- Nodes: `751`
- Volume elements: `2191`
- Volume element type counts: `{ "4": 2191 }`
- Source surface triangles: `320`
- SU2 markers:
  - `wing_wall`: `308` triangular boundary elements
  - `farfield`: `1168` triangular boundary elements
- Marker audit: `pass`
- Missing config markers: `[]`
- Unassigned mesh markers: `[]`
- Zero-element markers: `[]`

SU2 preprocessing evidence from `artifacts/blackcat_main_wing/solver.log`:

```text
751 grid points.
2191 volume elements.
308 boundary elements in index 0 (Marker = wing_wall).
1168 boundary elements in index 1 (Marker = farfield).
All volume elements are correctly oriented.
There has been a re-orientation of 1196 TRIANGLE surface elements.
Exit Success (SU2_CFD)
```

## SU2 smoke

- Solver: `INC_EULER`
- Command: `SU2_CFD -t 1 su2_runtime.cfg`
- Velocity: `6.5 m/s`
- AoA: `0.0 deg`
- Iterations requested: `3`
- History rows: `3`
- Final iteration: `2`
- Final smoke coefficients:
  - `CL = 0.03138246626`
  - `CD = -0.04357673071`
  - `CMx = -0.4548779929`
  - `CMy = -0.007863122175`
  - `CMz = 0.0188046601`

## Engineering assessment

This is a pass for pipeline connectivity and marker ownership:

```text
AVL station/reference data reaches SU2 through mesh-native geometry.
Gmsh creates a 3D tet volume.
SU2 reads the mesh.
SU2 sees nonzero wing_wall and farfield markers.
The solver exits successfully and writes finite force coefficients.
```

This is not aerodynamic validation. The coefficient values above should not be
compared to VSPAERO or used to judge the real main-wing lift yet.

Engineering caveats:

- The run is a coarse faceted Euler smoke case with only `2191` tetrahedra.
- There is no viscous boundary-layer prism strategy.
- The run stops after three iterations, so convergence is not evaluated.
- The farfield is deliberately close for a fast smoke run.
- SU2 reports `Dynamic Pressure = 0` in the properties table while `RefForce`
  is finite; audit this before coefficient validation.
- SU2 re-oriented `1196` triangular surface elements. Volume orientation passes,
  but the surface-normal convention should be cleaned before production use.

## Verdict

`pass_for_blackcat_mesh_native_pipeline_connectivity_to_su2_smoke`

The route is now connected end to end for the Black Cat main wing without
STEP/BREP repair. The next engineering gate should be surface-orientation
cleanup plus a less toy-like mesh/convergence study, not interpretation of this
three-iteration `CL/CD`.
