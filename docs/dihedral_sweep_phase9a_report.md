# Fine Dihedral Sweep Report (Task 9a)

Date: 2026-04-13

## Run Setup

- Config: `configs/blackcat_004.yaml`
- AVL model: `data/blackcat_004_full.avl`
- Dihedral scaling: progressive (`wing.dihedral_scaling_exponent = 1.0`)
- Multipliers: `1.0 → 3.5` with `step = 0.1` (26 cases)
- Baseline wire geometry: single wire at `y = 7.5 m`, `fuselage_z = -1.5 m`, `wire_angle = 11.3 deg`
- Output: `output/dihedral_sweep_phase9a`

Command:

```bash
./.venv/bin/python scripts/dihedral_sweep_campaign.py \
  --config configs/blackcat_004.yaml \
  --base-avl data/blackcat_004_full.avl \
  --multipliers 1.0,1.1,1.2,1.3,1.4,1.5,1.6,1.7,1.8,1.9,2.0,2.1,2.2,2.3,2.4,2.5,2.6,2.7,2.8,2.9,3.0,3.1,3.2,3.3,3.4,3.5 \
  --output-dir output/dihedral_sweep_phase9a
```

## Summary

`overall = stable Dutch Roll AND aero gates passed AND structure feasible`

| multiplier | mass_kg | wire_margin_n | dutch_roll_damping (-real) | ld_ratio | clearance_mm | overall |
|---:|---:|---:|---:|---:|---:|:---:|
| 1.0 | 24.970 | 3800.9 | 5.94463 | 45.319 | 0.000 | yes |
| 1.1 | 23.712 | 3731.4 | 5.94165 | 45.246 | 0.019 | yes |
| 1.2 | 22.764 | 3679.2 | 5.93836 | 45.174 | 1.646 | yes |
| 1.3 | 21.811 | 3618.6 | 5.93477 | 45.104 | 3.310 | yes |
| 1.4 | 20.802 | 3572.1 | 5.93088 | 45.035 | 4.892 | yes |
| 1.5 | 19.963 | 3530.4 | 5.92671 | 44.968 | 6.395 | yes |
| 1.6 | 19.155 | 3509.4 | 5.92226 | 44.903 | 6.135 | yes |
| 1.7 | 18.460 | 3471.7 | 5.91755 | 44.838 | 4.654 | yes |
| 1.8 | 17.834 | 3444.0 | 5.91259 | 44.775 | 2.724 | yes |
| 1.9 | 17.440 | 3254.3 | 5.90739 | 44.713 | 2.792 | yes |
| 2.0 | 14.813 | 3177.2 | 5.90195 | 44.652 | 1.492 | yes |
| 2.1 | 14.377 | 3132.9 | 5.89629 | 44.591 | 1.586 | yes |
| 2.2 | 13.921 | 3072.3 | 5.89043 | 44.532 | 4.226 | yes |
| 2.3 | 13.736 | 3059.6 | 5.88437 | 44.473 | 4.506 | yes |
| 2.4 | 13.290 | 3003.8 | 5.87812 | 44.415 | 6.187 | yes |
| 2.5 | 13.145 | 2995.6 | 5.87170 | 44.357 | 6.369 | yes |
| 2.6 | 13.008 | 2987.8 | 5.86512 | 44.299 | 6.622 | yes |
| 2.7 | 12.875 | 2980.4 | 5.85839 | 44.242 | 6.357 | yes |
| 2.8 | 12.763 | 2973.8 | 5.85151 | 44.185 | 6.585 | yes |
| 2.9 | 12.648 | 2967.0 | 5.84373 | 44.150 | 6.405 | yes |
| 3.0 | 12.472 | 2960.0 | 5.83675 | 44.123 | 1.491 | yes |
| 3.1 | 12.494 | 2975.2 | 5.82953 | 44.069 | 2.699 | yes |
| 3.2 | 12.251 | 2948.0 | 5.82221 | 44.015 | 1.048 | yes |
| 3.3 | 12.171 | 2942.6 | 5.81480 | 43.960 | 2.520 | yes |
| 3.4 | 12.132 | 2940.9 | 5.80731 | 43.906 | 4.420 | yes |
| 3.5 | 11.988 | 2932.7 | 5.79975 | 43.851 | 2.049 | yes |

## Key Findings

- All 26 cases passed stability, aero performance, and structural feasibility gates.
- Within the original `1.0 → 3.5` sweep, the lightest feasible case is `x3.5`, `11.988 kg`.
- Relative to `x1.0`, `x3.5` reduces structural mass by about `52.0%`.
- Highest L/D and strongest Dutch Roll damping remain at `x1.0`, but degradation at `x3.5` is mild:
  `L/D 45.319 → 43.851` (`-3.24%`), damping `5.94463 → 5.79975` (`-2.44%`).
- Maximum wire tension occurs at `x3.5`: `3939.5 N`, still leaving `2932.7 N` positive margin.
- Mass trend is almost monotonic downward across the whole range, with one small local regression:
  `x3.0 = 12.472 kg`, `x3.1 = 12.494 kg`, then dropping again from `x3.2` onward.
- Clearance is not monotonic in the high-dihedral regime; `x3.4` has noticeably better jig clearance
  than `x3.0`, `x3.2`, and `x3.5` despite very similar mass.

