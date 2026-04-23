# Birdman Upstream Frontier Low-Speed Box Study

Date: 2026-04-24
Workspace: `/Volumes/Samsung SSD/hpa-mdo`

## Goal

Check whether the new sizing-oriented parameterization is still being limited by a too-small low-speed sizing box, and quantify how far the feasibility frontier moves when we lower `wing_loading_target_Npm2` and allow larger derived `wing_area_m2`.

## Configs Added

- `configs/birdman_upstream_concept_box_a.yaml`
- `configs/birdman_upstream_concept_box_a_smoke.yaml`
- `configs/birdman_upstream_concept_box_b.yaml`
- `configs/birdman_upstream_concept_box_b_smoke.yaml`

Box definitions:

- baseline control:
  - `wing_loading_target_Npm2 = 26..34`
  - `wing_area_m2_range = 28..42`
- box_A:
  - `wing_loading_target_Npm2 = 22..34`
  - `wing_area_m2_range = 28..48`
- box_B:
  - `wing_loading_target_Npm2 = 19..34`
  - `wing_area_m2_range = 28..54`

All other major design dimensions stayed aligned with the current upstream line:

- `span_m = 30..36`
- `taper_ratio = 0.24..0.40`
- `tip_twist_deg = -3.0..-0.5`
- same tail candidates
- same airfoil family / CST route
- same mission / launch / turn / trim / stall contracts

## Actual Runs

Shared real-XFOIL cache driver:

- shared cache:
  - `output/birdman_upstream_frontier_shared_cache_20260424/polar_db`

Executed cases:

- box_A exploratory:
  - config: `.tmp/birdman_frontier_configs/box_a_explore16.yaml`
  - sample count: `16`
  - worker mode: `julia`
  - output: `output/birdman_upstream_frontier_box_a_explore16_20260424`
- box_B exploratory:
  - config: `.tmp/birdman_frontier_configs/box_b_explore16.yaml`
  - sample count: `16`
  - worker mode: `julia`
  - output: `output/birdman_upstream_frontier_box_b_explore16_20260424`
- box_B promoted run:
  - config: `.tmp/birdman_frontier_configs/box_b_promote24.yaml`
  - sample count: `24`
  - worker mode: `julia`
  - output: `output/birdman_upstream_frontier_box_b_promote24_20260424`

Comparison helper output:

- `output/birdman_upstream_frontier_compare_all_20260424/frontier_comparison.json`
- `output/birdman_upstream_frontier_compare_all_20260424/frontier_comparison.md`

## Baseline Control

For same-line control, use:

- `.tmp/birdman_upstream_smoke_out/concept_summary.json`

This current-line control is enough to compare failure-mode movement even though it is a smaller smoke than the new box study.

Fresh cold baseline rerun was started with real XFOIL, but stopped after a long cold-path wait because this turn was better spent on the requested A/B frontier comparison. The slow cold-path behavior itself is consistent with the earlier 2026-04-23 benchmark note that low-Re viscous solving remains the runtime bottleneck.

Baseline control top-ranked infeasible signal:

- top concept:
  - `W/S = 29.56 N/m^2`
  - `S = 34.83 m^2`
  - `AR = 33.03`
- failed gates:
  - `launch`
  - `turn`
  - `local_stall`
  - `mission`
- local stall sizing gap:
  - required wing area for limit: `47.19 m^2`
  - extra area still needed: `+12.36 m^2`
- mission margin:
  - `-42.195 km`

## New Results

| Run | Accepted / Requested | Fully Feasible | Top `W/S` [N/m^2] | Top `S` [m^2] | Top `AR` | Top Failure | Best-Infeasible Area Needed for Stall Limit [m^2] | Best-Infeasible Extra Area [m^2] | Top Mission Margin [km] |
| --- | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: | ---: |
| baseline control | `8 / 8` | `0` | `29.56` | `34.83` | `33.03` | `launch + turn + local_stall + mission` | `47.19` | `12.36` | `-42.20` |
| box_A exploratory | `11 / 16` | `0` | `24.38` | `42.24` | `29.77` | `local_stall + mission` | `50.08` | `7.84` | `-21.68` |
| box_B exploratory | `9 / 16` | `0` | `21.97` | `46.87` | `26.83` | `local_stall + mission` | `49.29` | `2.43` | `-28.29` |
| box_B promoted | `16 / 24` | `0` | `21.19` | `48.60` | `24.43` | `local_stall + mission` | `48.62` | `0.02` | `-23.77` |

## Frontier Interpretation

### 1. The frontier keeps moving to lower wing loading and larger wing area

Yes.

- baseline control top concept:
  - `W/S = 29.56`
  - `S = 34.83`
- box_A top concept:
  - `W/S = 24.38`
  - `S = 42.24`
