# Birdman Brute-Force Follow-up Benchmark

Date: 2026-04-23
Workspace: `/Volumes/Samsung SSD/hpa-mdo/.worktrees/birdman-upstream-concept`

## Purpose

Capture the performance state after the post-Target-CL follow-up work:

1. worker negative cache and stage-separated cache buckets
2. coarse-to-fine CST refinement
3. all-zone batched screening queries
4. cross-concept global screening batches
5. successive-halving refinement with enlarged search space

This report answers two practical questions:

1. How much runtime did the later checklist items save beyond the original
   Target-CL dual-track upgrade?
2. Which performance items from the ChatGPT checklist are still not fully
   implemented?

## Reference Sequence

| Milestone | Meaning | Persistent cold runtime |
| --- | --- | ---: |
| Old full-sweep baseline | pre Target-CL dual-track | `98.48 s` |
| Target-CL dual-track | finalist-only full sweep | `60.71 s` |
| Coarse-to-fine CST | bounded refinement after screening | `45.36 s` |
| Batched zone screening | zone-level batching only | `38.23 s` |
| Global concept batching | small-space current state | `27.20 s` |
| Successive-halving expanded search | current enlarged state | `81.90 s` |

## Search Space Comparison

| State | `keep_top_n` | zones | CST candidates per zone | Nominal airfoil candidates |
| --- | ---: | ---: | ---: | ---: |
| Small-space global batching | `5` | `4` | `35` | `700` |
| Expanded successive-halving | `8` | `4` | `99` | `3168` |

The enlarged state increases the nominal screening space by about `4.53x`.

## Current Commands

### Current persistent cold run

```bash
rm -rf output/birdman_targetcl_halving_expanded_smoke && /usr/bin/time -l \
  env PYTHONPATH=src ../../.venv/bin/python \
  scripts/birdman_upstream_concept_design.py \
  --config configs/birdman_upstream_concept_baseline.yaml \
  --output-dir output/birdman_targetcl_halving_expanded_smoke \
  --worker-mode julia
```

### Current persistent warm run

```bash
/usr/bin/time -l env PYTHONPATH=src ../../.venv/bin/python \
  scripts/birdman_upstream_concept_design.py \
  --config configs/birdman_upstream_concept_baseline.yaml \
  --output-dir output/birdman_targetcl_halving_expanded_smoke \
  --worker-mode julia
```

### Current one-shot cold run

```bash
rm -rf output/birdman_targetcl_halving_expanded_oneshot && /usr/bin/time -l \
  env PYTHONPATH=src ../../.venv/bin/python - <<'PY'
from pathlib import Path

from hpa_mdo.concept.airfoil_worker import JuliaXFoilWorker
from hpa_mdo.concept.avl_loader import build_avl_backed_spanwise_loader
from hpa_mdo.concept.config import load_concept_config
from hpa_mdo.concept.pipeline import run_birdman_concept_pipeline

cfg_path = Path("configs/birdman_upstream_concept_baseline.yaml").resolve()
out_dir = Path("output/birdman_targetcl_halving_expanded_oneshot").resolve()
cfg = load_concept_config(cfg_path)


def fallback_loader(concept, stations):
    zones = ("root", "mid1", "mid2", "tip")
    if not stations:
        return {zone: {"points": []} for zone in zones}
    payload = {zone: {"points": []} for zone in zones}
    for index, station in enumerate(stations):
        zone = zones[min(index * len(zones) // len(stations), len(zones) - 1)]
        payload[zone]["points"].append(
            {
                "reynolds": 260000.0 + 5000.0 * index,
                "cl_target": max(0.5, 0.70 - 0.015 * index),
                "cm_target": -0.10 + 0.01 * index,
                "weight": 1.0,
                "station_y_m": station.y_m,
                "chord_m": station.chord_m,
            }
        )
    return payload


spanwise_loader = build_avl_backed_spanwise_loader(
    cfg=cfg,
    working_root=out_dir / "avl_cases",
    fallback_loader=fallback_loader,
)

run_birdman_concept_pipeline(
    config_path=cfg_path,
    output_dir=out_dir,
    airfoil_worker_factory=lambda **kwargs: JuliaXFoilWorker(
        **kwargs, persistent_mode=False
    ),
    spanwise_loader=spanwise_loader,
)
PY
```

### Current full regression

```bash
PYTHONPATH=src ../../.venv/bin/python -m pytest \
  tests/test_concept_config.py \
  tests/test_concept_geometry.py \
  tests/test_concept_zone_requirements.py \
  tests/test_concept_airfoil_cst.py \
  tests/test_concept_airfoil_selection.py \
  tests/test_concept_airfoil_worker.py \
  tests/test_concept_safety.py \
  tests/test_concept_handoff.py \
  tests/test_concept_pipeline.py \
  tests/test_concept_avl_loader.py -q
```

## Current Results

