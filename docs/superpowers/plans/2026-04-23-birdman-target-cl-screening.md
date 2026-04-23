# Birdman Target-CL Screening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a dual-track airfoil analysis flow so the Birdman concept line uses cheap Target-CL screening for all candidates and reserves full alpha sweeps for finalists only.

**Architecture:** Extend the worker contract first so solver fidelity becomes an explicit part of query identity and cache identity. Then add a Julia-side Target-CL screening path with conservative fallback, wire a finalist reevaluation pass into the Python pipeline, and finish by benchmarking cold and warm runtime against the current full-sweep baseline.

**Tech Stack:** Python 3.10, Julia, Xfoil.jl, current `hpa_mdo.concept` pipeline, `pytest`.

---

## Scope Check

This plan implements Phase 1 from the approved Target-CL screening spec:

- screening and finalist solver fidelities
- explicit cache separation
- Julia-side target-CL solve path
- conservative mini-sweep fallback
- finalist-only full-polar reevaluation
- timing and regression evidence

It does **not** implement:

- a global optimizer
- full coarse-to-fine CST search
- a different airfoil toolchain
- a redesign of the Birdman aerodynamic objective

## File Structure

### Create

- `docs/superpowers/plans/2026-04-23-birdman-target-cl-screening.md`
  - This plan document.

### Modify

- `src/hpa_mdo/concept/airfoil_worker.py`
  - Add fidelity/stage query contract, cache separation, and response handling.
- `tools/julia/xfoil_worker/xfoil_worker.jl`
  - Add Target-CL screening path and mini-sweep fallback.
- `src/hpa_mdo/concept/airfoil_selection.py`
  - Mark screening queries explicitly and consume screening-mode responses.
- `src/hpa_mdo/concept/pipeline.py`
  - Add finalist reevaluation flow and rerank handling.
- `tests/test_concept_airfoil_worker.py`
  - Worker contract, cache separation, and target-CL behavior tests.
- `tests/test_concept_airfoil_selection.py`
  - Screening-mode query construction tests.
- `tests/test_concept_pipeline.py`
  - Dual-track finalist reevaluation tests.

### Optional Modify

- `src/hpa_mdo/concept/config.py`
  - Only if we decide to expose finalist count `L` or screening parameters in config now.
- `tests/test_concept_config.py`
  - Only if config schema changes.

## Engineering Decisions Locked In

- `analysis_mode` is the primary solver-fidelity discriminator
  - `screening_target_cl`
  - `full_alpha_sweep`
- `analysis_stage` is the workflow discriminator
  - `screening`
  - `finalist`
- Both discriminators must participate in physical cache identity
- Target-CL solving is implemented explicitly around `solve_alpha`, not by depending on a hidden CL-mode path
- Failed or near-stall target-CL solves fall back conservatively to `mini alpha sweep`
- Finalists use `full_alpha_sweep`; non-finalists stay screening-only
- Default finalist count for Phase 1 is `L = 3`

## Task 1: Extend The Worker Contract For Solver Fidelity

**Files:**
- Modify: `src/hpa_mdo/concept/airfoil_worker.py`
- Test: `tests/test_concept_airfoil_worker.py`

- [ ] **Step 1: Write failing contract tests for fidelity-separated cache identity**

Add tests in `tests/test_concept_airfoil_worker.py` that assert:

```python
def test_worker_cache_key_separates_screening_and_full_sweep() -> None:
    screening = _sample_query(
        analysis_mode="screening_target_cl",
        analysis_stage="screening",
    )
    finalist = _sample_query(
        analysis_mode="full_alpha_sweep",
        analysis_stage="finalist",
    )

    worker = JuliaXFoilWorker(
        project_dir=Path("/tmp/repo"),
        cache_dir=Path("/tmp/cache"),
        persistent_mode=False,
    )

    assert worker.cache_key(screening) != worker.cache_key(finalist)


def test_worker_materializes_result_with_analysis_mode_and_stage() -> None:
    query = _sample_query(
        analysis_mode="screening_target_cl",
        analysis_stage="screening",
    )
    worker = JuliaXFoilWorker(
        project_dir=Path("/tmp/repo"),
        cache_dir=Path("/tmp/cache"),
        persistent_mode=False,
    )

    materialized = worker._materialize_result_for_query(
        {
            "template_id": "ignored",
            "reynolds": query.reynolds,
            "cl_samples": list(query.cl_samples),
            "roughness_mode": query.roughness_mode,
            "geometry_hash": query.geometry_hash,
            "analysis_mode": "screening_target_cl",
            "analysis_stage": "screening",
            "status": "ok",
            "polar_points": [],
        },
        query,
    )

    assert materialized["analysis_mode"] == "screening_target_cl"
    assert materialized["analysis_stage"] == "screening"
```

- [ ] **Step 2: Run worker tests to verify the new contract is still missing**

Run:

```bash
PYTHONPATH=src ../../.venv/bin/python -m pytest tests/test_concept_airfoil_worker.py -q
```

