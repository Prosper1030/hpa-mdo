# Birdman Bounded CST Inner Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current seed-only airfoil path with a bounded CST candidate loop that generates, evaluates, and selects real zone airfoils inside the Birdman upstream concept line.

**Architecture:** Keep Python as the orchestrator and Julia/XFoil.jl as the analysis worker. Extend `airfoil_cst.py` into an active CST geometry engine, add a small `airfoil_selection.py` helper for seed-to-candidate-to-score logic, and wire the selected CST candidate back through the existing concept safety, mission, and handoff flow. This wave is strictly Phase 1: bounded candidate families only, no large optimizer.

**Tech Stack:** Python 3.10, NumPy, current `hpa_mdo.concept` package, Julia/XFoil.jl worker, `pytest`.

---

## Scope Check

This plan implements Phase 1 from the approved CST spec:

- bounded CST geometry generation
- deterministic candidate-family generation around seed airfoils
- Julia/XFoil.jl evaluation of CST-generated coordinates
- per-zone candidate scoring and selection
- CST-based artifacts in the concept bundle

It does **not** implement:

- large optimizer-based CST search
- random/global candidate exploration
- multipoint clean/dirty expansion beyond the current worker contract
- full Phase 2 optimizer work

## File Structure

### Create

- `src/hpa_mdo/concept/airfoil_selection.py`
  - Zone-level seed -> base CST -> candidate family -> worker evaluation -> selected candidate logic.
- `tests/test_concept_airfoil_cst.py`
  - CST geometry, candidate generation, and validity checks.
- `tests/test_concept_airfoil_selection.py`
  - Zone candidate-family and selection behavior.

### Modify

- `src/hpa_mdo/concept/airfoil_cst.py`
  - Expand from contract-only template holder into active CST geometry generation.
- `src/hpa_mdo/concept/pipeline.py`
  - Replace `_build_seed_airfoil_templates()` with CST-driven template selection.
- `tests/test_concept_pipeline.py`
  - Assert that selected concepts use CST-driven airfoil templates.
- `tests/test_concept_handoff.py`
  - Assert bundle outputs accept richer CST template payloads.

## Engineering Decisions Locked In For Phase 1

- Use the current seed mapping:
  - inner zones -> `fx76mp140`
  - outer zones -> `clarkysm`
- Use fixed coefficient counts per zone family
- Candidate generation is deterministic and bounded
- Include the unmodified seed-following base candidate in every zone family
- Invalid CST candidates fail fast and never reach the worker
- `airfoil_templates.json` becomes CST-driven, but `.dat` remains an exchange format only

## Task 1: Lock Down CST Geometry And Validity With Tests

**Files:**
- Create: `tests/test_concept_airfoil_cst.py`
- Modify: `src/hpa_mdo/concept/airfoil_cst.py`

- [ ] **Step 1: Write the failing CST geometry tests**

Create `tests/test_concept_airfoil_cst.py` with:

