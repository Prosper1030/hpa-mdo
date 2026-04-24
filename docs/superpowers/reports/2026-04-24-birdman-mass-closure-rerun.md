# Birdman Mass Closure Rerun

Date: 2026-04-24
Workspace: `/Volumes/Samsung SSD/hpa-mdo`

## Command

```bash
env PYTHONPATH=src /usr/bin/time -p ./.venv/bin/python \
  scripts/birdman_upstream_concept_design.py \
  --config configs/birdman_upstream_concept_baseline.yaml \
  --output-dir output/birdman_mass_closure_rerun_20260424 \
  --worker-mode julia
```

Runtime:

- `real 1030.46`
- `user 7074.18`
- `sys 122.44`

Artifacts:

- `output/birdman_mass_closure_rerun_20260424/concept_summary.json`
- `output/birdman_mass_closure_rerun_20260424/concept_ranked_pool.json`
- `output/birdman_mass_closure_rerun_20260424/frontier_summary.json`

The output directory is ignored by git and was not staged.

## Baseline Result

The baseline run completed with the real `julia_xfoil` worker.

Summary:

- evaluated concepts: `40`
- selected fully feasible concepts: `0`
- mission feasible concepts: `0`
- safety feasible concepts: `0`
- top-ranked dominant failure: `local_stall+mission`
- top-ranked launch failures: `0`
- top-ranked turn failures: `0`
- top-ranked trim failures: `0`

Geometry enumeration for the baseline:

- requested samples: `48`
- accepted concepts: `40`
- rejected concepts: `8`
- rejection reasons: `aspect_ratio_above_max: 8`
- accepted area range: `30.397..40.100 m2`
- accepted wing-loading range: `26.074..33.772 N/m2`
- accepted closed-mass range: `104.679..106.620 kg`

## Top Candidate

Top ranked infeasible candidate: `eval-24`

| field | value |
| --- | ---: |
| span | `35.988 m` |
| wing area | `38.086 m2` |
| aspect ratio | `34.006` |
| wing loading target | `27.350 N/m2` |
| closed gross mass | `106.217 kg` |
| mass margin to 107 kg cap | `0.783 kg` |
| launch | `ok` |
| turn | `ok` |
| trim | `ok` |
| local stall | `fail` |
| local stall utilization | `1.070` |
| mission best range | `16.117 km` |
| mission margin | `-26.078 km` |
| best feasible speed | `7.0 m/s` |
| power margin at best feasible speed | `-25.4 W` |

Mission limiter audit for this candidate:

- dominant limiter: `endurance_shortfall_at_best_feasible_speed`
- target duration at `7.0 m/s`: `100.46 min`
- available duration at `7.0 m/s`: `38.37 min`
- power required at `7.0 m/s`: `238.31 W`

## Area Repair Check

The top candidate still wants more wing area to satisfy the local-stall
utilization limit:

- current area: `38.086 m2`
- required area for local-stall limit: `50.961 m2`
- added area required: `12.875 m2`

Using the same mass-closure equation:

```text
gross_mass = 98.6 + 0.20 * wing_area_m2
```

the local-stall repair area would imply:

```text
gross_mass = 98.6 + 0.20 * 50.961 = 108.792 kg
```

That misses the hard cap by `1.792 kg`. So the old "just add area" answer is
now correctly blocked by mass closure.

The same pattern holds across the top-ranked set:

