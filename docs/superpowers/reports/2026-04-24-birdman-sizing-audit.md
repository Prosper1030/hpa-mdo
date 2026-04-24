# Birdman Upstream Sizing Audit

Date: 2026-04-24
Workspace: `/Volumes/Samsung SSD/hpa-mdo`

## Purpose

This is a diagnosis-only audit of the current upstream Birdman concept line after
the low-speed box study. It does not expand `wing_area_m2`, lower
`wing_loading_target_Npm2`, change the optimizer, add design variables, change the
airfoil family, change the tail model, or reload quasi-3D physics.

The specific concern is that the promoted `box_B` top concept
(`S ~= 48.6 m^2`, `W/S ~= 21.2 N/m^2`) may not be a true optimum. It may instead
be an artifact of:

- a 6 m/s low-speed local-stall gate,
- fixed gross mass,
- no area-coupled wing structural mass feedback,
- and a mission model that still fails badly after the low-speed gate is nearly
  satisfied.

## Sources

- Baseline control:
  `.tmp/birdman_upstream_smoke_out/concept_summary.json`
- `box_A` exploratory run:
  `output/birdman_upstream_frontier_box_a_explore16_20260424/concept_ranked_pool.json`
- `box_B` promoted run:
  `output/birdman_upstream_frontier_box_b_promote24_20260424/concept_ranked_pool.json`

All three cases use the same mass contract:

- `pilot_mass_kg = 60.0`
- `baseline_aircraft_mass_kg = 40.0`
- `gross_mass_sweep_kg = [95.0, 100.0, 105.0]`
- `design_gross_mass_kg = 105.0`

No area-coupled wing structural mass field was found in the current concept
configuration or top-ranked records.

## Top Concept Sizing Table

`CL_avg_at_V = (W/S) / (0.5 * rho * V^2)`, using the run's launch-air density
`rho = 1.135668544 kg/m^3`.

The estimated drag components below are evaluated at the critical local-stall
case speed, which is 6.0 m/s for all three top concepts. The profile component is
the mission proxy non-induced component:
`q S (profile_cd_proxy + misc_cd_proxy + trim_drag_cd_proxy)`. The induced
component is `q S CL^2 / (pi AR e)`.

| case | concept | span_m | wing_area_m2 | aspect_ratio | wing_loading_target_Npm2 | design_gross_mass_kg | best_range_speed_mps | critical_stall_case_speed_mps | CL_avg_at_6mps | CL_avg_at_7mps | CL_avg_at_8mps | local_stall_margin | mission_margin_km | estimated_profile_drag_component_N | estimated_induced_drag_component_N | structural_mass_assumption |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| baseline smoke top | infeasible-01 | 33.920 | 34.833 | 33.030 | 29.561 | 105.0 | n/a | 6.0 | 1.446 | 1.062 | 0.813 | -0.098 | -42.195 | 17.108 | 18.606 | fixed gross mass; no area feedback |
| box_A top | eval-07 | 35.461 | 42.243 | 29.768 | 24.375 | 105.0 | 6.5 | 6.0 | 1.192 | 0.876 | 0.671 | 0.062 | -21.681 | 11.938 | 16.227 | fixed gross mass; no area feedback |
| box_B promoted top | eval-16 | 34.460 | 48.601 | 24.433 | 21.187 | 105.0 | 6.0 | 6.0 | 1.036 | 0.761 | 0.583 | 0.245 | -23.772 | 13.340 | 17.023 | fixed gross mass; no area feedback |

Important interpretation:

- Baseline is not even able to produce a feasible mission operating-point speed
  after stall filtering.
- `box_A` clears launch and turn, but still fails the 6 m/s local-stall gate and
  misses the 42.195 km mission by about 21.7 km at the 105 kg case.
- `box_B` promoted nearly satisfies the 6 m/s local-stall gate
  (`stall_utilization = 0.8003` against a `0.8000` limit; extra area needed only
  `0.019 m^2`), but the mission still misses by about 23.8 km.
- Moving from `box_A` to `box_B` improves the 6 m/s stall condition, but the
  worst-case mission range gets worse (`20.5 km` to `18.4 km`) because the design
  has become a larger, lower-AR, lower-speed aircraft.

## Mass Sensitivity

The current ranking is highly mass-sensitive. This matters because the current
pipeline holds design gross mass fixed while wing area changes.

| case | gross_mass_kg | best_range_km | best_range_speed_mps | mission_margin_km | mission limiter | power_at_best_feasible_w |
| --- | ---: | ---: | ---: | ---: | --- | ---: |
| baseline | 95 | 0.000 | n/a | -42.195 | stall_operating_point_unavailable | n/a |
| baseline | 100 | 0.000 | n/a | -42.195 | stall_operating_point_unavailable | n/a |
| baseline | 105 | 0.000 | n/a | -42.195 | stall_operating_point_unavailable | n/a |
| box_A | 95 | 47.213 | 6.5 | 5.018 | target_range_met | 210.364 |
| box_A | 100 | 32.231 | 6.5 | -9.964 | endurance_shortfall_at_best_feasible_speed | 219.678 |
| box_A | 105 | 20.514 | 6.5 | -21.681 | endurance_shortfall_at_best_feasible_speed | 229.399 |
| box_B promoted | 95 | 43.378 | 6.0 | 1.183 | target_range_met | 210.703 |
| box_B promoted | 100 | 28.148 | 6.0 | -14.047 | endurance_shortfall_at_best_feasible_speed | 221.362 |
| box_B promoted | 105 | 18.423 | 6.0 | -23.772 | endurance_shortfall_at_best_feasible_speed | 232.477 |

Engineering read:

