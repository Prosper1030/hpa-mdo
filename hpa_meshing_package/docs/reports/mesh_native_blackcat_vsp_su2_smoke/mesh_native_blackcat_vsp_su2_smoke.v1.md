# Mesh-Native Black Cat VSP SU2 Smoke v1

- route: `OpenVSP .vsp3 -> mesh-native surface -> Gmsh volume -> SU2`
- geometry source: `data/blackcat_004_origin.vsp3`
- reference source: `data/blackcat_004_full.avl`
- case dir: `/tmp/hpa_mdo_blackcat_vsp_native_mesh_h0025_feature3`
- status: `vsp_native_geometry_mesh_and_su2_smoke_passed`

## Mesh Result

| item | value |
|---|---:|
| nodes | `258,378` |
| volume tetra | `717,901` |
| `wing_wall` boundary elems | `469,776` |
| `farfield` boundary elems | `518` |
| `min_gamma` | `3.81e-05` |
| `p01_gamma` | `0.01785` |
| `min_sicn` | `4.90e-04` |
| non-positive volumes | `0` |

Engineering read: this is usable for solver smoke. It is not a final CFD mesh because the low-tail quality metrics still show sliver risk, probably near sharp TE/tip features.

## SU2 Smoke

| item | value |
|---|---:|
| solver | `INC_NAVIER_STOKES` |
| wall BC | `MARKER_HEATFLUX = ( wing_wall, 0.0 )` |
| iterations | `150` |
| return code | `0` |
| marker audit | `pass` |
| final `CL` | `0.2589146327` |
| final `CD` | `0.1531623408` |
| final `CMy` | `-0.09049866671` |

SU2 exited normally after hitting the 150-iteration budget. It did not meet the very strict Cauchy convergence criterion, so this is a smoke result, not a converged aerodynamic result.

## Engineering Judgment

The important result is that the corrected geometry route is now real: VSP-native geometry can produce a high-density-ish mesh and SU2 can read/run it with owned markers. CD is positive under the no-slip wall setup, unlike the earlier Euler slip-wall drag behavior.

Next engineering step: run 1000+ iterations on this same VSP-native mesh, then compare against a second mesh density. Do not spend more time on Euler drag for this geometry.
