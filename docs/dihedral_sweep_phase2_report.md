# Phase-2 Dihedral Sweep Re-run (Task 7f)

Date: 2026-04-13

## Run setup

- Config: `configs/blackcat_004.yaml`
- AVL model: `data/blackcat_004_full.avl`
- Multipliers: `1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5`
- Output: `output/dihedral_sweep_phase2`

Command:

```bash
./.venv/bin/python scripts/dihedral_sweep_campaign.py \
  --config configs/blackcat_004.yaml \
  --base-avl data/blackcat_004_full.avl \
  --multipliers 1.0,1.25,1.5,1.75,2.0,2.25,2.5 \
  --output-dir output/dihedral_sweep_phase2
```

## Summary table

`overall = (aero_status == stable) AND (aero_performance_feasible) AND (structure_status == feasible)`

| multiplier | mass_kg | wire_margin_n | dutch_roll_damping (-real) | cl_trim | ld_ratio | aero_feasible | overall |
|---:|---:|---:|---:|---:|---:|:---:|:---:|
| 1.00 | 24.970 | 3800.9 | 5.94463 | 1.23521 | 45.319 | yes | yes |
| 1.25 | 22.103 | 3649.0 | 5.93600 | 1.23521 | 45.114 | yes | yes |
| 1.50 | 19.681 | 3537.2 | 5.92553 | 1.23521 | 44.910 | yes | yes |
| 1.75 | 15.681 | 3277.2 | 5.91334 | 1.23521 | 44.705 | yes | yes |
| 2.00 | 14.563 | 3155.6 | 5.89953 | 1.23521 | 44.500 | yes | yes |
| 2.25 | 13.810 | 3063.7 | 5.88424 | 1.23521 | 44.295 | yes | yes |
| 2.50 | 13.102 | 2997.7 | 5.86758 | 1.23521 | 44.088 | yes | yes |

## Key findings

- Lightest case with all gates passed: **x2.50** (`13.102 kg`, overall yes).
- Highest L/D case: **x1.00** (`L/D = 45.319`).
- Strongest Dutch Roll damping case: **x1.00** (`-real = 5.94463`, most negative real part).
- Wire margin check: all cases are positive (`2997.7 N` to `3800.9 N`), so no wire-limit violation.

## Trade-off notes

- Increasing dihedral multiplier reduces structural mass monotonically.
- Increasing dihedral also reduces aerodynamic efficiency (`L/D`) and Dutch Roll damping monotonically in this sweep.
- This creates a clear trade-off: **x2.50** is best for mass, while **x1.00** is best for aero efficiency and damping.

## Gate failures

- No stability gate failures (`aero_status = stable` for all cases).
- No aero performance gate failures (`aero_performance_feasible = true` for all cases).
- No structural feasibility failures (`structure_status = feasible` for all cases).