## Deflection Snapshot

`loaded tip z` is the height relative to the global horizontal/root reference plane. `max uz` is the
elastic deflection increment relative to the jig / undeformed structure.

| case | equivalent_tip_deflection_m | main_tip_z_m | rear_tip_z_m | main_max_uz_m | rear_max_uz_m | note |
|---|---:|---:|---:|---:|---:|---|
| `x3.5` | 2.417 | 3.127 | 3.123 | 2.317 | 3.116 | below `2.5 m` tip-deflection gate |
| `x4.0` probe | 2.426 | 3.573 | 3.569 | 2.323 | 3.138 | still below `2.5 m` tip-deflection gate |

## Extension Probe Above `x3.5`

A focused follow-up probe was also run for `3.6 → 4.0`:

```bash
./.venv/bin/python scripts/dihedral_sweep_campaign.py \
  --config configs/blackcat_004.yaml \
  --base-avl data/blackcat_004_full.avl \
  --multipliers 3.6,3.7,3.8,3.9,4.0 \
  --output-dir output/dihedral_sweep_phase9a_extension \
  --skip-step-export
```

| multiplier | mass_kg | ld_ratio | clearance_mm | equivalent_tip_deflection_m | overall |
|---:|---:|---:|---:|---:|:---:|
| 3.6 | 11.954 | 43.80 | 1.695 | 2.426 | yes |
| 3.7 | 11.954 | 43.74 | 1.973 | 2.426 | yes |
| 3.8 | 11.954 | 43.68 | 2.251 | 2.426 | yes |
| 3.9 | 11.954 | 43.63 | 2.529 | 2.426 | yes |
| 4.0 | 11.954 | 43.54 | 2.807 | 2.426 | yes |

## Extreme Upper-Bound Probe

To find the first real failure point, the multiplier was then pushed upward until a gate broke:

```bash
./.venv/bin/python scripts/dihedral_sweep_campaign.py \
  --config configs/blackcat_004.yaml \
  --base-avl data/blackcat_004_full.avl \
  --multipliers 4.5,5.0,6.0,7.5,10.0 \
  --output-dir output/dihedral_sweep_extreme_probe_01 \
  --skip-step-export

./.venv/bin/python scripts/dihedral_sweep_campaign.py \
  --config configs/blackcat_004.yaml \
  --base-avl data/blackcat_004_full.avl \
  --multipliers 6.2,6.4,6.6,6.8,7.0,7.2,7.4 \
  --output-dir output/dihedral_sweep_extreme_probe_02 \
  --skip-step-export

./.venv/bin/python scripts/dihedral_sweep_campaign.py \
  --config configs/blackcat_004.yaml \
  --base-avl data/blackcat_004_full.avl \
  --multipliers 6.24,6.26,6.28,6.30,6.32,6.34,6.36,6.38 \
  --output-dir output/dihedral_sweep_extreme_probe_03 \
  --skip-step-export
```

| multiplier | aoa_trim_deg | ld_ratio | structure_status | result |
|---:|---:|---:|:---:|---|
| 6.00 | 11.91373 | 43.99 | feasible | pass |
| 6.24 | 11.98492 | 43.83 | feasible | pass |
| 6.26 | 11.99086 | 43.81 | feasible | pass |
| 6.28 | 11.99680 | 43.80 | feasible | last pass |
| 6.30 | 12.00274 | 43.78 | skipped | first fail: `trim_aoa_exceeds_limit` |
| 7.50 | 12.36448 | 42.88 | skipped | trim AoA gate fail |
| 10.00 | 13.22147 | 40.28 | skipped | trim AoA gate fail |

- The limiter is therefore the aero performance gate, not structure.
- `single x6.28` still keeps the low-mass plateau: `11.954 kg`, `9.148 mm` clearance,
  `equivalent_tip_deflection = 2.426 m`.
- The first sampled failure appears immediately at `x6.30`, where trim AoA crosses the
  configured `12.0 deg` ceiling.

## Engineering Interpretation

- Progressive dihedral scaling keeps paying off well beyond the old `x2.5` ceiling.
- The dominant trade-off is no longer a hard aero/stability gate. It is now a softer choice between:
  the wide low-mass plateau (`x3.6 → x6.28 = 11.954 kg`), more clearance as dihedral rises, and
  slightly stronger damping / L/D at lower multipliers.
- The real upper bound is now known: the first sampled failure is `x6.30`, caused by
  `trim_aoa_exceeds_limit`, not by structural infeasibility or tip-deflection violation.
- The main unanswered question is therefore not "how far can dihedral go?".
  It is how this broad high-dihedral single-wire plateau compares against multi-wire families
  once drag is priced in.

## Recommended Next Step

With `9b` now complete, proceed to `9c multi-objective Pareto front` using:

1. `single x3.6 → x6.28` as the high-dihedral low-mass family.
2. `dual/triple x1.0` as low-dihedral structural-support reference points.
3. One optional crossover bridge in `x1.5 → x2.2` if we later need a sharper handoff boundary.

This keeps the entire feasible plateau in scope while avoiding values at or above `x6.30`, where the
trim AoA gate already starts failing.
