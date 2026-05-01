# Mesh-Native Black Cat Feature Refinement Sweep v1

Date: 2026-05-01

## Objective

Record a first automatic TE/tip/wake feature-refinement sweep for the Black Cat
004 mesh-native main-wing route.

This is not a production CFD mesh. The goal is narrower: prove that localized
feature boxes can increase mesh density without refining the full farfield, and
show where quality warnings begin to appear.

## Route Tested

`blackcat_main_wing_mesh_native_coupled_refinement_ladder`

Fixed settings:

- source geometry: `data/blackcat_004_full.avl`
- full-span main wing
- `spanwise_subdivisions = 1`
- `points_per_side = 8`
- wing-local mesh size: `6.0`
- farfield mesh size: `18.0`
- wing refinement radius: `12.0 m`
- target: `1,000,000` volume elements
- local guardrail: `25,000` volume elements

Feature-refinement sweep:

- no feature boxes
- feature box size `3.0`
- feature box size `2.0`
- feature box size `1.0`

The feature boxes are first-pass axis-aligned Gmsh `Box` size fields around:

- trailing edge
- left tip
- right tip
- wake

## Artifacts

- Report JSON: `mesh_native_blackcat_feature_refinement_sweep.v1.json`
- Runtime report JSON: `artifacts/coupled_refinement_ladder_report.json`
- Mesh artifacts:
  - `artifacts/00_span_1_pps_8_feat_none_h_6/mesh.msh`
  - `artifacts/01_span_1_pps_8_feat_3_h_6/mesh.msh`
  - `artifacts/02_span_1_pps_8_feat_2_h_6/mesh.msh`
  - `artifacts/03_span_1_pps_8_feat_1_h_6/mesh.msh`

SU2 files were intentionally not written. This packet is a meshing evidence
run, not a solver-validation run.

## Results

| feature size | feature boxes | nodes | volume elements | target ratio | min gamma | p01 gamma | warnings |
| :- | -: | -: | -: | -: | -: | -: | :- |
| none | 0 | 333 | 976 | 0.000976 | 5.3084e-4 | 0.00387 | `low_p01_gamma` |
| 3.0 | 4 | 404 | 1,222 | 0.001222 | 2.1379e-4 | 0.00323 | `low_p01_gamma` |
| 2.0 | 4 | 542 | 1,683 | 0.001683 | 1.0240e-6 | 0.00024 | `very_low_min_gamma`, `low_p01_gamma` |
| 1.0 | 4 | 820 | 3,036 | 0.003036 | 8.4981e-7 | 0.00072 | `very_low_min_gamma`, `low_p01_gamma` |

## Engineering Assessment

The implementation is now doing real localized refinement. Reducing feature
box size from none to `1.0` grows the volume mesh from `976` to `3,036`
tetrahedra while keeping the farfield coarse.

The engineering warning is just as important: after `feature size = 2.0`, the
mesh starts triggering `very_low_min_gamma`. That means the next production
strategy should not blindly push feature boxes smaller. The route needs an
automatic stop/selection policy that considers both element count and quality.

For now, `feature size = 3.0` is the least-bad local refinement candidate in
this tiny Mac-safe sweep: it increases density by about `25%` over the no-box
case while avoiding the very-low-gamma warning. It is still far below the
million-cell credibility target and should not be used to interpret CL/CD.

## Verdict

Pass for:

- feature-box field wiring
- coupled feature-size sweep automation
- first automatic density-vs-quality tradeoff evidence

No-go for:

- production CFD
- mesh convergence
- aerodynamic coefficient interpretation

Next step: add an automatic selector that reports the densest case without
blockers or severe quality warnings, then run a larger ladder combining
spanwise, chordwise, feature boxes, and volume size.