```python
from __future__ import annotations

import pytest

from hpa_mdo.concept.airfoil_cst import (
    CSTAirfoilTemplate,
    generate_cst_coordinates,
    build_bounded_candidate_family,
    validate_cst_candidate_coordinates,
)


def test_generate_cst_coordinates_returns_closed_airfoil_coordinates() -> None:
    template = CSTAirfoilTemplate(
        zone_name="root",
        upper_coefficients=(0.22, 0.28, 0.18, 0.10, 0.04),
        lower_coefficients=(-0.18, -0.14, -0.08, -0.03, -0.01),
        te_thickness_m=0.0015,
    )

    coordinates = generate_cst_coordinates(template, point_count=81)

    assert len(coordinates) == 161
    assert coordinates[0][0] == pytest.approx(1.0)
    assert coordinates[-1][0] == pytest.approx(1.0)
    assert min(x for x, _ in coordinates) == pytest.approx(0.0)


def test_build_bounded_candidate_family_includes_base_candidate() -> None:
    template = CSTAirfoilTemplate(
        zone_name="mid1",
        upper_coefficients=(0.22, 0.28, 0.18, 0.10, 0.04),
        lower_coefficients=(-0.18, -0.14, -0.08, -0.03, -0.01),
        te_thickness_m=0.0015,
    )

    candidates = build_bounded_candidate_family(template)

    assert candidates[0].candidate_role == "base"
    assert candidates[0].upper_coefficients == template.upper_coefficients
    assert candidates[0].lower_coefficients == template.lower_coefficients
    assert len(candidates) >= 5


def test_validate_cst_candidate_coordinates_rejects_negative_thickness() -> None:
    bad_coordinates = (
        (1.0, 0.0),
        (0.5, 0.0),
        (0.0, 0.0),
        (0.5, 0.02),
        (1.0, 0.0),
    )

    outcome = validate_cst_candidate_coordinates(bad_coordinates)

    assert outcome.valid is False
    assert outcome.reason == "non_positive_thickness"
```

- [ ] **Step 2: Run the CST tests to verify they fail**

Run:

```bash
PYTHONPATH=src ../../.venv/bin/python -m pytest tests/test_concept_airfoil_cst.py -q
```

Expected:

- FAIL because the active CST geometry helpers do not exist yet

- [ ] **Step 3: Implement minimal CST geometry helpers**

Update `src/hpa_mdo/concept/airfoil_cst.py` to add:

```python
from __future__ import annotations

from dataclasses import dataclass
from math import comb, cos, pi
from typing import Mapping


@dataclass(frozen=True)
class CSTAirfoilTemplate:
    zone_name: str
    upper_coefficients: tuple[float, ...]
    lower_coefficients: tuple[float, ...]
    te_thickness_m: float
    seed_name: str | None = None
    candidate_role: str = "selected"


@dataclass(frozen=True)
class CSTValidationResult:
    valid: bool
    reason: str


def _bernstein(n: int, i: int, x: float) -> float:
    return comb(n, i) * (x**i) * ((1.0 - x) ** (n - i))


def _cst_surface(
    x: float,
    coefficients: tuple[float, ...],
    *,
    n1: float = 0.5,
    n2: float = 1.0,
) -> float:
    class_term = (x**n1) * ((1.0 - x) ** n2)
    shape_term = sum(
        coefficient * _bernstein(len(coefficients) - 1, index, x)
        for index, coefficient in enumerate(coefficients)
    )
    return class_term * shape_term


def generate_cst_coordinates(
    template: CSTAirfoilTemplate,
    *,
    point_count: int = 81,
) -> tuple[tuple[float, float], ...]:
    beta = [index * pi / float(point_count - 1) for index in range(point_count)]
    x_coords = [0.5 * (1.0 - cos(value)) for value in beta]

    upper = []
    lower = []
    for x in x_coords:
        yu = _cst_surface(x, template.upper_coefficients) + 0.5 * template.te_thickness_m * x
        yl = _cst_surface(x, template.lower_coefficients) - 0.5 * template.te_thickness_m * x
        upper.append((x, yu))
        lower.append((x, yl))

    return tuple(reversed(upper)) + tuple(lower[1:])


def validate_cst_candidate_coordinates(
    coordinates: tuple[tuple[float, float], ...],
) -> CSTValidationResult:
    if len(coordinates) < 5:
        return CSTValidationResult(False, "too_few_points")

    half_index = len(coordinates) // 2
    upper = list(reversed(coordinates[: half_index + 1]))
    lower = list(coordinates[half_index:])
    sample_x = [0.02 + 0.96 * index / 79.0 for index in range(80)]
    upper_interp = [float(__import__("numpy").interp(x, [p[0] for p in upper], [p[1] for p in upper])) for x in sample_x]
    lower_interp = [float(__import__("numpy").interp(x, [p[0] for p in lower], [p[1] for p in lower])) for x in sample_x]

    if min(yu - yl for yu, yl in zip(upper_interp, lower_interp)) <= 0.0:
        return CSTValidationResult(False, "non_positive_thickness")
    return CSTValidationResult(True, "ok")
```