- box_B exploratory top concept:
  - `W/S = 21.97`
  - `S = 46.87`
- box_B promoted top concept:
  - `W/S = 21.19`
  - `S = 48.60`

The frontier is still walking down the low-`W/S` direction and up the large-`S` direction. It has not turned back inward yet.

### 2. The old box really was too conservative

Yes.

Comparing the same-line baseline control to the promoted box_B run:

- top-ranked `W/S` moved from `29.56` down to `21.19`
  - about `-8.37 N/m^2`
  - about `-28%`
- top-ranked `S` moved from `34.83` up to `48.60`
  - about `+13.77 m^2`
  - about `+39.5%`

That is too large a movement to dismiss as noise.

### 3. The dominant failure mode has changed

At the baseline-control frontier, the top infeasible cases still failed:

- `launch`
- `turn`
- `local_stall`
- `mission`

At the expanded-box frontier, the top cases mostly fail only:

- `local_stall`
- `mission`

Detailed counts from the promoted box_B top-ranked subset:

- `launch`: `1`
- `turn`: `0`
- `trim`: `0`
- `local_stall`: `10`
- `mission`: `10`

That is a meaningful shift.

Engineering reading:

- low-speed sizing expansion did remove `launch` and `turn` from the leading edge of the frontier
- `trim` is no longer a meaningful limiter here
- the remaining leading pair is now `local_stall + mission`
- mission-side dominant limiter in the new frontier is mostly `endurance_shortfall_at_best_feasible_speed`

So the answer is no longer “just stall everywhere.” It is now “stall is still the last low-speed gate, and mission endurance/power has become the co-equal new wall.”

### 4. There is a clear frontier knee

Yes.

The promoted box_B top concept reached:

- `W/S = 21.19`
- `S = 48.60`
- `AR = 24.43`
- local stall extra area still needed: only `+0.02 m^2`
- mission margin still `-23.77 km`

This is the clearest engineering conclusion from the run set:

- low-speed stall can be pushed very close to the limit by moving toward about `49 m^2`
- but even when that happens, mission is still far from passing

This means the frontier knee is now visible:

- before expansion:
  - the line was clearly low-speed-size-limited
- after expansion:
  - low-speed sizing is almost enough
  - mission endurance/power remains deeply insufficient

That is exactly the kind of “the box was too small, but the box was not the whole problem” answer this study was meant to extract.

## Quantitative Estimate: How Small Was The Box?

### Wing loading target needed for near-stall-feasible concepts

Current evidence says the useful frontier is around:

- `W/S ~= 21..22 N/m^2`

Below about `24 N/m^2`, the frontier clearly improves.
Around `21.2 N/m^2`, the promoted top concept is essentially on the local-stall edge.

Practical recommendation:

- if the goal is to let the search touch the low-speed frontier cleanly, the lower bound should be around `21 N/m^2`, not `26 N/m^2`

### Wing area upper range needed with current span bounds

Current evidence says:

- the top promoted concept already sits at `48.60 m^2`
- the best-infeasible local-stall limit estimate there is `48.62 m^2`
- many top-ranked cases still want roughly `49..50 m^2`

Practical recommendation:

- `50 m^2` is a sensible minimum upper bound if the goal is to let the line reach the low-speed frontier
- `52 m^2` is a safer engineering upper bound for study purposes, because the promoted top-ranked subset still has a median required area above `50 m^2`

Important caveat:

- with `span = 30..36 m` and `AR >= 24`, this larger-area region is already pressing against the low-AR side
- the promoted top concept is already at `AR = 24.43`
- so once you go much beyond about `49..50 m^2`, you are no longer only asking for “more area”; you are also implicitly asking the search to crowd the lower-`AR` edge of the allowed family

### What the study says about mission / power assumptions

Even after nearly removing the local-stall gap, the promoted top concept still misses mission by about:

- `23.77 km`

That is too large to explain away as a tiny residual sizing miss.

Engineering implication:

- the old low-speed box was definitely too small
- but after expanding it, the next dominant issue is now mission endurance / rider-power availability at the best feasible speed
- the next study should not only keep expanding `S`; it should review mission-speed / power / endurance assumptions

## Bottom Line

The new parameterization is doing the right thing.

Low-speed box expansion materially moved the frontier:

- from roughly `W/S ~ 30`, `S ~ 35`
- toward roughly `W/S ~ 21`, `S ~ 49`

That shift removed `launch` and `turn` from the leading infeasible set.

But the promoted run also shows the next wall very clearly:

- local stall is almost closed
- mission is still very far from closed

So the right next step is:

- keep `box_B` as the active low-speed reference
- stop treating `trim` or `turn` as the main issue
- do a focused mission / power / endurance review before spending much more effort on even larger area or finer physics
