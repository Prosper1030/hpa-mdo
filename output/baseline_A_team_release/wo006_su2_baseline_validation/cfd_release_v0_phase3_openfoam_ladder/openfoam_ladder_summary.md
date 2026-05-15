# OpenFOAM Ladder Summary

- route: `OpenFOAM full-wing bounded grid/layer/yPlus ladder`
- solver: `simpleFoam`
- baseline turbulence model: `SpalartAllmaras`
- output_dir: `/Volumes/Samsung SSD/hpa-mdo/output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0_phase3_openfoam_ladder`

| case | purpose | acceptance | cells | max skew | CD_primary | CL_primary | y+ upper mean | y+ lower mean |
|---|---|---|---:|---:|---:|---:|---:|---:|
| `layers_0` | `baseline_no_layers` | `accepted` | 212987 | `6.08499` | `0.09330549` | `0.4431198` | `325.5238` | `398.1273` |
| `layers_3` | `baseline_layer_ladder` | `rejected` | 232934 | `6.08499` | `0.07556245` | `0.9004293` | `193.8764` | `134.6553` |
| `layers_8` | `route_smoke_reproduction` | `accepted` | 238014 | `6.08499` | `0.08141586` | `0.8227612` | `183.2387` | `164.5427` |
| `layers_12` | `layer_ladder` | `rejected` | 240218 | `6.08499` | `0.08959346` | `0.7068862` | `188.8339` | `174.16` |
| `layers_16` | `layer_ladder` | `accepted` | 241143 | `6.08499` | `0.09079239` | `0.6820456` | `194.7079` | `186.3026` |
| `layers_24` | `layer_ladder` | `accepted` | 239988 | `6.08499` | `0.09094512` | `0.6697053` | `209.5007` | `193.3586` |
| `layers_12_low_yplus_factor_0p44` | `low_yplus_oriented_attempt` | `rejected` | 233448 | `6.08499` | `8.064502e+87` | `3.774225e+88` | `not_available` | `not_available` |
| `layers_8_refined_surface_plus1` | `surface_refinement_comparison` | `rejected` | 514157 | `5.4911` | `0.05869294` | `0.9176483` | `89.9788` | `86.52465` |
| `layers_8_kOmegaSST_same_mesh` | `turbulence_model_sensitivity` | `rejected` | 238014 | `6.08499` | `0.08706285` | `0.8308892` | `47.7129` | `45.58173` |

The ladder keeps `wing_upper + wing_lower` as primary and keeps tip/TE/closure as diagnostics.
Accepted means route evidence inside the stated bounded CFD trust boundary, not final drag truth.