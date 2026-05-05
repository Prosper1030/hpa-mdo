# DAE outer-airfoil AVL match sweep

This sweep fixes the diagnosed inverse-chord geometries and residual twist schedule from
`output/birdman_outer_loading_diagnostic_smoke/spanload_design_smoke_report.json`.
Only the outer AVL airfoil assignment changes: root/mid1 stay `fx76mp140`, while
mid2/tip are replaced with DAE11, DAE21, DAE31, or DAE41.

Important limitation: this is an AVL camberline/loading check, not a 2D viscous
section-stall or drag validation. Use XFOIL at the listed Reynolds numbers before
treating any DAE section as feasible.

## Best DAE per sample

| sample | outer | e_CDi | RMS dGamma | max dGamma | outer mean Gamma ratio | outer min Gamma ratio | eta70 Cl | eta82 Cl | eta90 Cl | eta95 Cl |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 34 | dae31 | 0.899 | 0.102 | 0.197 | 0.725 | 0.672 | 0.854 | 0.726 | 0.653 | 0.590 |
| 55 | dae31 | 0.918 | 0.102 | 0.171 | 0.750 | 0.709 | 0.945 | 0.814 | 0.747 | 0.685 |
| 59 | dae31 | 0.915 | 0.144 | 0.239 | 0.667 | 0.629 | 0.892 | 0.773 | 0.721 | 0.677 |

## All cases

| sample | outer | e_CDi | RMS dGamma | max dGamma | outer mean Gamma ratio | outer min Gamma ratio | eta70 Cl | eta82 Cl | eta90 Cl | eta95 Cl |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 59 | clarkysm | 0.813 | 0.193 | 0.334 | 0.473 | 0.445 | 0.733 | 0.579 | 0.524 | 0.483 |
| 59 | dae11 | 0.887 | 0.159 | 0.270 | 0.604 | 0.570 | 0.842 | 0.713 | 0.660 | 0.617 |
| 59 | dae21 | 0.892 | 0.156 | 0.264 | 0.615 | 0.580 | 0.851 | 0.724 | 0.671 | 0.628 |
| 59 | dae31 | 0.915 | 0.144 | 0.239 | 0.667 | 0.629 | 0.892 | 0.773 | 0.721 | 0.677 |
| 59 | dae41 | 0.781 | 0.207 | 0.360 | 0.421 | 0.395 | 0.687 | 0.523 | 0.467 | 0.427 |
| 34 | clarkysm | 0.791 | 0.159 | 0.296 | 0.501 | 0.466 | 0.698 | 0.533 | 0.459 | 0.404 |
| 34 | dae11 | 0.868 | 0.120 | 0.229 | 0.654 | 0.606 | 0.805 | 0.667 | 0.593 | 0.533 |
| 34 | dae21 | 0.873 | 0.117 | 0.223 | 0.666 | 0.618 | 0.814 | 0.677 | 0.604 | 0.544 |
| 34 | dae31 | 0.899 | 0.102 | 0.197 | 0.725 | 0.672 | 0.854 | 0.726 | 0.653 | 0.590 |
| 34 | dae41 | 0.758 | 0.175 | 0.322 | 0.441 | 0.411 | 0.653 | 0.478 | 0.403 | 0.350 |
| 55 | clarkysm | 0.824 | 0.150 | 0.259 | 0.544 | 0.514 | 0.788 | 0.623 | 0.556 | 0.502 |
| 55 | dae11 | 0.892 | 0.116 | 0.199 | 0.684 | 0.647 | 0.896 | 0.755 | 0.688 | 0.629 |
| 55 | dae21 | 0.897 | 0.114 | 0.194 | 0.696 | 0.658 | 0.905 | 0.766 | 0.699 | 0.639 |
| 55 | dae31 | 0.918 | 0.102 | 0.171 | 0.750 | 0.709 | 0.945 | 0.814 | 0.747 | 0.685 |
| 55 | dae41 | 0.794 | 0.163 | 0.283 | 0.489 | 0.462 | 0.743 | 0.568 | 0.501 | 0.449 |

## Target Cl check

| sample | eta | target Cl | ClarkY Cl | best DAE | best DAE Cl | best Cl ratio | best Gamma ratio |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 34 | 0.70 | 1.105 | 0.698 | dae31 | 0.854 | 0.772 | 0.686 |
| 34 | 0.82 | 0.957 | 0.533 | dae31 | 0.726 | 0.759 | 0.672 |
| 34 | 0.90 | 0.782 | 0.459 | dae31 | 0.653 | 0.835 | 0.729 |
| 34 | 0.95 | 0.661 | 0.404 | dae31 | 0.590 | 0.893 | 0.814 |
| 55 | 0.70 | 1.154 | 0.788 | dae31 | 0.945 | 0.819 | 0.710 |
| 55 | 0.82 | 0.991 | 0.623 | dae31 | 0.814 | 0.821 | 0.709 |
| 55 | 0.90 | 0.842 | 0.556 | dae31 | 0.747 | 0.887 | 0.757 |
| 55 | 0.95 | 0.741 | 0.502 | dae31 | 0.685 | 0.925 | 0.823 |
| 59 | 0.70 | 1.134 | 0.733 | dae31 | 0.892 | 0.786 | 0.640 |
| 59 | 0.82 | 0.998 | 0.579 | dae31 | 0.773 | 0.774 | 0.629 |
| 59 | 0.90 | 0.872 | 0.524 | dae31 | 0.721 | 0.827 | 0.666 |
| 59 | 0.95 | 0.785 | 0.483 | dae31 | 0.677 | 0.862 | 0.731 |

## Engineering read

- DAE AVL cases run: `12` / `12` ok.
- DAE31 is the best fixed-geometry DAE option for all three samples.
- DAE31 clears the prior `e_CDi >= 0.85` gate for all three samples, but none of the best cases clears the stricter max target-vs-AVL circulation delta success gate.
- The ClarkY concern is real in this AVL check: replacing it with DAE31 raises outer mean circulation ratio by roughly 0.18-0.25 and improves e_CDi by about 0.09-0.11 absolute.
- This still does not fully match the Fourier target. Best outer circulation ratios remain around 0.67-0.75, so the outer wing is still underloaded in the fixed geometry.
- DAE41 is the wrong direction for this current incidence/twist schedule; it is worse than ClarkY on the main match metrics.

## Inputs

- Config: `configs/birdman_upstream_concept_baseline.yaml`
- Design speed: `6.8` m/s
- Design mass: `98.5` kg
- DAE files: `dae11`, `dae21`, `dae31`, `dae41`
- AVL cases: `/Volumes/Samsung SSD/hpa-mdo/output/dae_outer_airfoil_avl_match`
