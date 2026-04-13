# Multi-Wire Sweep Report (Task 9b)

Date: 2026-04-13

## Run Setup

- Config: `configs/blackcat_004.yaml`
- AVL model: `data/blackcat_004_full.avl`
- Dihedral multipliers: `1.0, 2.5, 3.0, 3.1, 3.2, 3.3, 3.4, 3.5`
- Wire layouts:
  - `single = [7.5]`
  - `dual = [4.5, 10.5]`
  - `triple = [4.5, 7.5, 10.5]`
- Wire drag penalty: `ΔCD = 0.003 × wire_count`
- Output: `output/multi_wire_sweep_phase9b`

Command:

```bash
./.venv/bin/python scripts/multi_wire_sweep_campaign.py \
  --config configs/blackcat_004.yaml \
  --base-avl data/blackcat_004_full.avl \
  --output-dir output/multi_wire_sweep_phase9b \
  --skip-step-export
```

## Summary

`overall = stable Dutch Roll AND aero gates passed AND structure feasible`

| layout | multiplier | mass_kg | min_wire_margin_n | ld_ratio | dutch_roll_damping (-real) | overall |
|:--|---:|---:|---:|---:|---:|:---:|
| single | 1.0 | 24.970 | 3800.9 | 40.83 | 5.94463 | yes |
| single | 2.5 | 13.145 | 2995.6 | 40.04 | 5.87170 | yes |
| single | 3.0 | 12.472 | 2960.0 | 39.85 | 5.83675 | yes |
| single | 3.1 | 12.494 | 2975.2 | 39.81 | 5.82953 | yes |
| single | 3.2 | 12.251 | 2948.0 | 39.76 | 5.82221 | yes |
| single | 3.3 | 12.171 | 2942.6 | 39.72 | 5.81480 | yes |
| single | 3.4 | 12.132 | 2940.9 | 39.67 | 5.80731 | yes |
| single | 3.5 | 11.988 | 2932.7 | 39.63 | 5.79975 | yes |
| dual | 1.0 | 20.389 | 4336.3 | 37.14 | 5.94463 | yes |
| dual | 2.5 | 16.440 | 4175.3 | 36.49 | 5.87170 | yes |
| dual | 3.0 | 15.487 | 4137.3 | 36.34 | 5.83675 | yes |
| dual | 3.1 | 15.364 | 4134.9 | 36.30 | 5.82953 | yes |
| dual | 3.2 | 15.165 | 4123.4 | 36.26 | 5.82221 | yes |
| dual | 3.3 | 15.007 | 4118.4 | 36.22 | 5.81480 | yes |
| dual | 3.4 | 14.949 | 4114.1 | 36.19 | 5.80731 | yes |
| dual | 3.5 | 14.708 | 4105.1 | 36.15 | 5.79975 | yes |
| triple | 1.0 | 20.414 | 4356.8 | 34.07 | 5.94463 | yes |
| triple | 2.5 | 16.441 | 4176.5 | 33.52 | 5.87170 | yes |
| triple | 3.0 | 15.484 | 4134.0 | 33.39 | 5.83675 | yes |
| triple | 3.1 | 15.637 | 4197.8 | 33.36 | 5.82953 | yes |
| triple | 3.2 | 15.158 | 4119.7 | 33.33 | 5.82221 | yes |
| triple | 3.3 | 15.004 | 4110.8 | 33.30 | 5.81480 | yes |
| triple | 3.4 | 14.883 | 4106.7 | 33.26 | 5.80731 | yes |
| triple | 3.5 | 14.868 | 4102.4 | 33.23 | 5.79975 | yes |

## Key Findings

- All 24 cases passed stability, aero performance, and structural feasibility gates.
- Lightest overall case remains `single x3.5 = 11.988 kg`.
- Best aerodynamic efficiency also remains `single x1.0 = L/D 40.83`.
- Dutch Roll damping is unchanged across layouts at fixed dihedral because the current wire model
  only penalizes drag in the trim/L-D estimate, not AVL geometry or inertia.

## Wire-Count Tradeoff

- In the low-dihedral regime, extra wires help structure:
  - `x1.0 single = 24.970 kg`
  - `x1.0 dual = 20.389 kg`
  - `x1.0 triple = 20.414 kg`
- In the high-dihedral regime, extra wires lose badly once drag is priced in:
  - `x3.5 single = 11.988 kg`
  - `x3.5 dual = 14.708 kg`
  - `x3.5 triple = 14.868 kg`
- Dual/triple layouts buy about `+1.17 kN` extra minimum wire margin at `x3.5`, but cost
  about `+2.7 to +2.9 kg` and noticeably worse `L/D`.
- Triple wire does not beat dual wire in any sampled region here; it is essentially "more drag,
  similar mass, slightly more margin."

## Engineering Interpretation

- High target dihedral has already replaced extra wire count as the dominant structural lever.
- For the currently sampled high-dihedral window, the best design direction is:
  `single wire + high progressive dihedral`.
- The remaining open question is not "should we go above 3.5?".
  It is "where is the crossover between low-dihedral multi-wire benefit and high-dihedral
  single-wire benefit?" That crossover likely sits somewhere between `x1.0` and `x2.5`.

## Recommended Next Step

Proceed to `9c multi-objective Pareto front`, using:

1. `single x3.2–x3.5` as the high-performance family.
2. `dual/triple x1.0` as low-dihedral structural-support reference points.

If we later need a sharper wire-count crossover boundary, run one focused bridge sweep in the
missing region `x1.5 → x2.2`.