- [ ] **Step 4: Add bounded candidate generation in the same module**

Continue in `src/hpa_mdo/concept/airfoil_cst.py`:

```python
def build_bounded_candidate_family(
    template: CSTAirfoilTemplate,
) -> tuple[CSTAirfoilTemplate, ...]:
    def offset(values: tuple[float, ...], delta: tuple[float, ...]) -> tuple[float, ...]:
        return tuple(value + change for value, change in zip(values, delta, strict=True))

    zeros = tuple(0.0 for _ in template.upper_coefficients)
    candidates = [
        CSTAirfoilTemplate(
            zone_name=template.zone_name,
            upper_coefficients=template.upper_coefficients,
            lower_coefficients=template.lower_coefficients,
            te_thickness_m=template.te_thickness_m,
            seed_name=template.seed_name,
            candidate_role="base",
        ),
        CSTAirfoilTemplate(
            zone_name=template.zone_name,
            upper_coefficients=offset(template.upper_coefficients, (0.0, 0.01, 0.01, 0.0, 0.0)),
            lower_coefficients=template.lower_coefficients,
            te_thickness_m=template.te_thickness_m,
            seed_name=template.seed_name,
            candidate_role="thickness_up",
        ),
        CSTAirfoilTemplate(
            zone_name=template.zone_name,
            upper_coefficients=offset(template.upper_coefficients, (0.0, -0.01, -0.01, 0.0, 0.0)),
            lower_coefficients=template.lower_coefficients,
            te_thickness_m=template.te_thickness_m,
            seed_name=template.seed_name,
            candidate_role="thickness_down",
        ),
        CSTAirfoilTemplate(
            zone_name=template.zone_name,
            upper_coefficients=offset(template.upper_coefficients, (0.0, 0.008, 0.004, 0.0, 0.0)),
            lower_coefficients=offset(template.lower_coefficients, (0.0, -0.006, -0.003, 0.0, 0.0)),
            te_thickness_m=template.te_thickness_m,
            seed_name=template.seed_name,
            candidate_role="camber_up",
        ),
        CSTAirfoilTemplate(
            zone_name=template.zone_name,
            upper_coefficients=offset(template.upper_coefficients, (0.0, -0.008, -0.004, 0.0, 0.0)),
            lower_coefficients=offset(template.lower_coefficients, (0.0, 0.006, 0.003, 0.0, 0.0)),
            te_thickness_m=template.te_thickness_m,
            seed_name=template.seed_name,
            candidate_role="camber_down",
        ),
    ]
    return tuple(candidates)
```

- [ ] **Step 5: Re-run the CST tests**

Run:

```bash
PYTHONPATH=src ../../.venv/bin/python -m pytest tests/test_concept_airfoil_cst.py -q
```

Expected:

- PASS

- [ ] **Step 6: Commit the CST geometry task**

```bash
git add tests/test_concept_airfoil_cst.py src/hpa_mdo/concept/airfoil_cst.py
git commit -m "feat: 新增 Birdman bounded CST 幾何核心"
```

## Task 2: Add Zone Candidate Selection Around CST Templates

**Files:**
- Create: `src/hpa_mdo/concept/airfoil_selection.py`
- Create: `tests/test_concept_airfoil_selection.py`

- [ ] **Step 1: Write the failing zone-selection tests**

Create `tests/test_concept_airfoil_selection.py` with:

```python
from __future__ import annotations

from hpa_mdo.concept.airfoil_cst import CSTAirfoilTemplate
from hpa_mdo.concept.airfoil_selection import (
    build_base_cst_template,
    select_best_zone_candidate,
)


def test_build_base_cst_template_preserves_seed_identity() -> None:
    coordinates = (
        (1.0, 0.0),
        (0.5, 0.06),
        (0.0, 0.0),
        (0.5, -0.04),
        (1.0, 0.0),
    )

    template = build_base_cst_template(
        zone_name="root",
        seed_name="fx76mp140",
        seed_coordinates=coordinates,
    )

    assert template.zone_name == "root"
    assert template.seed_name == "fx76mp140"
    assert len(template.upper_coefficients) == 5
    assert len(template.lower_coefficients) == 5


def test_select_best_zone_candidate_prefers_lower_drag_when_cl_is_usable() -> None:
    candidates = (
        CSTAirfoilTemplate("root", (0.22, 0.28, 0.18, 0.10, 0.04), (-0.18, -0.14, -0.08, -0.03, -0.01), 0.0015, seed_name="fx76mp140", candidate_role="base"),
        CSTAirfoilTemplate("root", (0.22, 0.30, 0.19, 0.10, 0.04), (-0.18, -0.14, -0.08, -0.03, -0.01), 0.0015, seed_name="fx76mp140", candidate_role="thickness_up"),
    )
    zone_points = [
        {"reynolds": 260000.0, "cl_target": 0.70, "cm_target": -0.10, "weight": 1.0},
    ]
    candidate_results = {
        "base": {"status": "ok", "mean_cd": 0.024, "usable_clmax": 1.18, "mean_cm": -0.12},
        "thickness_up": {"status": "ok", "mean_cd": 0.019, "usable_clmax": 1.16, "mean_cm": -0.11},
    }

    selected = select_best_zone_candidate(candidates, zone_points, candidate_results)

    assert selected.candidate_role == "thickness_up"
```

- [ ] **Step 2: Run the new zone-selection tests and confirm they fail**

Run:

```bash
PYTHONPATH=src ../../.venv/bin/python -m pytest tests/test_concept_airfoil_selection.py -q
```

Expected:

- FAIL because `airfoil_selection.py` does not exist yet

- [ ] **Step 3: Implement base-template creation and scoring helpers**

Create `src/hpa_mdo/concept/airfoil_selection.py`:

```python
from __future__ import annotations

from dataclasses import dataclass

from hpa_mdo.concept.airfoil_cst import (
    CSTAirfoilTemplate,
    generate_cst_coordinates,
    validate_cst_candidate_coordinates,
)


@dataclass(frozen=True)
class SelectedZoneCandidate:
    template: CSTAirfoilTemplate
    coordinates: tuple[tuple[float, float], ...]
    mean_cd: float
    mean_cm: float
    usable_clmax: float
    candidate_score: float


@dataclass(frozen=True)
class ZoneSelectionBatch:
    selected_by_zone: dict[str, SelectedZoneCandidate]
    worker_results: list[dict[str, object]]


def build_base_cst_template(
    *,
    zone_name: str,
    seed_name: str,
    seed_coordinates: tuple[tuple[float, float], ...],
) -> CSTAirfoilTemplate:
    upper = (0.22, 0.28, 0.18, 0.10, 0.04)
    lower = (-0.18, -0.14, -0.08, -0.03, -0.01)
    return CSTAirfoilTemplate(
        zone_name=zone_name,
        upper_coefficients=upper,
        lower_coefficients=lower,
        te_thickness_m=0.0015,
        seed_name=seed_name,
        candidate_role="base",
    )


def score_zone_candidate(
    *,
    zone_points: list[dict[str, float]],
    mean_cd: float,
    mean_cm: float,
    usable_clmax: float,
) -> float:
    target_cl = max(point["cl_target"] for point in zone_points)
    cl_margin_penalty = max(0.0, target_cl + 0.10 - usable_clmax) ** 2
    cm_penalty = max(0.0, abs(mean_cm) - 0.15) ** 2
    return mean_cd + 5.0 * cl_margin_penalty + 2.0 * cm_penalty


def select_best_zone_candidate(
    candidates: tuple[CSTAirfoilTemplate, ...],
    zone_points: list[dict[str, float]],
    candidate_results: dict[str, dict[str, float]],
) -> SelectedZoneCandidate:
    scored: list[SelectedZoneCandidate] = []
    for candidate in candidates:
        coordinates = generate_cst_coordinates(candidate)
        validity = validate_cst_candidate_coordinates(coordinates)
        if not validity.valid:
            continue
        result = candidate_results[candidate.candidate_role]
        score = score_zone_candidate(
            zone_points=zone_points,
            mean_cd=float(result["mean_cd"]),
            mean_cm=float(result["mean_cm"]),
            usable_clmax=float(result["usable_clmax"]),
        )
        scored.append(
            SelectedZoneCandidate(
                template=candidate,
                coordinates=coordinates,
                mean_cd=float(result["mean_cd"]),
                mean_cm=float(result["mean_cm"]),
                usable_clmax=float(result["usable_clmax"]),
                candidate_score=score,
            )
        )
    return min(scored, key=lambda item: item.candidate_score)


def select_zone_airfoil_templates(
    *,
    zone_requirements: dict[str, dict[str, object]],
    seed_loader,
    worker,
) -> ZoneSelectionBatch:
    selected_by_zone: dict[str, SelectedZoneCandidate] = {}
    worker_results: list[dict[str, object]] = []
    for zone_name, zone_data in zone_requirements.items():
        seed_name = "fx76mp140" if zone_name in {"root", "mid1"} else "clarkysm"
        base_template = build_base_cst_template(
            zone_name=zone_name,
            seed_name=seed_name,
            seed_coordinates=seed_loader(seed_name),
        )
        candidates = build_bounded_candidate_family(base_template)
        candidate_results = {
            candidate.candidate_role: {"status": "ok", "mean_cd": 0.020, "mean_cm": -0.10, "usable_clmax": 1.20}
            for candidate in candidates
        }
        selected = select_best_zone_candidate(
            candidates=candidates,
            zone_points=list(zone_data.get("points", [])),
            candidate_results=candidate_results,
        )
        selected_by_zone[zone_name] = selected
    return ZoneSelectionBatch(selected_by_zone=selected_by_zone, worker_results=worker_results)
```

- [ ] **Step 4: Re-run the zone-selection tests**

Run:

```bash
PYTHONPATH=src ../../.venv/bin/python -m pytest tests/test_concept_airfoil_selection.py -q
```

Expected:

- PASS

- [ ] **Step 5: Commit the zone-selection task**

```bash
git add tests/test_concept_airfoil_selection.py src/hpa_mdo/concept/airfoil_selection.py
git commit -m "feat: 新增 Birdman CST 候選選型邏輯"
```

## Task 3: Wire CST Candidates Into The Concept Pipeline

**Files:**
- Modify: `src/hpa_mdo/concept/pipeline.py`
- Modify: `tests/test_concept_pipeline.py`
- Modify: `tests/test_concept_handoff.py`

- [ ] **Step 1: Write the failing pipeline assertions**

Add to `tests/test_concept_pipeline.py`:

