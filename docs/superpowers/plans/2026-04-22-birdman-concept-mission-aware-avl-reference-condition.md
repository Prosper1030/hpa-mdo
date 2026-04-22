# Birdman Concept Mission-Aware AVL Reference Condition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current fixed AVL sizing surrogate (`speed_sweep midpoint + heaviest gross mass`) with a mission-aware reference condition that changes with `objective_mode` and the limiting gross-mass case.

**Architecture:** Keep the new AVL-backed spanwise loader in `src/hpa_mdo/concept/avl_loader.py`, but add a small mission-proxy selector there that chooses the representative AVL trim point before writing/solving the AVL case. Do not widen the geometry search space or start CST work in this wave. The pipeline should keep reporting the selected AVL reference-condition policy in the output summary.

**Tech Stack:** Python 3.10, current `hpa_mdo.concept` package, AVL CLI, Julia/XFoil.jl worker already wired, `pytest`.

---

## Scope Check

This wave is one narrow engineering task:

- choose AVL reference speed/mass based on `mission.objective_mode`
- surface the chosen policy and selected condition in artifacts
- keep the existing fallback path and current pipeline contracts

It does **not** include:

- CST deformation
- full mission simulation
- new config knobs
- full unification of all mission formulas across every module

## File Structure

### Modify

- `src/hpa_mdo/concept/avl_loader.py`
  - Add mission-aware reference-condition selection helper(s).
  - Replace the fixed midpoint/heaviest-mass AVL setup.
  - Preserve and annotate fallback behavior.
- `src/hpa_mdo/concept/pipeline.py`
  - Extend the spanwise-requirement summary to expose the selected AVL reference condition in the concept summary.
- `tests/test_concept_avl_loader.py`
  - Add direct tests for objective-aware reference-condition selection.
  - Keep the existing real-AVL smoke test.
- `tests/test_concept_pipeline.py`
  - Assert that concept summaries expose the new reference-condition metadata.

### Create

- No new runtime modules are required for this wave.

## Engineering Assumption

The mission-aware AVL selector in this wave is still a **proxy**, but a better one:

- for `max_range`
  - choose the gross-mass case with the **smallest** `best_range_m`
  - use that case’s `best_range_speed_mps` as the AVL reference speed
- for `min_power`
  - choose the gross-mass case with the **largest** `min_power_w`
  - use that case’s `min_power_speed_mps` as the AVL reference speed

This is not yet a full closed-loop mission truth. It is a better sizing surrogate than the current fixed midpoint speed.

### Task 1: Lock The Mission-Aware Reference Contract With Tests

**Files:**
- Modify: `tests/test_concept_avl_loader.py`
- Modify: `tests/test_concept_pipeline.py`

- [ ] **Step 1: Write failing AVL-loader reference-condition tests**

Add direct tests in `tests/test_concept_avl_loader.py` for a new helper such as:

```python
def test_select_avl_reference_condition_uses_range_speed_for_max_range():
    cfg = load_concept_config(Path("configs/birdman_upstream_concept_baseline.yaml"))
    cfg = cfg.model_copy(
        update={
            "mission": cfg.mission.model_copy(update={"objective_mode": "max_range"})
        }
    )
    concept = _sample_concept()

    ref = select_avl_reference_condition(
        cfg=cfg,
        concept=concept,
        air_density_kg_per_m3=1.10,
    )

    assert ref["objective_mode"] == "max_range"
    assert ref["mass_selection_reason"] == "min_best_range"
    assert ref["reference_speed_reason"] == "best_range_speed_mps"
    assert ref["reference_condition_policy"] == "mission_objective_and_limiting_mass_proxy_v1"
    assert ref["reference_speed_mps"] == pytest.approx(
        ref["selected_mass_case"]["best_range_speed_mps"]
    )
```

```python
def test_select_avl_reference_condition_uses_min_power_speed_for_min_power():
    cfg = load_concept_config(Path("configs/birdman_upstream_concept_baseline.yaml"))
    cfg = cfg.model_copy(
        update={
            "mission": cfg.mission.model_copy(update={"objective_mode": "min_power"})
        }
    )
    concept = _sample_concept()

    ref = select_avl_reference_condition(
        cfg=cfg,
        concept=concept,
        air_density_kg_per_m3=1.10,
    )

    assert ref["objective_mode"] == "min_power"
    assert ref["mass_selection_reason"] == "max_min_power"
    assert ref["reference_speed_reason"] == "min_power_speed_mps"
    assert ref["reference_speed_mps"] == pytest.approx(
        ref["selected_mass_case"]["min_power_speed_mps"]
    )
```

- [ ] **Step 2: Add a pipeline summary test for the new reference metadata**

Extend `tests/test_concept_pipeline.py` with a small summary assertion:

```python
def test_pipeline_records_reference_condition_metadata_in_spanwise_summary(tmp_path: Path) -> None:
    result = run_birdman_concept_pipeline(
        config_path=Path("configs/birdman_upstream_concept_baseline.yaml"),
        output_dir=tmp_path,
        airfoil_worker_factory=...,
        spanwise_loader=lambda concept, stations: {
            "root": {
                "source": "avl_strip_forces",
                "reference_condition_policy": "mission_objective_and_limiting_mass_proxy_v1",
                "reference_speed_mps": 6.5,
                "reference_gross_mass_kg": 105.0,
                "points": [...],
            },
            ...
        },
    )

    summary = json.loads(result.summary_json_path.read_text(encoding="utf-8"))
    spanwise_summary = summary["selected_concepts"][0]["spanwise_requirements"]

    assert spanwise_summary["reference_condition_policies"] == [
        "mission_objective_and_limiting_mass_proxy_v1"
    ]
    assert spanwise_summary["reference_speeds_mps"] == [6.5]
    assert spanwise_summary["reference_gross_masses_kg"] == [105.0]
```