Expected:

- FAIL because `PolarQuery` does not yet include the new fields

- [ ] **Step 3: Extend `PolarQuery` and cache identity**

Update `src/hpa_mdo/concept/airfoil_worker.py`:

- add to `PolarQuery`:

```python
analysis_mode: str = "full_alpha_sweep"
analysis_stage: str = "screening"
```

- include both fields in:
  - `cache_key()`
  - `_physical_query_identity()`
  - `_physical_result_identity()`
  - `_materialize_result_for_query()`

The physical identity payload must look like:

```python
payload = {
    "reynolds": query.reynolds,
    "cl_samples": list(query.cl_samples),
    "roughness_mode": query.roughness_mode,
    "geometry_hash": self._validated_geometry_hash(query),
    "analysis_mode": query.analysis_mode,
    "analysis_stage": query.analysis_stage,
}
```

- [ ] **Step 4: Ensure response validation requires the new fields**

Extend result validation so worker responses must carry:

- `analysis_mode`
- `analysis_stage`

and raise a clear error if they do not.

- [ ] **Step 5: Re-run targeted worker tests**

Run:

```bash
PYTHONPATH=src ../../.venv/bin/python -m pytest tests/test_concept_airfoil_worker.py -q
```

Expected:

- PASS with the new contract tests included

- [ ] **Step 6: Commit**

```bash
git add -p src/hpa_mdo/concept/airfoil_worker.py tests/test_concept_airfoil_worker.py
git commit -m "feat: 擴充 Birdman worker 的 solver fidelity contract"
```

## Task 2: Implement Julia Target-CL Screening With Mini-Sweep Fallback

**Files:**
- Modify: `tools/julia/xfoil_worker/xfoil_worker.jl`
- Test: `tests/test_concept_airfoil_worker.py`

- [ ] **Step 1: Add failing tests for screening-mode response shape**

Add tests that assert screening responses:

- preserve `analysis_mode="screening_target_cl"`
- preserve `analysis_stage="screening"`
- return `status` from:
  - `ok`
  - `mini_sweep_fallback`
- do not require a full sweep summary payload

- [ ] **Step 2: Add Julia-side mode dispatch**

In `tools/julia/xfoil_worker/xfoil_worker.jl`, change `analyze_query(query)` so it dispatches on:

```julia
analysis_mode = String(get(query, "analysis_mode", "full_alpha_sweep"))
analysis_stage = String(get(query, "analysis_stage", "screening"))
```

and then routes to:

- `analyze_query_target_cl(query)`
- `analyze_query_full_sweep(query)`

- [ ] **Step 3: Implement guarded Target-CL solve**

Add a helper structure like:

```julia
function solve_target_cl_screening(x, y, cl_target, reynolds; mach, iter, ncrit, xtrip)
    # 1. choose initial alpha bracket
    # 2. call Xfoil.solve_alpha at endpoints
    # 3. verify cl_target is bracketed
    # 4. iterate with secant / guarded interpolation
    # 5. stop on tolerance or failure
end
```

Required behavior:

- use `Xfoil.solve_alpha`
- do not extrapolate past the converged bracket
- mark nonconverged or unbracketed cases explicitly

- [ ] **Step 4: Implement mini-sweep fallback**

If the target-CL path cannot bracket or converges poorly near stall:

- run a small local alpha sweep
- use the best converged point as a lower-bound result
- return:

```json
{
  "status": "mini_sweep_fallback",
  "target_cl_converged": false,
  "clmax_is_lower_bound": true
}
```

- [ ] **Step 5: Keep full sweep path unchanged for finalists**

Refactor the existing alpha-sweep logic into `analyze_query_full_sweep(query)` without changing its aerodynamic behavior.

- [ ] **Step 6: Run targeted worker tests**

Run:

```bash
PYTHONPATH=src ../../.venv/bin/python -m pytest tests/test_concept_airfoil_worker.py -q
```

Expected:

- PASS with the new screening-mode tests

- [ ] **Step 7: Commit**

```bash
git add -p tools/julia/xfoil_worker/xfoil_worker.jl tests/test_concept_airfoil_worker.py
git commit -m "feat: 實作 Birdman Julia Target-CL screening"
```

## Task 3: Mark Zone Selection Queries As Screening Fidelity

**Files:**
- Modify: `src/hpa_mdo/concept/airfoil_selection.py`
- Test: `tests/test_concept_airfoil_selection.py`

- [ ] **Step 1: Write failing tests for screening-mode query creation**

Add a test in `tests/test_concept_airfoil_selection.py` that captures queries sent to the fake worker and asserts:

```python
assert all(query.analysis_mode == "screening_target_cl" for query in captured_queries)
assert all(query.analysis_stage == "screening" for query in captured_queries)
```

- [ ] **Step 2: Update `select_zone_airfoil_templates()`**

When building `PolarQuery(...)`, set:

```python
analysis_mode="screening_target_cl",
analysis_stage="screening",
```

Do not change the candidate-family logic in this task.

- [ ] **Step 3: Re-run selection tests**

Run:

```bash
PYTHONPATH=src ../../.venv/bin/python -m pytest tests/test_concept_airfoil_selection.py -q
```

Expected:

- PASS with the new query-shape assertions

- [ ] **Step 4: Commit**

```bash
git add -p src/hpa_mdo/concept/airfoil_selection.py tests/test_concept_airfoil_selection.py
git commit -m "feat: 標記 Birdman zone screening 的 Target-CL query"
```

## Task 4: Add Finalist Full-Sweep Reevaluation To The Pipeline

**Files:**
- Modify: `src/hpa_mdo/concept/pipeline.py`
- Test: `tests/test_concept_pipeline.py`
- Optional Modify: `src/hpa_mdo/concept/config.py`, `tests/test_concept_config.py`

- [ ] **Step 1: Write failing finalist reevaluation tests**

Add a pipeline test that:

- screens all concepts first
- reruns only the top `L=3`
- asserts finalist rerun queries use:

```python
analysis_mode == "full_alpha_sweep"
analysis_stage == "finalist"
```

and that non-finalists are not rerun.

- [ ] **Step 2: Add a finalist reevaluation helper**

In `src/hpa_mdo/concept/pipeline.py`, add a helper like:

```python
def _reevaluate_finalists_with_full_sweep(...):
    ...
```

Responsibilities:

- take screened evaluated concepts
- identify the finalist subset
- rebuild worker queries for the selected zone airfoils only
- rerun those queries with finalist/full-sweep fidelity
- rebuild worker feedback and derived summaries for those records

- [ ] **Step 3: Hook reevaluation after first ranking**

Insert the finalist pass after:

```python
ranked_concepts = rank_concepts(...)
```

and before the selected/best-infeasible bundle-writing loops.

Phase 1 default:

```python
finalist_count = 3
```

Hardcode this first unless config exposure is immediately necessary.

- [ ] **Step 4: Keep artifact flow intact**

Make sure `_concept_to_bundle_payload()` and bundle writers still work without structural changes.

Only add fidelity/stage fields to summaries if needed for traceability.

- [ ] **Step 5: Re-run targeted pipeline tests**

Run:

```bash
PYTHONPATH=src ../../.venv/bin/python -m pytest tests/test_concept_pipeline.py -q
```

Expected:

- PASS with finalist reevaluation coverage

- [ ] **Step 6: Commit**

```bash
git add -p src/hpa_mdo/concept/pipeline.py tests/test_concept_pipeline.py
git commit -m "feat: 接上 Birdman finalist full sweep 複評流程"
```

## Task 5: Run Full Regression And Performance Benchmarks

**Files:**
- Modify only if a fix is required after verification

- [ ] **Step 1: Run the full Birdman concept suite**

Run:

```bash
PYTHONPATH=src ../../.venv/bin/python -m pytest tests/test_concept_config.py tests/test_concept_geometry.py tests/test_concept_zone_requirements.py tests/test_concept_airfoil_cst.py tests/test_concept_airfoil_selection.py tests/test_concept_airfoil_worker.py tests/test_concept_safety.py tests/test_concept_handoff.py tests/test_concept_pipeline.py tests/test_concept_avl_loader.py -q
```

Expected:

- all tests pass

- [ ] **Step 2: Measure persistent cold run**

Run:

```bash
rm -rf output/birdman_target_cl_persistent
env PYTHONPATH=src /usr/bin/time -p ../../.venv/bin/python scripts/birdman_upstream_concept_design.py --config configs/birdman_upstream_concept_baseline.yaml --output-dir output/birdman_target_cl_persistent --worker-mode julia
```

Expected:

- successful run
- measurable cold runtime lower than the current full-sweep-everywhere baseline

- [ ] **Step 3: Measure persistent warm run**

Run:

```bash
env PYTHONPATH=src /usr/bin/time -p ../../.venv/bin/python scripts/birdman_upstream_concept_design.py --config configs/birdman_upstream_concept_baseline.yaml --output-dir output/birdman_target_cl_persistent --worker-mode julia
```

Expected:

- successful run
- warm runtime remains low

- [ ] **Step 4: Measure one-shot cold control**

Run a one-shot control by constructing:

```python
JuliaXFoilWorker(..., persistent_mode=False)
```

against the same config/output isolation as the persistent benchmark.

- [ ] **Step 5: Sanity-check output consistency**

Compare:

- `worker_backend`
- concept ordering
- selected vs infeasible split
- obvious ranking drift

Do not claim success if the code is only faster because it stopped computing needed finalist information.

- [ ] **Step 6: Commit only if verification required code changes**

If benchmark/regression reveals no code fix, do not create a no-op commit.

If a fix was needed:

```bash
git add -p <task-specific-files>
git commit -m "fix: 修正 Birdman Target-CL dual-track regression"
```
