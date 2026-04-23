# Birdman Target-CL Screening Benchmark

Date: 2026-04-23
Workspace: `/Volumes/Samsung SSD/hpa-mdo/.worktrees/birdman-upstream-concept`

## Purpose

Benchmark the new Birdman Target-CL dual-track flow against the previous
full-alpha-sweep screening baseline, and verify that the new path still passes
the concept-line regression suite.

The comparison isolates three questions:

1. Does Target-CL screening reduce cold-path runtime versus the older
   full-sweep screening path?
2. Does persistent Julia worker mode still matter after the new dual-track
   wiring lands?
3. Does the updated pipeline still pass the full concept-line regression suite?

## Benchmark Config

- Config: `configs/birdman_upstream_concept_baseline.yaml`
- Worker mode: `julia`
- Active dual-track branch:
  `/Volumes/Samsung SSD/hpa-mdo/.worktrees/birdman-upstream-concept`
- Comparison baseline worktree pinned to pre-dual-track commit:
  `/Volumes/Samsung SSD/hpa-mdo/.worktrees/birdman-targetcl-baseline`

## Commands

### Current dual-track persistent cold run

```bash
rm -rf output/birdman_targetcl_dualtrack_cold && /usr/bin/time -l \
  env PYTHONPATH=src ../../.venv/bin/python \
  scripts/birdman_upstream_concept_design.py \
  --config configs/birdman_upstream_concept_baseline.yaml \
  --output-dir output/birdman_targetcl_dualtrack_cold \
  --worker-mode julia
```

### Previous full-sweep persistent cold run

```bash
rm -rf output/birdman_targetcl_fullsweep_cold && /usr/bin/time -l \
  env PYTHONPATH=src ../../.venv/bin/python \
  scripts/birdman_upstream_concept_design.py \
  --config configs/birdman_upstream_concept_baseline.yaml \
  --output-dir output/birdman_targetcl_fullsweep_cold \
  --worker-mode julia
```

### Current dual-track persistent warm run

```bash
/usr/bin/time -l env PYTHONPATH=src ../../.venv/bin/python \
  scripts/birdman_upstream_concept_design.py \
  --config configs/birdman_upstream_concept_baseline.yaml \
  --output-dir output/birdman_targetcl_dualtrack_cold \
  --worker-mode julia
```

### Current dual-track one-shot cold run

```bash
rm -rf output/birdman_targetcl_dualtrack_oneshot && /usr/bin/time -l \
  env PYTHONPATH=src ../../.venv/bin/python - <<'PY'
from pathlib import Path

from hpa_mdo.concept.airfoil_worker import JuliaXFoilWorker
from hpa_mdo.concept.avl_loader import build_avl_backed_spanwise_loader
from hpa_mdo.concept.config import load_concept_config
from hpa_mdo.concept.pipeline import run_birdman_concept_pipeline

cfg_path = Path("configs/birdman_upstream_concept_baseline.yaml").resolve()
out_dir = Path("output/birdman_targetcl_dualtrack_oneshot").resolve()
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

## Results

| Case | Runtime (s) | Peak memory footprint (bytes) |
| --- | ---: | ---: |
| Previous full-sweep persistent cold | 98.48 | 136,725,200 |
| Current dual-track persistent cold | 60.71 | 132,973,264 |
| Current dual-track persistent warm | 7.49 | 132,006,488 |
| Current dual-track one-shot cold | 201.77 | 133,399,128 |

## Key Deltas

- Dual-track persistent cold vs old full-sweep persistent cold:
  `60.71 s` vs `98.48 s`
  - improvement: about `38.35%`
- Current persistent cold vs current one-shot cold:
  `60.71 s` vs `201.77 s`
  - persistent mode saves about `69.91%`
  - one-shot is about `3.32x` slower
- Current warm run vs current persistent cold:
  `7.49 s` vs `60.71 s`
  - warm run is about `12.34%` of cold runtime

## Regression

Command:

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

Result:

- `129 passed in 85.94s (0:01:25)`

## Engineering Review

### What the data supports

The new Target-CL dual-track design is not just a software refactor. It gives a
real cold-path speedup on the same machine and same Birdman baseline config.

The main practical win is:

- screening no longer spends a full alpha sweep on every candidate
- only the finalists are promoted to the expensive full-sweep path

That is exactly what the runtime delta reflects.

### What is still slow

The dominant computational bottleneck is still viscous XFOIL evaluation, not
CST geometry generation.

Even after persistent workers and Target-CL screening:

- cold runs still take about one minute
- one-shot cold runs are still much slower than persistent runs

So the remaining cost is mostly solver work, not Python-side orchestration.

### What this means for next optimization steps

The next high-value performance steps should focus on solver work reduction,
not on CST math itself:

1. shrink unnecessary fallback mini-sweeps
2. tighten the Target-CL solve so fewer helper evaluations are needed
3. add coarse-to-fine candidate scheduling so fewer poor candidates reach the
   expensive path

## Bottom Line

The Target-CL dual-track implementation is a meaningful performance
improvement:

- about `38%` faster than the old full-sweep cold path
- about `3.3x` faster than the current one-shot cold path when persistent mode
  is enabled
- still fully regression-clean on the concept-line suite

From an engineering perspective, this is a real improvement and not benchmark
noise. But it does not remove the underlying physical-compute bottleneck:
low-Re viscous XFOIL solves remain the expensive part of brute-force airfoil
screening.
