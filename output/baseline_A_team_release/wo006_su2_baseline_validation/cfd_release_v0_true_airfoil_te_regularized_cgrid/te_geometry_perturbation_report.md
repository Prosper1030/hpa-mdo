# TE Geometry Perturbation Report

| variant | airfoil | raw TE gap/chord | resampled TE gap/chord | introduced | TE reg area delta/chord^2 | max TE displacement/chord | chord delta | Sref-equivalent effect |
|---|---:|---:|---:|---|---:|---:|---:|---|
| gap_0p00 | dae31 | 0.0 | 0.0 | False | 0.0 | 0.0 | 2.5000000000052758e-05 | TE z-gap changes section thickness area only; x-chord endpoints are unchanged, so planform Sref is unchanged. |
| gap_0p00 | cst_tip_nsga2_g05_child_0032_70ef8136 | 0.0017032 | 0.0017032 | False | 0.0 | 0.0 | 0.0 | TE z-gap changes section thickness area only; x-chord endpoints are unchanged, so planform Sref is unchanged. |
| gap_0p02 | dae31 | 0.0 | 0.0002 | True | 2.6770626201932934e-08 | 0.0001 | 2.5000000000052758e-05 | TE z-gap changes section thickness area only; x-chord endpoints are unchanged, so planform Sref is unchanged. |
| gap_0p02 | cst_tip_nsga2_g05_child_0032_70ef8136 | 0.0017032 | 0.0017032 | False | 0.0 | 0.0 | 0.0 | TE z-gap changes section thickness area only; x-chord endpoints are unchanged, so planform Sref is unchanged. |
| gap_0p05 | dae31 | 0.0 | 0.0005 | True | 6.692656547013787e-08 | 0.00025 | 2.5000000000052758e-05 | TE z-gap changes section thickness area only; x-chord endpoints are unchanged, so planform Sref is unchanged. |
| gap_0p05 | cst_tip_nsga2_g05_child_0032_70ef8136 | 0.0017032 | 0.0017032 | False | 0.0 | 0.0 | 0.0 | TE z-gap changes section thickness area only; x-chord endpoints are unchanged, so planform Sref is unchanged. |
| gap_0p10 | dae31 | 0.0 | 0.001 | True | 1.3385313091252016e-07 | 0.0005 | 2.5000000000052758e-05 | TE z-gap changes section thickness area only; x-chord endpoints are unchanged, so planform Sref is unchanged. |
| gap_0p10 | cst_tip_nsga2_g05_child_0032_70ef8136 | 0.0017032 | 0.0017032 | False | 0.0 | 0.0 | 0.0 | TE z-gap changes section thickness area only; x-chord endpoints are unchanged, so planform Sref is unchanged. |

Engineering read: DAE31 is the only mathematically sharp source TE in this matrix.
The `cst_tip` finite source TE gap is preserved and reported; it is not a new bluntness insertion.
The planform Sref-equivalent impact is zero for all variants because chord endpoints in x are unchanged.
