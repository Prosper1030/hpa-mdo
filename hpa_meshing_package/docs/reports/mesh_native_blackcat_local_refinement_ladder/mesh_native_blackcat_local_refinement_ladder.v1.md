# Mesh-Native Black Cat Local Refinement Ladder v1

Date: 2026-05-01

## Objective

Check whether the new wing-local Gmsh background sizing field is enough to move
the Black Cat 004 mesh-native route toward a production-scale CFD mesh without
refining the entire farfield volume.

## Route Tested

`blackcat_main_wing_mesh_native_faceted_refinement_ladder`

Sizing policy:

- `points_per_side = 8`
- wing-local mesh sizes: `14.0`, `10.0`, `8.0`, `6.0`, `4.5`, `3.0`
- farfield mesh size: `18.0`
- wing refinement radius: `12.0 m`
- Gmsh background field: Distance/Threshold from mesh-native wing nodes
- target: `1,000,000` volume elements
- local guardrail: `25,000` volume elements

## Artifacts

- Report JSON: `mesh_native_blackcat_local_refinement_ladder.v1.json`
- Runtime report JSON: `artifacts/refinement_ladder_report.json`
- Mesh artifacts:
  - `artifacts/00_h_14/mesh.msh`
  - `artifacts/01_h_10/mesh.msh`
  - `artifacts/02_h_8/mesh.msh`
  - `artifacts/03_h_6/mesh.msh`
  - `artifacts/04_h_4p5/mesh.msh`
  - `artifacts/05_h_3/mesh.msh`

## Results

| wing h | farfield h | nodes | volume elements | target ratio | min gamma | p01 gamma | minSICN | quality gate |
| -: | -: | -: | -: | -: | -: | -: | -: | :- |
| 14.0 | 18.0 | 312 | 903 | 0.000903 | 5.1712e-4 | 0.00308 | 4.6548e-4 | pass |
| 10.0 | 18.0 | 313 | 915 | 0.000915 | 4.9973e-4 | 0.00262 | 4.5177e-4 | pass |
| 8.0 | 18.0 | 325 | 944 | 0.000944 | 6.7928e-4 | 0.00301 | 6.4791e-4 | pass |
| 6.0 | 18.0 | 333 | 976 | 0.000976 | 5.3084e-4 | 0.00387 | 6.3010e-4 | pass |
| 4.5 | 18.0 | 340 | 1,007 | 0.001007 | 9.0067e-4 | 0.00551 | 8.7195e-4 | pass |
| 3.0 | 18.0 | 427 | 1,269 | 0.001269 | 1.6975e-5 | 0.00332 | 6.1437e-4 | pass |

All cases had zero non-positive minSICN, minSIGE, and volume counts.

## Engineering Assessment

The local sizing field is wired correctly and the generated meshes pass the
basic positivity quality gate. It does not yet solve mesh density.

The key observation is that shrinking the wing-local volume size from `14.0` to
`3.0` only increases the volume mesh from `903` to `1,269` tetrahedra. That is
still about `0.13%` of the current million-element production target. The reason
is structural: the wing boundary is already a fixed faceted surface, so the
background field can refine the volume insertion somewhat, but it cannot create
new chordwise/spanwise wing-surface detail by itself.

This means the next credible refinement step is not just another smaller
background-field size. The route needs coupled surface and volume refinement:

- raise `points_per_side` and possibly station interpolation on the wing surface
- keep farfield coarse
- add explicit wake/tip/trailing-edge sizing zones
- rerun the same ladder and monitor quality/element growth

## Verdict

Pass for implementation wiring:

- Distance/Threshold background field is active
- farfield and wing sizing are reported per case
- marker ownership remains deterministic
- quality gate remains positive

No-go for production CFD:

- the finest local-refinement case has only `1,269` volume elements
- no boundary-layer strategy exists in this route
- no SU2 convergence evidence is produced

Next step: make surface discretization part of the automatic refinement ladder,
then add wake/tip/trailing-edge zones. The million-scale target should remain a
production-scale gate, but it must be reached by controlled local refinement,
not by blindly shrinking the whole farfield.
