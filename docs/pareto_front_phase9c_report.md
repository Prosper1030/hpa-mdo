# Phase 9c Pareto Front Report

Date: 2026-04-13

## Inputs

- Single-wire sweep summaries: /Volumes/Samsung SSD/hpa-mdo/output/dihedral_sweep_phase9a/dihedral_sweep_summary.csv, /Volumes/Samsung SSD/hpa-mdo/output/dihedral_sweep_phase9a_extension/dihedral_sweep_summary.csv, /Volumes/Samsung SSD/hpa-mdo/output/dihedral_sweep_extreme_probe_01/dihedral_sweep_summary.csv, /Volumes/Samsung SSD/hpa-mdo/output/dihedral_sweep_extreme_probe_02/dihedral_sweep_summary.csv, /Volumes/Samsung SSD/hpa-mdo/output/dihedral_sweep_extreme_probe_03/dihedral_sweep_summary.csv
- Multi-wire sweep summary: `/Volumes/Samsung SSD/hpa-mdo/output/multi_wire_sweep_phase9b/multi_wire_sweep_summary.csv`
- Fair-comparison correction for single-wire points: `ΔCD = 0.003 × wire_count`

## Dataset

- Feasible design points considered: `54`
- Pareto-optimal points: `21`
- Pareto layouts represented: `dual, single`

## Representative Designs

| role | design | mass_kg | wire_count | ld_ratio | dutch_roll_damping | aoa_trim_deg | clearance_mm |
|---|---|---:|---:|---:|---:|---:|---:|
| mass_first | `single x5.000` | 11.954 | 1 | 40.19 | 5.84871 | 11.62094 | 5.588 |
| aero_first | `single x1.000` | 24.970 | 1 | 40.83 | 5.94463 | 10.98762 | 0.000 |
| stability_first | `single x1.000` | 24.970 | 1 | 40.83 | 5.94463 | 10.98762 | 0.000 |
| balanced | `single x2.000` | 14.813 | 1 | 40.28 | 5.90195 | 11.10606 | 1.492 |

## Pareto Frontier

| design | mass_kg | wire_count | ld_ratio | dutch_roll_damping | aoa_trim_deg | clearance_mm | tip_deflection_m |
|---|---:|---:|---:|---:|---:|---:|---:|
| `single x5.000` | 11.954 | 1 | 40.19 | 5.84871 | 11.62094 | 5.588 | 2.426 |
| `single x2.800` | 12.763 | 1 | 39.90 | 5.85151 | 11.26271 | 6.585 | 1.926 |
| `single x2.700` | 12.875 | 1 | 39.95 | 5.85839 | 11.24069 | 6.357 | 1.837 |
| `single x2.600` | 13.008 | 1 | 40.00 | 5.86512 | 11.21930 | 6.622 | 1.762 |
| `single x2.500` | 13.145 | 1 | 40.04 | 5.87170 | 11.19859 | 6.369 | 1.685 |
| `single x2.400` | 13.290 | 1 | 40.09 | 5.87812 | 11.17857 | 6.187 | 1.607 |
| `single x2.300` | 13.736 | 1 | 40.14 | 5.88437 | 11.15928 | 4.506 | 1.511 |
| `single x2.200` | 13.921 | 1 | 40.19 | 5.89043 | 11.14074 | 4.226 | 1.435 |
| `single x2.100` | 14.377 | 1 | 40.23 | 5.89629 | 11.12300 | 1.586 | 1.465 |
| `single x2.000` | 14.813 | 1 | 40.28 | 5.90195 | 11.10606 | 1.492 | 1.425 |
| `single x1.900` | 17.440 | 1 | 40.33 | 5.90739 | 11.08998 | 2.792 | 1.305 |
| `single x1.800` | 17.834 | 1 | 40.38 | 5.91259 | 11.07476 | 2.724 | 1.317 |
| `single x1.700` | 18.460 | 1 | 40.43 | 5.91755 | 11.06045 | 4.654 | 1.239 |
| `single x1.600` | 19.155 | 1 | 40.49 | 5.92226 | 11.04707 | 6.135 | 1.162 |
| `single x1.500` | 19.963 | 1 | 40.54 | 5.92671 | 11.03464 | 6.395 | 1.082 |
| `dual x1.000` | 20.389 | 2 | 37.14 | 5.94463 | 10.98762 | 0.000 | 0.162 |
| `single x1.400` | 20.802 | 1 | 40.60 | 5.93088 | 11.02318 | 4.892 | 1.004 |
| `single x1.300` | 21.811 | 1 | 40.65 | 5.93477 | 11.01274 | 3.310 | 0.928 |
| `single x1.200` | 22.764 | 1 | 40.71 | 5.93836 | 11.00331 | 1.646 | 0.849 |
| `single x1.100` | 23.712 | 1 | 40.77 | 5.94165 | 10.99493 | 0.019 | 0.772 |
| `single x1.000` | 24.970 | 1 | 40.83 | 5.94463 | 10.98762 | 0.000 | 0.695 |

## Key Findings

- Mass-first representative is `single x5.000`.
- Aero-first representative is `single x1.000`.
- Stability-first representative is `single x1.000`.
- Balanced compromise representative is `single x2.000`.
- Triple-wire cases are absent from the frontier when compared against dual-wire and single-wire points under the current objectives.
- The single-wire high-dihedral plateau stays on the frontier because it dominates on mass and wire-count while accepting some damping loss.
- The low-dihedral dual-wire family remains relevant because it preserves the strongest Dutch Roll damping while staying much lighter than `single x1.0`.

## Interpretation

- The multiplier limit for the single-wire family is now governed by the trim AoA gate near `x6.30`, not by structure.
- For the current four-objective formulation (`mass`, `wire_count`, `L/D`, `Dutch Roll damping`), the design space naturally separates into a low-wire-count / low-mass branch and a low-dihedral / higher-damping branch.
- This means 9d should build on a much smaller candidate family instead of the full sweep tables.
