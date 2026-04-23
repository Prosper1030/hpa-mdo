# Birdman Brute-Force Follow-up Benchmark

Date: 2026-04-23
Workspace: `/Volumes/Samsung SSD/hpa-mdo/.worktrees/birdman-upstream-concept`

## Purpose

Capture the performance state after the post-Target-CL follow-up work:

1. worker negative cache and stage-separated cache buckets
2. coarse-to-fine CST refinement
3. all-zone batched screening queries
4. cross-concept global screening batches

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
| Global concept batching | current state | `27.20 s` |

## Current Commands

### Current persistent cold run

```bash
rm -rf output/birdman_targetcl_global_batch_smoke && /usr/bin/time -l \
  env PYTHONPATH=src ../../.venv/bin/python \
  scripts/birdman_upstream_concept_design.py \
  --config configs/birdman_upstream_concept_baseline.yaml \
  --output-dir output/birdman_targetcl_global_batch_smoke \
  --worker-mode julia
```

### Current persistent warm run

```bash
/usr/bin/time -l env PYTHONPATH=src ../../.venv/bin/python \
  scripts/birdman_upstream_concept_design.py \
  --config configs/birdman_upstream_concept_baseline.yaml \
  --output-dir output/birdman_targetcl_global_batch_smoke \
  --worker-mode julia
```

### Current one-shot cold run

```bash
rm -rf output/birdman_targetcl_global_batch_oneshot && /usr/bin/time -l \
  env PYTHONPATH=src ../../.venv/bin/python - <<'PY'
from pathlib import Path

from hpa_mdo.concept.airfoil_worker import JuliaXFoilWorker
from hpa_mdo.concept.avl_loader import build_avl_backed_spanwise_loader
from hpa_mdo.concept.config import load_concept_config
from hpa_mdo.concept.pipeline import run_birdman_concept_pipeline

cfg_path = Path("configs/birdman_upstream_concept_baseline.yaml").resolve()
out_dir = Path("output/birdman_targetcl_global_batch_oneshot").resolve()
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
| Current persistent cold | `27.20` | `143,884,984` |
| Current persistent warm | `5.83` | `134,709,848` |
| Current one-shot cold | `87.97` | `144,835,160` |

Regression:

- `134 passed in 72.01s (0:01:12)`

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
- Current state vs old full-sweep baseline:
  - `98.48 s -> 27.20 s`
  - about `72.38%` faster overall
- Current one-shot vs current persistent cold:
  - `87.97 s / 27.20 s ≈ 3.23x`
- Current warm vs current persistent cold:
  - `5.83 s / 27.20 s ≈ 21.43%`

## Engineering Review

### What is now clearly true

The brute-force path is materially better than the earlier dual-track-only
state. The later checklist items are not cosmetic:

- negative cache avoids repeated dead queries
- coarse-to-fine avoids sending the full bounded family through screening
- all-zone batching reduces worker scheduling fragmentation
- global concept batching removes another layer of repeated screening passes

Together, these later steps save another large chunk of cold-path time after
the original Target-CL screening win.

### What is still the physical-compute bottleneck

The dominant cost is still low-Re viscous XFOIL solve time, not CST geometry.

That is visible in two ways:

1. persistent cold is still much slower than warm cache-hit runs
2. one-shot remains much slower than persistent, which confirms that session
   reuse and shared screening batches are still buying a meaningful amount of
   runtime
3. even the persistent cold
   path is still solver-dominated rather than Python-dominated

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
2. more aggressive coarse-to-fine / multi-stage search
   - current refinement is local and bounded, not yet a broader beam/successive
     halving architecture

## Bottom Line

The Birdman brute-force screening engine is now much closer to the intended
architecture from the performance checklist.

From an engineering perspective:

- the speedup is real
- the current architecture is no longer obviously wasting solver effort in the
  way the earlier full-sweep path did
- but the next gains will come from smarter global scheduling and surrogate
  filtering, not from further micro-optimizing CST math