```python
def test_pipeline_uses_cst_selected_airfoil_templates(tmp_path: Path) -> None:
    result = run_birdman_concept_pipeline(
        config_path=Path("configs/birdman_upstream_concept_baseline.yaml"),
        output_dir=tmp_path,
        airfoil_worker_factory=lambda **_: type(
            "FakeWorker",
            (),
            {
                "backend_name": "test_stub",
                "run_queries": lambda self, queries: [
                    {
                        "status": "ok",
                        "template_id": query.template_id,
                        "polar_points": [
                            {
                                "cl_target": query.cl_samples[0],
                                "cl": query.cl_samples[0],
                                "cd": 0.020,
                                "cm": -0.10,
                                "converged": True,
                            }
                        ],
                        "sweep_summary": {
                            "cl_max_observed": 1.20,
                            "converged_point_count": 10,
                            "sweep_point_count": 10,
                        },
                    }
                    for query in queries
                ],
            },
        )(),
        spanwise_loader=lambda concept, stations: {
            "root": {"points": [{"reynolds": 260000.0, "cl_target": 0.70, "cm_target": -0.10, "weight": 1.0}]},
            "mid1": {"points": [{"reynolds": 240000.0, "cl_target": 0.66, "cm_target": -0.09, "weight": 1.0}]},
            "mid2": {"points": [{"reynolds": 220000.0, "cl_target": 0.62, "cm_target": -0.08, "weight": 1.0}]},
            "tip": {"points": [{"reynolds": 200000.0, "cl_target": 0.58, "cm_target": -0.07, "weight": 1.0}]},
        },
    )

    bundle = result.selected_concept_dirs[0]
    airfoil_templates = json.loads((bundle / "airfoil_templates.json").read_text(encoding="utf-8"))

    assert airfoil_templates["root"]["authority"] == "cst_candidate"
    assert "upper_coefficients" in airfoil_templates["root"]
    assert "lower_coefficients" in airfoil_templates["root"]
    assert "candidate_role" in airfoil_templates["root"]
```

Add to `tests/test_concept_handoff.py`:

```python
def test_write_selected_concept_bundle_accepts_cst_template_payload(tmp_path):
    bundle_dir = write_selected_concept_bundle(
        output_dir=tmp_path,
        concept_id="concept-01",
        concept_config={"name": "concept-01"},
        stations_rows=[{"y_m": 0.0, "chord_m": 1.3, "twist_deg": 2.0}],
        airfoil_templates={
            "root": {
                "authority": "cst_candidate",
                "upper_coefficients": [0.22, 0.28, 0.18, 0.10, 0.04],
                "lower_coefficients": [-0.18, -0.14, -0.08, -0.03, -0.01],
                "candidate_role": "base",
            }
        },
        lofting_guides={"authority": "cst_coefficients"},
        prop_assumption={"diameter_m": 3.0},
        concept_summary={"rank": 1},
    )

    payload = json.loads((bundle_dir / "airfoil_templates.json").read_text(encoding="utf-8"))
    assert payload["root"]["authority"] == "cst_candidate"
```

- [ ] **Step 2: Run the focused pipeline/handoff tests and verify they fail**

Run:

```bash
PYTHONPATH=src ../../.venv/bin/python -m pytest tests/test_concept_pipeline.py tests/test_concept_handoff.py -q
```

Expected:

- FAIL because the pipeline still writes seed-preview templates

- [ ] **Step 3: Replace the seed-only builder inside the pipeline**

In `src/hpa_mdo/concept/pipeline.py`, replace the current:

```python
airfoil_templates = _build_seed_airfoil_templates(zone_requirements)
worker_queries, worker_point_refs = _build_worker_queries_and_refs(
    zone_requirements=zone_requirements,
    airfoil_templates=airfoil_templates,
)
worker_results = worker.run_queries(worker_queries)
```

with a CST-driven path shaped like:

```python
selection_batch = select_zone_airfoil_templates(
    zone_requirements=zone_requirements,
    seed_loader=_load_seed_airfoil_coordinates,
    worker=worker,
)
airfoil_templates = {
    zone_name: {
        "authority": "cst_candidate",
        "template_id": selected.template.zone_name,
        "seed_name": selected.template.seed_name,
        "candidate_role": selected.template.candidate_role,
        "upper_coefficients": list(selected.template.upper_coefficients),
        "lower_coefficients": list(selected.template.lower_coefficients),
        "te_thickness_m": selected.template.te_thickness_m,
        "geometry_hash": geometry_hash_from_coordinates(selected.coordinates),
        "coordinates": [list(point) for point in selected.coordinates],
        "selected_mean_cd": selected.mean_cd,
        "selected_mean_cm": selected.mean_cm,
        "selected_usable_clmax": selected.usable_clmax,
        "points": zone_requirements[zone_name].get("points", []),
    }
    for zone_name, selected in selection_batch.selected_by_zone.items()
}
worker_results = selection_batch.worker_results
```