- At 95 kg, both `box_A` and `box_B` can pass the target range.
- At 105 kg, both fail badly.
- Because larger wings should normally add structural mass, a fixed 105 kg gross
  mass while increasing area is optimistic. If structural mass feedback were
  added, the `box_B` promoted concept would likely move further away from mission
  feasibility rather than closer.

## Historical Sanity Check

These references are used as sanity checks only, not hard gates.

| aircraft / archetype | S_m2 | b_m | AR | W/S_Npm2 | speed_mps | comparison to current box_B promoted top |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Light Eagle / Daedalus type | ~31 | ~34.7 | ~39.4 | ~37 | ~7.8 | Similar span, but much smaller area, much higher AR, and much higher wing loading. |
| Gossamer Albatross type | ~46 | ~29 | ~19 | n/a | ~5 | Similar large area and slow-speed character, but not the same long-distance high-efficiency class. |
| Windnauts-like high-AR Birdman | ~28 | ~33 | ~39 | n/a | n/a | Similar span family, but far smaller area and much higher AR. |
| S-230 Cygnus | ~49.7 | ~38 | ~29.1 | ~38 | n/a | Similar area scale, but at about 193 kg all-up mass; its wing loading is far above the current `21.2 N/m^2`. |

The promoted `box_B` concept is therefore not a clean match to the
high-efficiency Daedalus / Light Eagle family:

- It has Light-Eagle-like span scale (`34.5 m`) but not Light-Eagle-like area,
  AR, or wing loading.
- It has Gossamer-like wing area (`48.6 m^2`) and very low-speed behavior, but
  the current mission is a long-distance Birdman mission, not purely a
  lowest-speed crossing concept.
- It has S-230-like area scale, but the mass and wing loading are completely
  different: `105 kg` and `21.2 N/m^2` here versus about `193 kg` and
  `38 N/m^2` for S-230.

Classification: the `box_B` promoted top concept is best treated as a physically
suspicious sizing artifact for the current long-range Birdman objective. It is
not automatically impossible as a 6 m/s ultra-low-speed aircraft, but it is not a
credible long-distance high-efficiency optimum under the current missing
structural-mass feedback.

## Formula Audit

`S = W / (W/S)` is correct. The issue is how it is currently being used.

1. Gross mass is fixed while area changes.
   The config keeps `design_gross_mass_kg = 105.0` and sweeps only
   `[95, 100, 105] kg`. Larger wing area does not increase empty mass.

2. There is no wing structural mass penalty.
   The current top-ranked records have no area-coupled structural mass
   assumption. This allows the search to buy lower stall CL by increasing area
   at nearly no mass cost.

3. The 6 m/s gate is acting like the dominant sizing speed.
   The critical local-stall case for all three top concepts is `slow_avl_case`
   at 6.0 m/s. The promoted `box_B` concept is essentially sized to make
   `CL_avg_at_6mps ~= 1.04` and barely reach the local-stall utilization limit.

4. Local stall is forcing an area solution.
   The progression is monotonic:
   `S = 34.8 -> 42.2 -> 48.6 m^2`, while
   `W/S = 29.6 -> 24.4 -> 21.2 N/m^2`.
   This is exactly the direction expected if the optimizer is using area to
   satisfy a fixed low-speed stall requirement.

5. Mission failure remains too large to justify continuing area growth.
   `box_B` is nearly stall-feasible at 6 m/s, yet the 105 kg mission margin is
   still `-23.8 km`. More area is therefore not the main engineering lever
   anymore. It would likely increase profile-like drag and, in a real model,
   structural mass.

## Answers To The Sizing Questions

If the target is 6 m/s ultra-low-speed flight, `S ~= 48..50 m^2` is plausible as
a Gossamer-like scale at the current fixed 105 kg mass:

- `W/S ~= 21 N/m^2`
- `CL_avg_at_6mps ~= 1.0`
- local-stall utilization sits almost exactly on the current 0.80 limit

That does not make it a good long-distance Birdman optimum. It only says the
current model's 6 m/s gate mathematically wants that wing loading.

If the target is 7.5 to 8.0 m/s long-distance high-efficiency Birdman flight,
the sanity-check range should look much closer to:

- `S ~= 28..34 m^2` for a roughly 105 kg all-up mass,
- `AR ~= 35..40` if span remains around `33..36 m`,
- `W/S ~= 30..38 N/m^2`,
- not `S ~= 49 m^2`, `AR ~= 24`, `W/S ~= 21 N/m^2`.

The current pipeline is therefore very likely steering the design toward the
wrong archetype: a very slow, large-area concept, not a Light-Eagle-like or
modern high-AR Birdman concept.

## Engineering Conclusion

The previous conclusion that the old box was too small is still true in a
narrow numerical sense: the baseline box could not let the low-speed frontier
reach the 6 m/s stall edge. But the promoted `box_B` result should not be
interpreted as "keep increasing area."

The better conclusion is:

- The search has reached the 6 m/s local-stall frontier.
- Launch and turn are no longer the top blockers for the promoted concept.
- The remaining hard wall is mission endurance / power / mass sensitivity.
- Because wing structural mass does not grow with area, the current large-area
  optimum is probably optimistic and physically suspicious.
- The next engineering step should be to audit the mission speed/power/mass
  assumptions before opening the area box further.

Recommended next work:

1. Add a report-only sizing archetype check to every frontier summary:
   `S`, `AR`, `W/S`, `CL_avg` at 6/7/8 m/s, and historical-reference distance.
2. Add a lightweight wing structural mass feedback model or at least a
   sensitivity sweep before trusting any `S > 45 m^2` concept.
3. Revisit whether 6 m/s should be a hard sizing point for this long-distance
   Birdman concept, or whether the primary design speed should be closer to the
   7.5 to 8.0 m/s high-efficiency family.
4. Do not expand the `wing_area_m2` upper bound again until the above checks are
   complete.