- [ ] **Step 3: Run the focused tests to verify they fail**

Run:

```bash
PYTHONPATH=src ../../.venv/bin/python -m pytest tests/test_concept_avl_loader.py tests/test_concept_pipeline.py -q
```

Expected:

- fail because the selector helper does not exist yet
- fail because `spanwise_requirements` summary does not yet include the new reference-condition lists

### Task 2: Implement Mission-Aware AVL Reference Selection

**Files:**
- Modify: `src/hpa_mdo/concept/avl_loader.py`

- [ ] **Step 1: Add a direct selector helper**

Add a helper in `src/hpa_mdo/concept/avl_loader.py` similar to:

```python
def select_avl_reference_condition(
    *,
    cfg: BirdmanConceptConfig,
    concept: GeometryConcept,
    air_density_kg_per_m3: float,
    profile_cd_proxy: float = 0.020,
) -> dict[str, Any]:
    ...
```

The helper should:

- build the speed sweep from mission config
- use a coarse mission power proxy over all `gross_mass_sweep_kg`
- evaluate each mass case with `evaluate_mission_objective(...)`
- choose the limiting mass case based on `objective_mode`
- return:
  - `objective_mode`
  - `reference_speed_mps`
  - `reference_gross_mass_kg`
  - `reference_speed_reason`
  - `mass_selection_reason`
  - `reference_condition_policy`
  - `selected_mass_case`

- [ ] **Step 2: Use the selector inside `load_zone_requirements_from_avl()`**

Replace:

```python
reference_speed_mps = _reference_speed_mps(cfg)
reference_gross_mass_kg = float(max(cfg.mass.gross_mass_sweep_kg))
```

with:

```python
reference_condition = select_avl_reference_condition(
    cfg=cfg,
    concept=concept,
    air_density_kg_per_m3=air_density_kgpm3,
)
reference_speed_mps = float(reference_condition["reference_speed_mps"])
reference_gross_mass_kg = float(reference_condition["reference_gross_mass_kg"])
```

and record these fields back into every zone payload:

```python
zone_payload["reference_speed_mps"] = float(reference_speed_mps)
zone_payload["reference_gross_mass_kg"] = float(reference_gross_mass_kg)
zone_payload["reference_speed_reason"] = str(reference_condition["reference_speed_reason"])
zone_payload["mass_selection_reason"] = str(reference_condition["mass_selection_reason"])
zone_payload["reference_condition_policy"] = str(
    reference_condition["reference_condition_policy"]
)
```

- [ ] **Step 3: Keep the fallback honesty contract**

Do not remove `_annotate_fallback_payload(...)`.
If AVL fails, fallback still happens, but the payload must still say:

```python
"source": "fallback_coarse_loader"
```

### Task 3: Surface The New Reference Metadata In Concept Summaries

**Files:**
- Modify: `src/hpa_mdo/concept/pipeline.py`

- [ ] **Step 1: Extend `_summarize_spanwise_requirements()`**

Include stable unique lists for:

```python
"reference_speeds_mps": ...,
"reference_gross_masses_kg": ...,
"reference_speed_reasons": ...,
"mass_selection_reasons": ...,
```

These should be collected from zone payload metadata if present.

- [ ] **Step 2: Keep summary behavior backward-compatible**

If a loader does not provide these fields, the summary should still exist and simply emit empty lists.

### Task 4: Verify And Commit

**Files:**
- Modify: only the files above

- [ ] **Step 1: Run the focused tests**

Run:

```bash
PYTHONPATH=src ../../.venv/bin/python -m pytest tests/test_concept_avl_loader.py tests/test_concept_pipeline.py -q
```

Expected:

- PASS

- [ ] **Step 2: Run the full concept test suite**

Run:

```bash
PYTHONPATH=src ../../.venv/bin/python -m pytest tests/test_concept_config.py tests/test_concept_geometry.py tests/test_concept_zone_requirements.py tests/test_concept_airfoil_worker.py tests/test_concept_safety.py tests/test_concept_handoff.py tests/test_concept_pipeline.py tests/test_concept_avl_loader.py -q
```

Expected:

- PASS

- [ ] **Step 3: Run a real AVL + Julia smoke**

Run:

```bash
rm -rf output/birdman_upstream_concept_mission_aware_avl_smoke
PYTHONPATH=src ../../.venv/bin/python scripts/birdman_upstream_concept_design.py \
  --config configs/birdman_upstream_concept_baseline.yaml \
  --output-dir output/birdman_upstream_concept_mission_aware_avl_smoke \
  --worker-mode julia
```

Check:

- `output/birdman_upstream_concept_mission_aware_avl_smoke/concept_summary.json` exists
- `selected_concepts[0]["spanwise_requirements"]["fallback_detected"]` is `False`
- `reference_condition_policies` contains `mission_objective_and_limiting_mass_proxy_v1`

- [ ] **Step 4: Do an engineering review, not just a software review**

Before calling it done, check:

- did the selected AVL reference speed actually move away from the old fixed midpoint when `objective_mode` changes?
- if not, is that because the current coarse mission proxy is too flat?
- are the resulting `trim` / `turn` / `launch` shifts plausible, or suspiciously unchanged?

If the results are unchanged, do not over-claim. Report that the policy wiring is correct but the current design space may still be too coarse to move the answer much.

- [ ] **Step 5: Commit**

```bash
git add src/hpa_mdo/concept/avl_loader.py src/hpa_mdo/concept/pipeline.py tests/test_concept_avl_loader.py tests/test_concept_pipeline.py
git commit -m "feat: 讓 Birdman AVL 載重工況跟 mission 目標連動"
```

