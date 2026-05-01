# Mesh-Native Black Cat High-Density 100k Probe v1

Date: 2026-05-01

## Objective

Test whether the mesh-native Black Cat main-wing route can produce a
SU2-exportable higher-density tetrahedral mesh without returning to
VSP/ESP STEP/BREP geometry.

This is still not a production CFD-convergence mesh. The target here is a
Mac-safe high-density meshing check around `100,000` volume elements.

## Route Tested

`blackcat_main_wing_mesh_native_coupled_refinement_ladder`

Fixed settings:

- source geometry: `data/blackcat_004_full.avl`
- full-span main wing
- `spanwise_subdivisions = 4`
- `points_per_side = 16`
- feature box size: `3.0`
- farfield mesh size: `18.0`
- wing refinement radius: `12.0 m`
- target: `100,000` volume elements
- guardrail: `300,000` volume elements
- SU2 export: enabled

Feature boxes:

- trailing-edge refinement region
- left-tip refinement region
- right-tip refinement region
- wake refinement region

## Artifacts

- Report JSON: `mesh_native_blackcat_high_density_100k_probe.v1.json`
- Runtime report JSON: `artifacts/coupled_refinement_ladder_report.json`
- SU2 smoke report JSON:
  `artifacts/01_span_4_pps_16_feat_3_h_0p09/high_density_su2_smoke_report.json`
- Mesh artifacts:
  - `artifacts/00_span_4_pps_16_feat_3_h_0p1/mesh.msh`
  - `artifacts/00_span_4_pps_16_feat_3_h_0p1/mesh.su2`
  - `artifacts/01_span_4_pps_16_feat_3_h_0p09/mesh.msh`
  - `artifacts/01_span_4_pps_16_feat_3_h_0p09/mesh.su2`

## Results

| h | nodes | volume elements | target status | min gamma | p01 gamma | warnings | selected |
| -: | -: | -: | :- | -: | -: | :- | :- |
| 0.10 | 31,077 | 92,645 | under target | 1.9917e-5 | 0.02563 | `very_low_min_gamma` | no |
| 0.09 | 35,993 | 107,415 | target reached | 3.0836e-4 | 0.02975 | none | yes |

Selected/recommended case:

- mesh size: `0.09`
- volume elements: `107,415`
- nodes: `35,993`
- quality warnings: none
- SU2 `NDIME`: `3`
- SU2 `NELEM`: `107,415`
- SU2 `NPOIN`: `35,993`
- SU2 markers: `wing_wall`, `farfield`

Marker element counts in the selected SU2 mesh:

| marker | boundary elements |
| :- | -: |
| `wing_wall` | 62,736 |
| `farfield` | 516 |

## SU2 Smoke

The selected `h = 0.09` mesh was run through `SU2_CFD` with `INC_EULER` for
three iterations using 4 threads.

Smoke result:

- return code: `0`
- run status: `completed`
- marker audit: `pass`
- final iteration: `2`
- final smoke `CL`: `0.1088195619`
- final smoke `CD`: `0.06000507882`

These coefficients are not aerodynamic evidence. The run is only a readability
and marker-ownership smoke test for the high-density mesh.

## Engineering Assessment

This is the first mesh-native Black Cat main-wing evidence packet that reaches
a `100k`-class volume mesh, writes a SU2 mesh with expected markers, and starts
`SU2_CFD` without immediate solver failure.

The result is encouraging but bounded. It proves that the current mesh-native
route can generate a higher-density tetrahedral mesh automatically on this
machine. It does not prove CFD convergence, and it is still about one order of
magnitude below a million-element credibility target.

The neighboring `h = 0.10` case shows why the automatic selector matters: it is
slightly coarser but has an isolated `very_low_min_gamma` warning. The `h =
0.09` case is denser and cleaner in this run, so it is the correct selected
candidate for the next SU2 smoke.

## Verdict

Pass for:

- mesh-native high-density meshing above `100k` volume elements
- SU2 mesh export
- exact expected boundary markers
- automatic quality-safe candidate selection

No-go for:

- final aerodynamic interpretation
- mesh convergence claims
- replacing a coarse/medium/fine refinement study

Next step: run SU2 smoke on the selected `h = 0.09` mesh, then build a larger
coarse/medium/fine ladder toward the million-element target.
