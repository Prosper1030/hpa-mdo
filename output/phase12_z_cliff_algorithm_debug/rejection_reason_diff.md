# Rejection Reason Diff

## Case Summary

| z | coarse candidates | coarse feasible | all evaluated after probes | feasible after probes | reported selected mass kg | best after probes mass kg | reported selected signature |
|---:|---:|---:|---:|---:|---:|---:|---|
| 2.000 | 96 | 21 | 101 | 24 | 77.013607 | 75.514549 | `baseline_uniform|0.000000,0.000000,0.000000,0.000000,1.000000` |
| 2.025 | 96 | 24 | 101 | 25 | 15.518635 | 15.518635 | `baseline_uniform|1.000000,1.000000,1.000000,1.000000,0.000000` |

## Cross-Recipe Checks

- Lightest reported passing recipe at z=2.025 m: `baseline_uniform|1.000000,1.000000,1.000000,1.000000,0.000000`, tube mass 15.518635 kg.
- The same recipe **was evaluated** at z=2.000 m and failed: clearance margin -0.012759 m, dominant constraint `ground_clearance_margin_m`, reason `ground_clearance; negative_margins:ground_clearance_margin_m=-0.0127587863`.
- First reported-selected passing recipe at z=2.000 m: `baseline_uniform|0.000000,0.000000,0.000000,0.000000,1.000000`, tube mass 77.013607 kg.
- The z=2.000 m heavy recipe also appears at z=2.025 m and passed: clearance margin 0.065186 m, objective 79.546941 kg.

## Why Lighter z=2.000 m Recipes Failed

- Count of non-feasible candidates lighter than the reported z=2.000 m selection: 48.
- Dominant negative-margin counts among those lighter failures:
  - `ground_clearance_margin_m`: 39
  - `ei_dominance_margin_min_nm2`: 9

## Overall Failure Counts

### z=2.000 m
- `ground_clearance`: 36
- `geometry_validity`: 29
- `geometry_validity|ground_clearance`: 12
### z=2.025 m
- `ground_clearance`: 37
- `geometry_validity`: 27
- `geometry_validity|ground_clearance`: 12

## Forced Recipe Rows

- `force_z2p025_light_recipe_on_z2p000`: pass=False, tube=15.518635 kg, clearance=-0.012759 m, prebend=1.796789 m, reason=`ground_clearance; negative_margins:ground_clearance_margin_m=-0.0127587863`
- `force_z2p000_heavy_recipe_on_z2p025`: pass=True, tube=77.013607 kg, clearance=0.065186 m, prebend=0.118852 m, reason=`eligible_but_higher_objective_than_reported_selected`
