# Mesh-Native Black Cat Span/Chord Coupled Ladder v1

Date: 2026-05-01

## Objective

Check whether coupled surface refinement can move the Black Cat 004
mesh-native main-wing route toward a production-scale CFD mesh.

This packet follows the previous global and wing-local tetrahedral refinement
ladders. Those runs showed that shrinking the volume mesh size alone does not
create enough wing-surface resolution. This run varies both:

- chordwise airfoil resampling density
- spanwise station interpolation density

It still keeps the run Mac-safe and intentionally below the million-element
production target.

## Route Tested

`blackcat_main_wing_mesh_native_coupled_refinement_ladder`

Input and sizing policy:

- source geometry: `data/blackcat_004_full.avl`
- full-span main wing
- no VSP/ESP STEP/BREP export
- no CAD repair
- spanwise subdivisions: `1`, `2`, `4`
- points per airfoil side: `8`, `12`, `16`
- wing-local mesh size: `6.0`
- farfield mesh size: `18.0`
- wing refinement radius: `12.0 m`
- production-scale target: `1,000,000` volume elements
- local guardrail: `25,000` volume elements

## Artifacts

- Report JSON: `mesh_native_blackcat_span_chord_coupled_ladder.v1.json`
- Runtime report JSON: `artifacts/coupled_refinement_ladder_report.json`
- Mesh artifacts:
  - `artifacts/00_span_1_pps_8_h_6/mesh.msh`
  - `artifacts/01_span_1_pps_12_h_6/mesh.msh`
  - `artifacts/02_span_1_pps_16_h_6/mesh.msh`
  - `artifacts/03_span_2_pps_8_h_6/mesh.msh`
  - `artifacts/04_span_2_pps_12_h_6/mesh.msh`
  - `artifacts/05_span_2_pps_16_h_6/mesh.msh`
  - `artifacts/06_span_4_pps_8_h_6/mesh.msh`
  - `artifacts/07_span_4_pps_12_h_6/mesh.msh`
  - `artifacts/08_span_4_pps_16_h_6/mesh.msh`

SU2 files were intentionally not written for this packet. This is a mesh
resolution and quality evidence run, not a solver-convergence run.

## Results

| span subdiv | points/side | stations | points/station | surface tris | nodes | volume elements | target ratio | min gamma | p01 gamma | minSICN | warnings |
| -: | -: | -: | -: | -: | -: | -: | -: | -: | -: | -: | :- |
| 1 | 8 | 11 | 14 | 320 | 333 | 976 | 0.000976 | 5.3084e-4 | 0.00387 | 6.3010e-4 | `low_p01_gamma` |
| 1 | 12 | 11 | 22 | 496 | 425 | 1,253 | 0.001253 | 2.3409e-4 | 0.00169 | 2.7004e-4 | `low_p01_gamma` |
| 1 | 16 | 11 | 30 | 672 | 517 | 1,548 | 0.001548 | 1.3218e-7 | 0.00009 | 1.0038e-5 | `very_low_min_gamma`, `very_low_min_sicn`, `low_p01_gamma` |
| 2 | 8 | 21 | 14 | 600 | 501 | 1,529 | 0.001529 | 5.2686e-4 | 0.00452 | 6.3667e-4 | `low_p01_gamma` |
| 2 | 12 | 21 | 22 | 936 | 675 | 2,018 | 0.002018 | 2.3248e-4 | 0.00220 | 2.7285e-4 | `low_p01_gamma` |
| 2 | 16 | 21 | 30 | 1,272 | 842 | 2,472 | 0.002472 | 1.5426e-6 | 0.00010 | 1.4930e-4 | `very_low_min_gamma`, `low_p01_gamma` |
| 4 | 8 | 41 | 14 | 1,160 | 838 | 2,621 | 0.002621 | 7.7179e-4 | 0.00978 | 7.8959e-4 | `low_p01_gamma` |
| 4 | 12 | 41 | 22 | 1,816 | 1,183 | 3,612 | 0.003612 | 3.3940e-4 | 0.00407 | 3.3184e-4 | `low_p01_gamma` |
| 4 | 16 | 41 | 30 | 2,472 | 1,513 | 4,438 | 0.004438 | 8.3411e-5 | 0.00391 | 1.8479e-4 | `very_low_min_gamma`, `low_p01_gamma` |

All cases had positive volume and positive signed quality metrics, so none of
these meshes is inverted. However, every case produced a quality warning.

## Engineering Assessment

The coupled refinement is wired correctly:

- spanwise subdivision increases station count from `11` to `41`
- chordwise resampling increases points per station from `14` to `30`
- surface triangles increase from `320` to `2,472`
- volume elements increase from `976` to `4,438`
- marker ownership remains deterministic

The run also makes the current limitation clearer. Even the most refined
Mac-safe case is only `0.44%` of the current `1,000,000` volume-element
production target. That means this is still a topology and automation mesh, not
a CFD-validation mesh.

The quality warnings are the more important engineering signal. Increasing
airfoil point count without better trailing-edge, tip, and wake control starts
creating very skinny tetrahedra. The `points_per_side = 16` cases are especially
suspicious: they increase resolution, but they also trigger `very_low_min_gamma`
or `very_low_min_sicn`. In practical CFD terms, those cells can poison residual
convergence and make force coefficients noisy even if SU2 can read the mesh.

## Verdict

Pass for:

- automatic coupled spanwise/chordwise refinement
- reproducible quality-warning summary
- deterministic mesh-native Black Cat geometry route
- Mac-safe evidence generation

No-go for:

- interpreting aerodynamic coefficients
- claiming mesh convergence
- treating naive point-count increases as the production refinement strategy

Next step: add localized refinement zones and sizing ownership around the
trailing edge, tip, and wake. The mesh should grow toward million-scale by
refining aerodynamically important regions, not by blindly adding chordwise
points until the tetrahedra become too skinny.