| rank | id | area m2 | W/S N/m2 | closed mass kg | cap margin kg | required area m2 | repair mass kg | repair cap margin kg | range km | mission margin km |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | eval-24 | 38.086 | 27.350 | 106.217 | 0.783 | 50.961 | 108.792 | -1.792 | 16.117 | -26.078 |
| 2 | eval-10 | 36.164 | 28.699 | 105.833 | 1.167 | 51.102 | 108.820 | -1.820 | 14.430 | -27.765 |
| 3 | eval-38 | 36.641 | 28.351 | 105.928 | 1.072 | 51.460 | 108.892 | -1.892 | 13.777 | -28.418 |
| 4 | eval-39 | 39.050 | 26.723 | 106.410 | 0.590 | 54.121 | 109.424 | -2.424 | 10.485 | -31.710 |
| 5 | eval-37 | 37.372 | 27.835 | 106.074 | 0.926 | 49.279 | 108.456 | -1.456 | 10.476 | -31.719 |
| 6 | eval-40 | 38.429 | 27.123 | 106.286 | 0.714 | 53.267 | 109.253 | -2.253 | 10.286 | -31.909 |
| 7 | eval-25 | 37.758 | 27.570 | 106.152 | 0.848 | 53.574 | 109.315 | -2.315 | 9.438 | -32.757 |
| 8 | eval-04 | 39.770 | 26.274 | 106.554 | 0.446 | 51.453 | 108.891 | -1.891 | 9.331 | -32.864 |
| 9 | eval-13 | 34.603 | 29.905 | 105.521 | 1.479 | 45.927 | 107.785 | -0.785 | 0.928 | -41.267 |
| 10 | eval-18 | 39.314 | 26.556 | 106.463 | 0.537 | 53.744 | 109.349 | -2.349 | 0.892 | -41.303 |

## Low-Speed Box Sanity Check

I also checked geometry enumeration under the previously wider `box_B` family
with the same mass-closure defaults.

`configs/birdman_upstream_concept_box_b_smoke.yaml`:

- accepted: `14`
- rejected: `18`
- rejection reasons:
  - `mass_hard_max_exceeded: 13`
  - `aspect_ratio_above_max: 3`
  - `aspect_ratio_below_min: 2`
- accepted area range: `31.312..41.562 m2`
- accepted wing-loading range: `25.226..32.842 N/m2`
- accepted closed-mass range: `104.862..106.912 kg`

`configs/birdman_upstream_concept_box_b.yaml`:

- accepted: `35`
- rejected: `37`
- rejection reasons:
  - `mass_hard_max_exceeded: 29`
  - `aspect_ratio_above_max: 5`
  - `aspect_ratio_below_min: 3`
- accepted area range: `30.343..41.415 m2`
- accepted wing-loading range: `25.309..33.828 N/m2`
- accepted closed-mass range: `104.669..106.883 kg`

This is the important correction: the old `W/S ~= 21 N/m2`, `S ~= 49 m2`
region is no longer treated as a free candidate family. It is filtered before
the expensive aero pipeline because the gross mass exceeds the current `107 kg`
hard cap.

## Engineering Read

Mass closure fixed the most dangerous modeling error in this line. The pipeline
no longer rewards giant wing area without paying structural mass.

The new result is still not design-feasible:

- Launch, turn, and trim are no longer the top-ranked blockers.
- Local stall still wants substantially more wing area.
- The required local-stall repair area would exceed the gross-mass cap.
- Even before solving that, the mission is far short: the best baseline concept
  reaches only `16.1 km` against `42.195 km`.
- The mission failure is an endurance/power wall, not just a geometry gate.

The current best concept should therefore be treated as a diagnostic point, not
a candidate aircraft.

## Recommended Next Work

1. Do not widen the low wing-loading / large-area box again under the current
   mass cap. That route now fails for the right physical reason.
2. Add a first-class `local_stall_repair_mass_feasibility` field to the frontier
   summary, because the most useful signal is now whether the area needed to fix
   stall would violate gross mass.
3. Shift the next search toward better `CLmax` / twist / planform distribution
   inside roughly `S = 34..40 m2` and `W/S = 27..31 N/m2`, instead of adding
   area.
4. Audit the rider-power / endurance model before trusting ranking. At the top
   candidate, the power margin at `7.0 m/s` is already `-25.4 W`, and the
   available duration is far below the required `100.46 min`.
