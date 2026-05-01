# Mesh-Native Black Cat Refinement Ladder v1

Date: 2026-05-01

## Objective

Record a reproducible mesh-density and quality ladder for the Black Cat 004
main wing using the mesh-native faceted Gmsh volume route. This is the first
evidence packet for the new non-STEP/BREP CFD geometry path.

## Route Tested

`blackcat_main_wing_mesh_native_faceted_refinement_ladder`

Input source:

- `data/blackcat_004_full.avl`
- `points_per_side = 8`
- full-span main wing
- mesh-native wing surface plus mesh-native farfield box
- no VSP/ESP STEP/BREP export
- no CAD repair

## Artifacts

- Report JSON: `mesh_native_blackcat_refinement_ladder.v1.json`
- Runtime report JSON: `artifacts/refinement_ladder_report.json`
- Mesh artifacts:
  - `artifacts/00_h_14/mesh.msh`
  - `artifacts/01_h_10/mesh.msh`
  - `artifacts/02_h_8/mesh.msh`
  - `artifacts/03_h_6/mesh.msh`
  - `artifacts/04_h_4p5/mesh.msh`

SU2 files were intentionally not written for this ladder packet. This run is a
mesh-density and quality audit, not a solver run.

## Ladder Settings

- Global Gmsh mesh sizes: `14.0`, `10.0`, `8.0`, `6.0`, `4.5`
- Production-scale target: `1,000,000` volume elements
- Local guardrail for this evidence run: `25,000` volume elements
- Volume element type: tetrahedron
- Required markers: `wing_wall`, `farfield`, `fluid`

## Results

| h | nodes | volume elements | target ratio | min gamma | p01 gamma | minSICN | p01 minSICN | quality gate |
| -: | -: | -: | -: | -: | -: | -: | -: | :- |
| 14.0 | 367 | 1,054 | 0.001054 | 7.3157e-4 | 0.00436 | 6.7749e-4 | 0.00411 | pass |
| 10.0 | 525 | 1,532 | 0.001532 | 9.0016e-4 | 0.00678 | 7.9632e-4 | 0.00582 | pass |
| 8.0 | 751 | 2,191 | 0.002191 | 8.4402e-4 | 0.00569 | 8.9871e-4 | 0.00630 | pass |
| 6.0 | 1,066 | 3,164 | 0.003164 | 0.001067 | 0.01182 | 9.4164e-4 | 0.01155 | pass |
| 4.5 | 1,649 | 4,916 | 0.004916 | 0.001239 | 0.01740 | 0.001108 | 0.01635 | pass |

All cases had:

- `non_positive_min_sicn_count = 0`
- `non_positive_min_sige_count = 0`
- `non_positive_volume_count = 0`
- `ill_shaped_tet_count = 0`
- `wing_wall` and `farfield` physical groups present

## Engineering Assessment

The mesh quality gate passes in the narrow sense: the generated tetrahedra have
positive quality and volume metrics, and the marker ownership is deterministic.

This is not yet a credible CFD mesh. The finest case has only `4,916` volume
elements, which is about `0.49%` of the current `1,000,000` element production
target. For an HPA main-wing 3D CFD case, this is still a smoke and topology
mesh, not a mesh-converged aerodynamic result.

The ladder also uses global isotropic tetra sizing only. That is useful for
automation and first evidence, but it is not the final strategy. A production
route still needs local refinement near the leading edge, trailing edge, tip,
wake, and later a boundary-layer strategy for viscous CFD.

## Verdict

Pass for:

- mesh-native Black Cat geometry ingestion
- deterministic marker ownership
- automated coarse-to-fine Gmsh ladder
- basic tetra quality gate
- reproducible scale-gap reporting

No-go for:

- interpreting `CL`, `CD`, or pressure distribution from these meshes
- claiming mesh convergence
- treating the current faceted tet route as a viscous production mesh

Next step: add a local refinement policy instead of shrinking the whole domain
uniformly. The first useful policy should refine wing surface, tip, trailing
edge, and wake neighborhoods while keeping the farfield coarser, then rerun this
same ladder toward coarse/medium/fine million-scale cases.