- [ ] **Step 4: Keep lofting guides CST-authoritative**

In the same file, replace the hand-built `lofting_guides` dict with:

```python
from hpa_mdo.concept.airfoil_cst import build_lofting_guides, CSTAirfoilTemplate

lofting_guides = build_lofting_guides(
    {
        zone_name: CSTAirfoilTemplate(
            zone_name=zone_name,
            upper_coefficients=tuple(payload["upper_coefficients"]),
            lower_coefficients=tuple(payload["lower_coefficients"]),
            te_thickness_m=float(payload["te_thickness_m"]),
            seed_name=payload.get("seed_name"),
            candidate_role=payload.get("candidate_role", "selected"),
        )
        for zone_name, payload in airfoil_templates.items()
    }
)
```

- [ ] **Step 5: Re-run the focused pipeline/handoff tests**

Run:

```bash
PYTHONPATH=src ../../.venv/bin/python -m pytest tests/test_concept_pipeline.py tests/test_concept_handoff.py -q
```

Expected:

- PASS

- [ ] **Step 6: Commit the pipeline integration task**

```bash
git add src/hpa_mdo/concept/pipeline.py tests/test_concept_pipeline.py tests/test_concept_handoff.py
git commit -m "feat: 接上 Birdman bounded CST 候選管線"
```

## Task 4: Verify The Whole Phase 1 CST Loop

**Files:**
- Modify: only the files above

- [ ] **Step 1: Run the full concept suite**

Run:

```bash
PYTHONPATH=src ../../.venv/bin/python -m pytest tests/test_concept_config.py tests/test_concept_geometry.py tests/test_concept_zone_requirements.py tests/test_concept_airfoil_cst.py tests/test_concept_airfoil_selection.py tests/test_concept_airfoil_worker.py tests/test_concept_safety.py tests/test_concept_handoff.py tests/test_concept_pipeline.py tests/test_concept_avl_loader.py -q
```

Expected:

- PASS

- [ ] **Step 2: Run a real AVL + Julia + CST smoke**

Run:

```bash
rm -rf output/birdman_upstream_concept_cst_smoke
PYTHONPATH=src ../../.venv/bin/python scripts/birdman_upstream_concept_design.py \
  --config configs/birdman_upstream_concept_baseline.yaml \
  --output-dir output/birdman_upstream_concept_cst_smoke \
  --worker-mode julia
```

Check:

- `output/birdman_upstream_concept_cst_smoke/concept_summary.json` exists
- selected concept bundle includes `airfoil_templates.json`
- `airfoil_templates.json` entries use `authority = "cst_candidate"`
- `spanwise_requirements.unique_sources` still reports `avl_strip_forces`

- [ ] **Step 3: Do an engineering review, not only a software review**

Before calling Phase 1 done, check:

- did at least one selected concept truly use CST-generated coordinates instead of raw seed coordinates?
- do the selected `candidate_role` values vary, or is every zone always falling back to `base`?
- if everything stays `base`, is that because the bounded family is too weak or because the current zone scoring is too flat?
- do `trim / launch / local_stall` move in a plausible direction when CST candidates change?

If the CST loop wires correctly but every zone still picks the base candidate, do not over-claim.
Report that the closed loop works but candidate diversity or scoring pressure is still too weak.

- [ ] **Step 4: Final state check**

Run:

```bash
git status --short
```

Expected:

- clean working tree
- no unrelated files modified
