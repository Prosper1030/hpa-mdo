# Mesh-Native Black Cat VSP Geometry Consistency v1

- verdict: `old_avl_mesh_native_source_not_identical_to_reference_vsp`
- reference VSP: `data/blackcat_004_origin.vsp3`
- historical AVL: `data/blackcat_004_full.avl`
- recommendation: use the VSP-native mesh-native builder for Black Cat CFD geometry; keep AVL as a reference/aero baseline.

## What Matches

- Full-span reference values match the VSP planform convention: `Sref = 35.175 m^2`, `Bref = 33.0 m`.
- Section chord schedule matches: `1.30, 1.30, 1.175, 1.04, 0.83, 0.435 m`.
- Airfoil coordinates match the VSP stations, including `fx76mp140` inboard and `clarkysm` at the tip.
- Incidence is still `3 deg`.

## What Did Not Match

The old AVL-driven mesh-native source was not fully identical to the VSP shape.

| quantity | old AVL mesh-native | VSP-native mesh | engineering meaning |
|---|---:|---:|---|
| tip `x_le` | `0.0000 m` | `0.2312 m` | outboard LE sweep/global incidence placement was missing |
| tip `y` | `16.5000 m` | `16.4747 m` | VSP surface uses projected station span under dihedral |
| tip `z_le` | `0.8110 m` | `0.8000 m` | VSP whole-wing rotation changes the actual LE height |
| mesh twist axis | `0.25 chord` | `0.0 chord` | VSP whole-wing incidence is represented around the LE placement |

## Station Comparison

| station | AVL `y` | VSP `y` | AVL `x_le` | VSP `x_le` | AVL `z_le` | VSP `z_le` |
|---:|---:|---:|---:|---:|---:|---:|
| 0 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| 1 | 4.5000 | 4.4993 | 0.0000 | 0.0041 | 0.0785 | 0.0784 |
| 2 | 7.5000 | 7.4975 | 0.0000 | 0.0096 | 0.1832 | 0.1830 |
| 3 | 10.5000 | 10.4934 | 0.0000 | 0.0575 | 0.3402 | 0.3377 |
| 4 | 13.5000 | 13.4861 | 0.0000 | 0.1180 | 0.5495 | 0.5441 |
| 5 | 16.5000 | 16.4747 | 0.0000 | 0.2312 | 0.8110 | 0.8000 |

## Engineering Judgment

This is not a catastrophic mismatch, but it is not safe to call the old AVL-driven mesh-native CFD geometry "same as VSP." The wing planform area, chord schedule, and airfoil sections were right, but the actual 3D placement of the outboard sections was incomplete.

For CFD, the VSP-native builder is the better current geometry source because it gives Gmsh/SU2 the external shape the designer actually sees in VSP, without going through STEP/BREP repair.