| Case | Runtime (s) | Peak memory footprint (bytes) |
| --- | ---: | ---: |
| Current persistent cold | `81.90` | `167,002,808` |
| Current persistent warm | `19.48` | `154,714,736` |
| Current one-shot cold | `276.70` | `205,570,696` |

Regression:

- `136 passed in 196.60s (0:03:16)`

## Improvement Breakdown

- Target-CL dual-track vs old full-sweep:
  - `98.48 s -> 60.71 s`
  - about `38.35%` faster
- Coarse-to-fine CST vs earlier Target-CL dual-track:
  - `60.71 s -> 45.36 s`
  - about `25.28%` faster
- Batched zone screening vs earlier coarse-to-fine:
  - `45.36 s -> 38.23 s`
  - about `15.72%` faster
- Global concept batching vs earlier batched zone screening:
  - `38.23 s -> 27.20 s`
  - about `28.85%` faster
- Expanded successive-halving vs small-space global batching:
  - `27.20 s -> 81.90 s`
  - about `201.10%` slower in absolute runtime
  - but nominal screening space increased from `700 -> 3168`
  - runtime per nominal candidate improved from about `0.0389 s -> 0.0259 s`
  - about `33.42%` better throughput per nominal candidate
- Current enlarged state vs old full-sweep baseline:
  - `98.48 s -> 81.90 s`
  - still about `16.84%` faster overall despite the larger search space
- Current one-shot vs current persistent cold:
  - `276.70 s / 81.90 s ≈ 3.38x`
- Current warm vs current persistent cold:
  - `19.48 s / 81.90 s ≈ 23.79%`

## Engineering Review

### What is now clearly true

The brute-force path is materially better than the earlier dual-track-only
state. The later checklist items are not cosmetic:

- negative cache avoids repeated dead queries
- coarse-to-fine avoids sending the full bounded family through screening
- all-zone batching reduces worker scheduling fragmentation
- global concept batching removes another layer of repeated screening passes

Together, these later steps first saved another large chunk of cold-path time
after the original Target-CL screening win. The newest enlarged-space step then
spent some of that runtime budget on materially more search coverage, instead
of only trying to minimize wall-clock time.

### What is still the physical-compute bottleneck

The dominant cost is still low-Re viscous XFOIL solve time, not CST geometry.

That is visible in two ways:

1. persistent cold is still much slower than warm cache-hit runs
2. one-shot remains much slower than persistent, which confirms that session
   reuse and shared screening batches are still buying a meaningful amount of
   runtime
3. even the enlarged persistent cold path is still solver-dominated rather than
   Python-dominated

### What the enlarged-space run tells us

The enlarged run is the first good evidence that the current screening engine is
no longer just fast on a toy search space.

- the nominal CST screening volume grew from `700` to `3168`
- persistent cold runtime grew from `27.20 s` to `81.90 s`, not linearly with
  the raw candidate count
- per-candidate throughput improved rather than regressed

From a brute-force architecture perspective, this is a healthy sign:

- the new search policy is doing more work
- the worker/cache/scheduling stack is still absorbing some of that growth
- the cost is still dominated by XFOIL solves, not by Python orchestration

### What remains from the original checklist

The low-risk, high-return items are now mostly in place:

- process-based persistent worker pool: done
- physical cache key redesign: done
- Target-CL screening with finalist full sweep: done
- negative cache separation: done
- conservative geometry prescreen: done
- coarse-to-fine CST refinement: done
- zone-level batched scheduling: done
- concept-level global query scheduling: done

The main items that are still only partial or missing are:

1. cache-assisted or learned surrogate prescreen
   - current prescreen is still conservative and mostly geometry-driven
2. broader global search policies beyond the current bounded successive-halving
   - current refinement is now multi-stage and beam-limited
   - but it is still local around bounded CST neighborhoods, not yet a more
     aggressive global successive-halving or surrogate-guided search

### Current physical-output sanity check

The enlarged search did not magically make the aircraft concepts feasible.
The current smoke output at
`output/birdman_targetcl_halving_expanded_smoke/concept_summary.json`
still shows:

- `selected_concepts = 0`
- `best_infeasible_concepts = 8`
- first best infeasible range around `4150.87 m`
- failure remains driven by `launch`, `turn`, and `local_stall`

That is an important engineering result: the larger CST search space did not
hide the underlying physical bottleneck. The current limitation still looks
like low-speed loading and stall margin, not a lack of airfoil sample count.

## Bottom Line

The Birdman brute-force screening engine is now much closer to the intended
architecture from the performance checklist, and it now survives a materially
larger search space at still-usable runtime.

From an engineering perspective:

- the speedup work is real
- the enlarged search confirms the current engine is no longer obviously wasting
  solver effort the way the earlier full-sweep path did
- but the next gains will come from smarter global screening and surrogate
  filtering, not from further micro-optimizing CST math
