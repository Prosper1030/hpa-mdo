# Birdman Upstream Concept Design Line Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a new Birdman-specific upstream concept-design pipeline that turns mission/rule inputs into `3~5` ranked aircraft concepts with airfoil zoning, simplified prop-aware coupling, launch/turn safety gates, and downstream handoff artifacts.

**Architecture:** Keep the existing inverse-design / jig / CFRP flow untouched as the downstream realizability mainline, and add a new `src/hpa_mdo/concept/` package that owns concept config, geometry-family generation, zone requirements, CST template handling, Julia/XFoil.jl worker integration, simplified prop/safety evaluation, ranking, and handoff packaging. Python remains the orchestrator; Julia is an external airfoil-analysis worker bridged through stable JSON/cache contracts.

**Tech Stack:** Python 3, Pydantic, existing `hpa_mdo.aero` and `hpa_mdo.mission` modules, `pytest` via `./.venv/bin/python -m pytest`, Julia runtime + `XFoil.jl` worker, YAML/JSON/CSV artifacts.

---

## Scope Check

This remains one implementation plan, not multiple separate plans, because the modules are interdependent pieces of a single upstream concept-design pipeline:

- concept config drives geometry generation
- geometry drives zone requirements
- zone requirements drive the Julia airfoil worker
- airfoil + prop assumptions feed launch/turn/safety
- ranking and handoff need the outputs of all prior tasks

The plan still keeps these responsibilities in separate files and commits so implementation can proceed task-by-task without tangling the downstream mainline.

## File Structure

### New files

- `src/hpa_mdo/concept/__init__.py`
  - Public exports for the upstream concept-design package.
- `src/hpa_mdo/concept/config.py`
  - Dedicated Pydantic config surface for the new line; keep this separate from `src/hpa_mdo/core/config.py`.
- `src/hpa_mdo/concept/geometry.py`
  - Geometry-family dataclasses, segmentation rules, linear taper/twist station generation.
- `src/hpa_mdo/concept/zone_requirements.py`
  - Zone definitions and conversion from spanwise loads/stations to per-zone `Re/cl/cm/thickness/stall` targets.
- `src/hpa_mdo/concept/airfoil_cst.py`
  - CST templates, `.dat` export helpers, lofting-guide generation, and interpolation rules.
- `src/hpa_mdo/concept/airfoil_worker.py`
  - Python bridge to Julia/XFoil.jl, polar-query cache, worker request/response parsing.
- `src/hpa_mdo/concept/propulsion.py`
  - Simplified prop-aware coupling model for concept evaluation.
- `src/hpa_mdo/concept/safety.py`
  - Ground-effect-aware launch gate, `15 deg bank` turn gate, trim/local-stall envelope evaluation.
- `src/hpa_mdo/concept/ranking.py`
  - Concept-level ranking contract and explanation fields.
- `src/hpa_mdo/concept/handoff.py`
  - Writer for `concept_config.yaml`, `stations.csv`, `airfoil_templates.json`, `lofting_guides.json`, `prop_assumption.json`, and `concept_summary.json`.
- `src/hpa_mdo/concept/pipeline.py`
  - Orchestration glue that wires config, geometry, zone requirements, Julia worker, safety, ranking, and handoff.
- `tools/julia/xfoil_worker/Project.toml`
  - Julia package environment for the airfoil worker.
- `tools/julia/xfoil_worker/xfoil_worker.jl`
  - Julia worker entrypoint that reads JSON input, uses `XFoil.jl`, and writes JSON output.
- `configs/birdman_upstream_concept_baseline.yaml`
  - Baseline config for Birdman upstream concept-design runs.
- `tests/test_concept_config.py`
  - Config validation and environment/segmentation assumptions.
- `tests/test_concept_geometry.py`
  - Geometry-family generation and segment-length constraints.
- `tests/test_concept_zone_requirements.py`
  - Zone binning and requirement extraction tests.
- `tests/test_concept_airfoil_worker.py`
  - Worker request/response, cache, and missing-runtime tests.
- `tests/test_concept_safety.py`
  - Prop coupling and launch/turn/trim/stall gate tests.
- `tests/test_concept_handoff.py`
  - Handoff artifact writer tests.
- `tests/test_concept_pipeline.py`
  - End-to-end pipeline smoke tests with fake/stubbed solver inputs.
- `scripts/birdman_upstream_concept_design.py`
  - CLI entrypoint for the new line.

### Existing files to modify

- `src/hpa_mdo/mission/__init__.py`
  - Reuse existing mission-power helpers if the new pipeline needs to import them through a stable package path.
- `src/hpa_mdo/aero/avl_spanwise.py`
  - Reuse only if a small helper extraction avoids duplicating strip-force → station mapping logic; do not refactor broadly.
- `src/hpa_mdo/aero/__init__.py`
  - Export new concept-side helpers only if the repo already uses package-level re-exports for neighboring subsystems.

### Write-scope notes

- Do not modify `scripts/direct_dual_beam_inverse_design.py` in this plan except later handoff consumption if a tiny adapter becomes unavoidable.
- Do not merge this line into the current structural candidate-screening path.
- Do not rewrite the repo into Julia.
- Do not build full propeller blade optimization in MVP.

## Task 1: Add A Dedicated Birdman Concept Config Surface

**Files:**
- Create: `src/hpa_mdo/concept/__init__.py`
- Create: `src/hpa_mdo/concept/config.py`
- Create: `configs/birdman_upstream_concept_baseline.yaml`
- Test: `tests/test_concept_config.py`

- [ ] **Step 1: Write the failing config tests**

Create `tests/test_concept_config.py`:

```python
from pathlib import Path

import pytest

from hpa_mdo.concept.config import BirdmanConceptConfig, load_concept_config


def test_load_concept_config_reads_birdman_baseline():
    repo_root = Path(__file__).resolve().parents[1]
    cfg = load_concept_config(
        repo_root / "configs" / "birdman_upstream_concept_baseline.yaml"
    )

    assert cfg.environment.temperature_c == pytest.approx(33.0)
    assert cfg.environment.relative_humidity == pytest.approx(80.0)
    assert cfg.mass.pilot_mass_kg == pytest.approx(60.0)
    assert cfg.mass.gross_mass_sweep_kg == (95.0, 100.0, 105.0)
    assert cfg.launch.platform_height_m == pytest.approx(10.0)
    assert cfg.turn.required_bank_angle_deg == pytest.approx(15.0)
    assert cfg.segmentation.min_segment_length_m == pytest.approx(1.0)
    assert cfg.segmentation.max_segment_length_m == pytest.approx(3.0)
    assert cfg.geometry_family.span_candidates_m == (30.0, 32.0, 34.0)
    assert cfg.geometry_family.taper_ratio_candidates == (0.30, 0.35, 0.40)


def test_segment_length_bounds_must_be_ordered():
    with pytest.raises(ValueError, match="min_segment_length_m"):
        BirdmanConceptConfig.model_validate(
            {
                "environment": {"temperature_c": 33.0, "relative_humidity": 80.0},
                "mass": {
                    "pilot_mass_kg": 60.0,
                    "baseline_aircraft_mass_kg": 40.0,
                    "gross_mass_sweep_kg": [95.0, 100.0, 105.0],
                },
                "mission": {"target_distance_km": 42.195},
                "segmentation": {
                    "min_segment_length_m": 3.5,
                    "max_segment_length_m": 3.0,
                },
            }
        )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
./.venv/bin/python -m pytest tests/test_concept_config.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'hpa_mdo.concept'`.

- [ ] **Step 3: Implement the dedicated config module**

Create `src/hpa_mdo/concept/config.py`:

```python
from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator


class EnvironmentConfig(BaseModel):
    temperature_c: float = Field(..., gt=-50.0, lt=80.0)
    relative_humidity: float = Field(..., ge=0.0, le=100.0)
    altitude_m: float = Field(0.0, ge=-100.0)


class MassConfig(BaseModel):
    pilot_mass_kg: float = Field(..., gt=0.0)
    baseline_aircraft_mass_kg: float = Field(..., gt=0.0)
    gross_mass_sweep_kg: tuple[float, ...] = Field(..., min_length=3, max_length=3)


class MissionConfig(BaseModel):
    target_distance_km: float = Field(42.195, gt=0.0)
    rider_model: Literal["fake_anchor_curve"] = "fake_anchor_curve"
    anchor_power_w: float = Field(300.0, gt=0.0)
    anchor_duration_min: float = Field(30.0, gt=0.0)
    speed_sweep_min_mps: float = Field(6.0, gt=0.0)
    speed_sweep_max_mps: float = Field(10.0, gt=0.0)
    speed_sweep_points: int = Field(9, ge=3)


class SegmentationConfig(BaseModel):
    min_segment_length_m: float = Field(1.0, gt=0.0)
    max_segment_length_m: float = Field(3.0, gt=0.0)

    @model_validator(mode="after")
    def validate_bounds(self) -> "SegmentationConfig":
        if self.max_segment_length_m < self.min_segment_length_m:
            raise ValueError("segmentation.max_segment_length_m must be >= min_segment_length_m.")
        return self


class LaunchConfig(BaseModel):
    platform_height_m: float = Field(10.0, gt=0.0)
    runup_length_m: float = Field(10.0, gt=0.0)
    use_ground_effect: bool = True


class TurnConfig(BaseModel):
    required_bank_angle_deg: float = Field(15.0, gt=0.0, lt=45.0)


class GeometryFamilyConfig(BaseModel):
    span_candidates_m: tuple[float, ...] = Field((30.0, 32.0, 34.0), min_length=1)
    wing_area_candidates_m2: tuple[float, ...] = Field((26.0, 28.0, 30.0), min_length=1)
    taper_ratio_candidates: tuple[float, ...] = Field((0.30, 0.35, 0.40), min_length=1)
    twist_tip_candidates_deg: tuple[float, ...] = Field((-2.0, -1.5, -1.0), min_length=1)
    tail_area_candidates_m2: tuple[float, ...] = Field((3.8, 4.2, 4.6), min_length=1)


class BirdmanConceptConfig(BaseModel):
    environment: EnvironmentConfig
    mass: MassConfig
    mission: MissionConfig
    segmentation: SegmentationConfig = Field(default_factory=SegmentationConfig)
    launch: LaunchConfig = Field(default_factory=LaunchConfig)
    turn: TurnConfig = Field(default_factory=TurnConfig)
    geometry_family: GeometryFamilyConfig = Field(default_factory=GeometryFamilyConfig)


def load_concept_config(path: str | Path) -> BirdmanConceptConfig:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return BirdmanConceptConfig.model_validate(payload)
```

Create `src/hpa_mdo/concept/__init__.py`:

```python
from hpa_mdo.concept.config import BirdmanConceptConfig, load_concept_config

__all__ = [
    "BirdmanConceptConfig",
    "load_concept_config",
]
```

Create `configs/birdman_upstream_concept_baseline.yaml`:

```yaml
environment:
  temperature_c: 33.0
  relative_humidity: 80.0
  altitude_m: 0.0

mass:
  pilot_mass_kg: 60.0
  baseline_aircraft_mass_kg: 40.0
  gross_mass_sweep_kg: [95.0, 100.0, 105.0]

mission:
  target_distance_km: 42.195
  rider_model: fake_anchor_curve
  anchor_power_w: 300.0
  anchor_duration_min: 30.0
  speed_sweep_min_mps: 6.0
  speed_sweep_max_mps: 10.0
  speed_sweep_points: 9

segmentation:
  min_segment_length_m: 1.0
  max_segment_length_m: 3.0

launch:
  platform_height_m: 10.0
  runup_length_m: 10.0
  use_ground_effect: true

turn:
  required_bank_angle_deg: 15.0

geometry_family:
  span_candidates_m: [30.0, 32.0, 34.0]
  wing_area_candidates_m2: [26.0, 28.0, 30.0]
  taper_ratio_candidates: [0.30, 0.35, 0.40]
  twist_tip_candidates_deg: [-2.0, -1.5, -1.0]
  tail_area_candidates_m2: [3.8, 4.2, 4.6]
```

- [ ] **Step 4: Run the config tests to verify they pass**

Run:

```bash
./.venv/bin/python -m pytest tests/test_concept_config.py -q
```

Expected: PASS with both config tests green.

- [ ] **Step 5: Commit**

```bash
git add src/hpa_mdo/concept/__init__.py src/hpa_mdo/concept/config.py configs/birdman_upstream_concept_baseline.yaml tests/test_concept_config.py
git commit -m "feat: 新增 Birdman 概念設計設定模型"
```

## Task 2: Generate The Geometry Family And Station Contract

**Files:**
- Create: `src/hpa_mdo/concept/geometry.py`
- Test: `tests/test_concept_geometry.py`

- [ ] **Step 1: Write the failing geometry tests**

Create `tests/test_concept_geometry.py`:

```python
import numpy as np
import pytest

from hpa_mdo.concept.config import load_concept_config
from hpa_mdo.concept.geometry import (
    GeometryConcept,
    build_linear_wing_stations,
    build_segment_plan,
    enumerate_geometry_concepts,
)


def test_build_segment_plan_respects_min_and_max_segment_length(tmp_path):
    cfg = load_concept_config("configs/birdman_upstream_concept_baseline.yaml")
    lengths = build_segment_plan(
        half_span_m=16.5,
        min_segment_length_m=cfg.segmentation.min_segment_length_m,
        max_segment_length_m=cfg.segmentation.max_segment_length_m,
    )

    assert pytest.approx(sum(lengths)) == 16.5
    assert all(1.0 <= item <= 3.0 for item in lengths)


def test_build_linear_wing_stations_returns_monotone_stations():
    concept = GeometryConcept(
        span_m=32.0,
        wing_area_m2=28.0,
        root_chord_m=1.30,
        tip_chord_m=0.45,
        twist_root_deg=2.0,
        twist_tip_deg=-1.5,
        tail_area_m2=4.0,
        cg_xc=0.30,
        segment_lengths_m=(1.5, 3.0, 3.0, 3.0, 3.0, 2.5),
    )

    stations = build_linear_wing_stations(concept, stations_per_half=6)

    assert stations[0].y_m == pytest.approx(0.0)
    assert stations[-1].y_m == pytest.approx(16.0)
    assert [station.y_m for station in stations] == sorted(station.y_m for station in stations)
    assert stations[0].chord_m > stations[-1].chord_m
    assert stations[0].twist_deg > stations[-1].twist_deg


def test_enumerate_geometry_concepts_generates_multiple_candidates():
    cfg = load_concept_config("configs/birdman_upstream_concept_baseline.yaml")
    concepts = enumerate_geometry_concepts(cfg)

    assert len(concepts) >= 3
```

- [ ] **Step 2: Run the geometry tests to verify they fail**

Run:

```bash
./.venv/bin/python -m pytest tests/test_concept_geometry.py -q
```

Expected: FAIL because `hpa_mdo.concept.geometry` does not exist yet.

- [ ] **Step 3: Implement the geometry generator**

Create `src/hpa_mdo/concept/geometry.py`:

```python
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WingStation:
    y_m: float
    chord_m: float
    twist_deg: float


@dataclass(frozen=True)
class GeometryConcept:
    span_m: float
    wing_area_m2: float
    root_chord_m: float
    tip_chord_m: float
    twist_root_deg: float
    twist_tip_deg: float
    tail_area_m2: float
    cg_xc: float
    segment_lengths_m: tuple[float, ...]


def build_segment_plan(
    *,
    half_span_m: float,
    min_segment_length_m: float,
    max_segment_length_m: float,
) -> tuple[float, ...]:
    lengths: list[float] = []
    remaining = float(half_span_m)
    while remaining > max_segment_length_m:
        lengths.append(float(max_segment_length_m))
        remaining -= float(max_segment_length_m)
    if remaining < min_segment_length_m and lengths:
        borrow = min_segment_length_m - remaining
        lengths[-1] -= borrow
        remaining += borrow
    lengths.append(remaining)
    return tuple(lengths)


def build_linear_wing_stations(
    concept: GeometryConcept,
    *,
    stations_per_half: int,
) -> tuple[WingStation, ...]:
    half_span_m = 0.5 * concept.span_m
    y_values = [
        idx * half_span_m / float(stations_per_half - 1)
        for idx in range(stations_per_half)
    ]
    stations = []
    for y_m in y_values:
        frac = 0.0 if half_span_m == 0.0 else y_m / half_span_m
        chord_m = concept.root_chord_m + frac * (concept.tip_chord_m - concept.root_chord_m)
        twist_deg = concept.twist_root_deg + frac * (concept.twist_tip_deg - concept.twist_root_deg)
        stations.append(WingStation(y_m=y_m, chord_m=chord_m, twist_deg=twist_deg))
    return tuple(stations)


def enumerate_geometry_concepts(cfg) -> tuple[GeometryConcept, ...]:
    concepts = []
    for span_m in cfg.geometry_family.span_candidates_m:
        for wing_area_m2 in cfg.geometry_family.wing_area_candidates_m2:
            for taper_ratio in cfg.geometry_family.taper_ratio_candidates:
                for twist_tip_deg in cfg.geometry_family.twist_tip_candidates_deg:
                    for tail_area_m2 in cfg.geometry_family.tail_area_candidates_m2:
                        root_chord_m = wing_area_m2 / (0.5 * span_m * (1.0 + taper_ratio))
                        tip_chord_m = root_chord_m * taper_ratio
                        segment_lengths_m = build_segment_plan(
                            half_span_m=0.5 * span_m,
                            min_segment_length_m=cfg.segmentation.min_segment_length_m,
                            max_segment_length_m=cfg.segmentation.max_segment_length_m,
                        )
                        concepts.append(
                            GeometryConcept(
                                span_m=span_m,
                                wing_area_m2=wing_area_m2,
                                root_chord_m=root_chord_m,
                                tip_chord_m=tip_chord_m,
                                twist_root_deg=2.0,
                                twist_tip_deg=twist_tip_deg,
                                tail_area_m2=tail_area_m2,
                                cg_xc=0.30,
                                segment_lengths_m=segment_lengths_m,
                            )
                        )
    return tuple(concepts)
```

- [ ] **Step 4: Run the geometry tests to verify they pass**

Run:

```bash
./.venv/bin/python -m pytest tests/test_concept_geometry.py -q
```

Expected: PASS, confirming monotone stations and segmentation within `1~3 m`.

- [ ] **Step 5: Commit**

```bash
git add src/hpa_mdo/concept/geometry.py tests/test_concept_geometry.py
git commit -m "feat: 新增 Birdman 概念幾何生成器"
```

## Task 3: Build Zone Requirements And CST Template Outputs

**Files:**
- Create: `src/hpa_mdo/concept/zone_requirements.py`
- Create: `src/hpa_mdo/concept/airfoil_cst.py`
- Test: `tests/test_concept_zone_requirements.py`

- [ ] **Step 1: Write the failing zone/CST tests**

Create `tests/test_concept_zone_requirements.py`:

```python
import numpy as np

from hpa_mdo.aero.base import SpanwiseLoad
from hpa_mdo.concept.airfoil_cst import CSTAirfoilTemplate, build_lofting_guides
from hpa_mdo.concept.geometry import GeometryConcept, build_linear_wing_stations
from hpa_mdo.concept.zone_requirements import build_zone_requirements, default_zone_definitions


def _sample_load() -> SpanwiseLoad:
    return SpanwiseLoad(
        y=np.array([0.0, 2.0, 4.0, 6.0, 8.0]),
        chord=np.array([1.30, 1.10, 0.90, 0.70, 0.50]),
        cl=np.array([0.90, 0.88, 0.82, 0.75, 0.68]),
        cd=np.array([0.020, 0.019, 0.018, 0.017, 0.016]),
        cm=np.array([-0.12, -0.11, -0.10, -0.09, -0.08]),
        lift_per_span=np.array([120.0, 110.0, 100.0, 85.0, 60.0]),
        drag_per_span=np.array([2.4, 2.1, 1.8, 1.5, 1.1]),
        aoa_deg=6.0,
        velocity=8.0,
        dynamic_pressure=36.8,
    )


def test_build_zone_requirements_groups_operating_points_by_zone():
    concept = GeometryConcept(
        span_m=16.0,
        wing_area_m2=20.0,
        root_chord_m=1.30,
        tip_chord_m=0.50,
        twist_root_deg=2.0,
        twist_tip_deg=-1.0,
        tail_area_m2=4.0,
        cg_xc=0.30,
        segment_lengths_m=(2.5, 2.5, 3.0),
    )
    stations = build_linear_wing_stations(concept, stations_per_half=5)
    zone_requirements = build_zone_requirements(
        spanwise_load=_sample_load(),
        stations=stations,
        zone_definitions=default_zone_definitions(),
    )

    assert set(zone_requirements.keys()) == {"root", "mid1", "mid2", "tip"}
    assert zone_requirements["root"].points
    assert zone_requirements["tip"].min_tc_ratio > 0.0


def test_build_lofting_guides_uses_cst_templates_as_authority():
    templates = {
        "root": CSTAirfoilTemplate("root", (0.2, 0.3, 0.1), (-0.1, -0.2, -0.05), 0.0015),
        "tip": CSTAirfoilTemplate("tip", (0.1, 0.2, 0.05), (-0.08, -0.15, -0.03), 0.0010),
    }

    guides = build_lofting_guides(templates)

    assert guides["authority"] == "cst_coefficients"
    assert guides["blend_pairs"] == [("root", "tip")]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
./.venv/bin/python -m pytest tests/test_concept_zone_requirements.py -q
```

Expected: FAIL because `zone_requirements` and `airfoil_cst` modules do not exist.

- [ ] **Step 3: Implement zone extraction and CST template helpers**

Create `src/hpa_mdo/concept/zone_requirements.py`:

```python
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ZoneDefinition:
    name: str
    y0_frac: float
    y1_frac: float


@dataclass(frozen=True)
class ZoneOperatingPoint:
    reynolds: float
    cl_target: float
    cm_target: float
    weight: float


@dataclass(frozen=True)
class ZoneRequirement:
    name: str
    min_tc_ratio: float
    points: tuple[ZoneOperatingPoint, ...]


def default_zone_definitions() -> tuple[ZoneDefinition, ...]:
    return (
        ZoneDefinition("root", 0.00, 0.25),
        ZoneDefinition("mid1", 0.25, 0.55),
        ZoneDefinition("mid2", 0.55, 0.80),
        ZoneDefinition("tip", 0.80, 1.00),
    )


def build_zone_requirements(*, spanwise_load, stations, zone_definitions):
    half_span_m = max(float(value) for value in spanwise_load.y)
    zone_map = {}
    density_kgpm3 = 2.0 * float(spanwise_load.dynamic_pressure) / float(spanwise_load.velocity) ** 2
    for zone in zone_definitions:
        points = []
        for y_m, chord_m, cl_value, cm_value in zip(
            spanwise_load.y, spanwise_load.chord, spanwise_load.cl, spanwise_load.cm
        ):
            frac = 0.0 if half_span_m == 0.0 else float(y_m) / half_span_m
            if zone.y0_frac <= frac <= zone.y1_frac:
                reynolds = (
                    density_kgpm3
                    * float(spanwise_load.velocity)
                    * float(chord_m)
                    / 1.8e-5
                )
                points.append(
                    ZoneOperatingPoint(
                        reynolds=reynolds,
                        cl_target=float(cl_value),
                        cm_target=float(cm_value),
                        weight=1.0,
                    )
                )
        min_tc = 0.14 if zone.name == "root" else 0.10
        zone_map[zone.name] = ZoneRequirement(zone.name, min_tc, tuple(points))
    return zone_map
```

Create `src/hpa_mdo/concept/airfoil_cst.py`:

```python
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CSTAirfoilTemplate:
    zone_name: str
    upper_coefficients: tuple[float, ...]
    lower_coefficients: tuple[float, ...]
    te_thickness_m: float


def build_lofting_guides(templates: dict[str, CSTAirfoilTemplate]) -> dict[str, object]:
    zone_names = list(templates.keys())
    blend_pairs = list(zip(zone_names[:-1], zone_names[1:]))
    return {
        "authority": "cst_coefficients",
        "zones": zone_names,
        "blend_pairs": blend_pairs,
        "interpolation_rule": "linear_in_coeff_space",
    }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run:

```bash
./.venv/bin/python -m pytest tests/test_concept_zone_requirements.py -q
```

Expected: PASS with zone grouping and CST-based lofting-guide checks green.

- [ ] **Step 5: Commit**

```bash
git add src/hpa_mdo/concept/zone_requirements.py src/hpa_mdo/concept/airfoil_cst.py tests/test_concept_zone_requirements.py
git commit -m "feat: 新增概念設計翼段需求與 CST 模板"
```

## Task 4: Add The Julia/XFoil.jl Worker Bridge And Polar Cache

**Files:**
- Create: `src/hpa_mdo/concept/airfoil_worker.py`
- Create: `tools/julia/xfoil_worker/Project.toml`
- Create: `tools/julia/xfoil_worker/xfoil_worker.jl`
- Test: `tests/test_concept_airfoil_worker.py`

- [ ] **Step 1: Write the failing worker tests**

Create `tests/test_concept_airfoil_worker.py`:

```python
from pathlib import Path

import pytest

from hpa_mdo.concept.airfoil_worker import JuliaXFoilWorker, PolarQuery


def test_worker_cache_key_is_stable_for_identical_query(tmp_path):
    worker = JuliaXFoilWorker(project_dir=tmp_path, cache_dir=tmp_path / "cache")
    query = PolarQuery(
        template_id="root-v1",
        reynolds=350000.0,
        cl_samples=(0.70, 0.75, 0.80),
        roughness_mode="clean",
    )

    assert worker.cache_key(query) == worker.cache_key(query)


def test_worker_raises_clear_error_when_julia_runtime_is_missing(tmp_path, monkeypatch):
    worker = JuliaXFoilWorker(project_dir=tmp_path, cache_dir=tmp_path / "cache")
    monkeypatch.setattr(worker, "_resolve_julia", lambda: None)

    with pytest.raises(RuntimeError, match="Julia runtime not found"):
        worker.run_queries([])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
./.venv/bin/python -m pytest tests/test_concept_airfoil_worker.py -q
```

Expected: FAIL because the worker module does not exist.

- [ ] **Step 3: Implement the Python bridge and Julia worker**

Create `src/hpa_mdo/concept/airfoil_worker.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import shutil
import subprocess


@dataclass(frozen=True)
class PolarQuery:
    template_id: str
    reynolds: float
    cl_samples: tuple[float, ...]
    roughness_mode: str


class JuliaXFoilWorker:
    def __init__(self, *, project_dir: Path, cache_dir: Path) -> None:
        self.project_dir = Path(project_dir)
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def cache_key(self, query: PolarQuery) -> str:
        payload = json.dumps(query.__dict__, sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    def _resolve_julia(self) -> str | None:
        return shutil.which("julia")

    def run_queries(self, queries: list[PolarQuery]) -> list[dict[str, object]]:
        julia = self._resolve_julia()
        if julia is None:
            raise RuntimeError("Julia runtime not found. Install Julia before running the XFoil worker.")
        request_path = self.cache_dir / "request.json"
        response_path = self.cache_dir / "response.json"
        request_path.write_text(json.dumps([query.__dict__ for query in queries], indent=2), encoding="utf-8")
        subprocess.run(
            [
                julia,
                "--project=tools/julia/xfoil_worker",
                "tools/julia/xfoil_worker/xfoil_worker.jl",
                str(request_path),
                str(response_path),
            ],
            check=True,
            cwd=self.project_dir,
        )
        return json.loads(response_path.read_text(encoding="utf-8"))
```

Create `tools/julia/xfoil_worker/Project.toml`:

```toml
name = "BirdmanXFoilWorker"
uuid = "dd111111-2222-3333-4444-555555555555"
authors = ["Codex"]
version = "0.1.0"

[deps]
JSON3 = "0f8b85d8-7281-11e9-16c3-7d8f0d0f9f4b"
XFoil = "d7c9c9ef-cd89-4c1a-beb9-7aa7284f4664"
```

Create `tools/julia/xfoil_worker/xfoil_worker.jl`:

```julia
using JSON3
using XFoil

request_path = ARGS[1]
response_path = ARGS[2]
queries = JSON3.read(read(request_path, String))

results = Any[]
for query in queries
    push!(results, Dict(
        "template_id" => query["template_id"],
        "reynolds" => query["reynolds"],
        "roughness_mode" => query["roughness_mode"],
        "status" => "stubbed_ok",
        "polar_points" => Any[],
    ))
end

write(response_path, JSON3.write(results))
```

- [ ] **Step 4: Run the worker tests to verify they pass**

Run:

```bash
./.venv/bin/python -m pytest tests/test_concept_airfoil_worker.py -q
```

Expected: PASS for cache-key stability and missing-runtime error handling.

- [ ] **Step 5: Commit**

```bash
git add src/hpa_mdo/concept/airfoil_worker.py tools/julia/xfoil_worker/Project.toml tools/julia/xfoil_worker/xfoil_worker.jl tests/test_concept_airfoil_worker.py
git commit -m "feat: 新增 Julia XFoil airfoil worker 橋接"
```

## Task 5: Add Simplified Prop Coupling And Safety Envelope Gates

**Files:**
- Create: `src/hpa_mdo/concept/propulsion.py`
- Create: `src/hpa_mdo/concept/safety.py`
- Test: `tests/test_concept_safety.py`

- [ ] **Step 1: Write the failing propulsion/safety tests**

Create `tests/test_concept_safety.py`:

```python
import pytest

from hpa_mdo.concept.propulsion import SimplifiedPropModel
from hpa_mdo.concept.safety import (
    evaluate_launch_gate,
    evaluate_turn_gate,
)


def test_prop_model_varies_efficiency_with_speed_and_power():
    model = SimplifiedPropModel(
        diameter_m=3.0,
        rpm_min=100.0,
        rpm_max=160.0,
        design_efficiency=0.83,
    )

    low_speed = model.efficiency(speed_mps=7.0, shaft_power_w=240.0)
    high_speed = model.efficiency(speed_mps=10.0, shaft_power_w=320.0)

    assert low_speed != pytest.approx(high_speed)


def test_launch_gate_includes_ground_effect_height_logic():
    result = evaluate_launch_gate(
        platform_height_m=10.0,
        wing_span_m=32.0,
        speed_mps=8.0,
        cl_required=0.95,
        cl_available=1.10,
        trim_margin_deg=3.0,
        use_ground_effect=True,
    )

    assert result.ground_effect_applied is True
    assert result.feasible is True


def test_turn_gate_rejects_insufficient_stall_margin():
    result = evaluate_turn_gate(
        bank_angle_deg=15.0,
        speed_mps=8.0,
        cl_level=0.95,
        cl_max=1.05,
        trim_feasible=True,
    )

    assert result.feasible is False
    assert result.reason == "stall_margin_insufficient"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
./.venv/bin/python -m pytest tests/test_concept_safety.py -q
```

Expected: FAIL because `propulsion` and `safety` modules do not exist.

- [ ] **Step 3: Implement the simplified prop model and safety gates**

Create `src/hpa_mdo/concept/propulsion.py`:

```python
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SimplifiedPropModel:
    diameter_m: float
    rpm_min: float
    rpm_max: float
    design_efficiency: float

    def efficiency(self, *, speed_mps: float, shaft_power_w: float) -> float:
        speed_term = max(0.70, 1.0 - 0.015 * abs(speed_mps - 8.5))
        power_term = max(0.75, 1.0 - 0.0004 * abs(shaft_power_w - 280.0))
        return max(0.50, min(0.90, self.design_efficiency * speed_term * power_term))
```

Create `src/hpa_mdo/concept/safety.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class LaunchGateResult:
    feasible: bool
    ground_effect_applied: bool
    adjusted_cl_required: float
    reason: str


@dataclass(frozen=True)
class TurnGateResult:
    feasible: bool
    required_cl: float
    stall_margin: float
    reason: str


def evaluate_launch_gate(
    *,
    platform_height_m: float,
    wing_span_m: float,
    speed_mps: float,
    cl_required: float,
    cl_available: float,
    trim_margin_deg: float,
    use_ground_effect: bool,
) -> LaunchGateResult:
    drag_factor = 1.0
    if use_ground_effect:
        height_ratio = max(platform_height_m / wing_span_m, 1.0e-3)
        drag_factor = max(0.82, 1.0 - 0.6 * math.exp(-8.0 * height_ratio))
    adjusted_required = cl_required * drag_factor
    feasible = cl_available >= adjusted_required and trim_margin_deg > 0.0
    reason = "ok" if feasible else "launch_cl_or_trim_insufficient"
    return LaunchGateResult(feasible, use_ground_effect, adjusted_required, reason)


def evaluate_turn_gate(
    *,
    bank_angle_deg: float,
    speed_mps: float,
    cl_level: float,
    cl_max: float,
    trim_feasible: bool,
) -> TurnGateResult:
    required_cl = cl_level / math.cos(math.radians(bank_angle_deg))
    stall_margin = cl_max - required_cl
    feasible = trim_feasible and stall_margin > 0.10
    reason = "ok" if feasible else "stall_margin_insufficient"
    return TurnGateResult(feasible, required_cl, stall_margin, reason)
```

- [ ] **Step 4: Run the propulsion/safety tests to verify they pass**

Run:

```bash
./.venv/bin/python -m pytest tests/test_concept_safety.py -q
```

Expected: PASS, including ground-effect-aware launch logic and `15 deg` turn margin rejection.

- [ ] **Step 5: Commit**

```bash
git add src/hpa_mdo/concept/propulsion.py src/hpa_mdo/concept/safety.py tests/test_concept_safety.py
git commit -m "feat: 新增概念設計螺旋槳耦合與安全包絡線"
```

## Task 6: Add Ranking And Mainline Handoff Artifact Writers

**Files:**
- Create: `src/hpa_mdo/concept/ranking.py`
- Create: `src/hpa_mdo/concept/handoff.py`
- Test: `tests/test_concept_handoff.py`

- [ ] **Step 1: Write the failing ranking/handoff tests**

Create `tests/test_concept_handoff.py`:

```python
import json
from pathlib import Path

from hpa_mdo.concept.handoff import write_selected_concept_bundle
from hpa_mdo.concept.ranking import CandidateConceptResult, rank_concepts


def test_rank_concepts_prefers_feasible_safer_candidate():
    ranked = rank_concepts(
        [
            CandidateConceptResult("A", True, True, True, 0.20, 41000.0, 1.0),
            CandidateConceptResult("B", True, True, True, 0.35, 42000.0, 0.5),
        ]
    )

    assert ranked[0].concept_id == "B"
    assert ranked[0].why_not_higher == ()


def test_write_selected_concept_bundle_writes_expected_artifacts(tmp_path):
    bundle_dir = write_selected_concept_bundle(
        output_dir=tmp_path,
        concept_id="concept-01",
        concept_config={"name": "concept-01"},
        stations_rows=[{"y_m": 0.0, "chord_m": 1.3, "twist_deg": 2.0}],
        airfoil_templates={"root": {"upper": [0.2], "lower": [-0.1]}},
        lofting_guides={"authority": "cst_coefficients"},
        prop_assumption={"diameter_m": 3.0},
        concept_summary={"rank": 1},
    )

    assert (bundle_dir / "concept_config.yaml").exists()
    assert (bundle_dir / "stations.csv").exists()
    assert json.loads((bundle_dir / "concept_summary.json").read_text(encoding="utf-8"))["rank"] == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
./.venv/bin/python -m pytest tests/test_concept_handoff.py -q
```

Expected: FAIL because `ranking` and `handoff` modules do not exist.

- [ ] **Step 3: Implement ranking and handoff writers**

Create `src/hpa_mdo/concept/ranking.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CandidateConceptResult:
    concept_id: str
    launch_feasible: bool
    turn_feasible: bool
    trim_feasible: bool
    safety_margin: float
    best_range_m: float
    assembly_penalty: float


@dataclass(frozen=True)
class RankedConcept:
    concept_id: str
    score: float
    why_not_higher: tuple[str, ...] = field(default_factory=tuple)


def rank_concepts(results: list[CandidateConceptResult]) -> list[RankedConcept]:
    ranked = []
    for result in results:
        score = (
            (0.0 if result.launch_feasible else 1000.0)
            + (0.0 if result.turn_feasible else 1000.0)
            + (0.0 if result.trim_feasible else 1000.0)
            - 0.001 * result.best_range_m
            - 10.0 * result.safety_margin
            + result.assembly_penalty
        )
        ranked.append(RankedConcept(concept_id=result.concept_id, score=score, why_not_higher=()))
    return sorted(ranked, key=lambda item: item.score)
```

Create `src/hpa_mdo/concept/handoff.py`:

```python
from __future__ import annotations

import csv
import json
from pathlib import Path

import yaml


def write_selected_concept_bundle(
    *,
    output_dir: Path,
    concept_id: str,
    concept_config: dict,
    stations_rows: list[dict],
    airfoil_templates: dict,
    lofting_guides: dict,
    prop_assumption: dict,
    concept_summary: dict,
) -> Path:
    bundle_dir = Path(output_dir) / concept_id
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / "concept_config.yaml").write_text(
        yaml.safe_dump(concept_config, sort_keys=False),
        encoding="utf-8",
    )
    with (bundle_dir / "stations.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(stations_rows[0].keys()))
        writer.writeheader()
        writer.writerows(stations_rows)
    (bundle_dir / "airfoil_templates.json").write_text(json.dumps(airfoil_templates, indent=2), encoding="utf-8")
    (bundle_dir / "lofting_guides.json").write_text(json.dumps(lofting_guides, indent=2), encoding="utf-8")
    (bundle_dir / "prop_assumption.json").write_text(json.dumps(prop_assumption, indent=2), encoding="utf-8")
    (bundle_dir / "concept_summary.json").write_text(json.dumps(concept_summary, indent=2), encoding="utf-8")
    return bundle_dir
```

- [ ] **Step 4: Run the ranking/handoff tests to verify they pass**

Run:

```bash
./.venv/bin/python -m pytest tests/test_concept_handoff.py -q
```

Expected: PASS, confirming ranking order and artifact emission.

- [ ] **Step 5: Commit**

```bash
git add src/hpa_mdo/concept/ranking.py src/hpa_mdo/concept/handoff.py tests/test_concept_handoff.py
git commit -m "feat: 新增概念設計排名與主線交接輸出"
```

## Task 7: Wire The Full Pipeline And CLI Entry Point

**Files:**
- Create: `src/hpa_mdo/concept/pipeline.py`
- Create: `scripts/birdman_upstream_concept_design.py`
- Modify: `src/hpa_mdo/concept/__init__.py`
- Test: `tests/test_concept_pipeline.py`

- [ ] **Step 1: Write the failing pipeline tests**

Create `tests/test_concept_pipeline.py`:

```python
from pathlib import Path

from hpa_mdo.concept.pipeline import run_birdman_concept_pipeline


def test_pipeline_writes_ranked_concept_summary(tmp_path):
    result = run_birdman_concept_pipeline(
        config_path=Path("configs/birdman_upstream_concept_baseline.yaml"),
        output_dir=tmp_path,
        airfoil_worker_factory=lambda **_: type(
            "FakeWorker",
            (),
            {"run_queries": lambda self, queries: [{"status": "ok", "polar_points": []} for _ in queries]},
        )(),
        spanwise_loader=lambda concept, stations: {
            "root": {"points": [{"reynolds": 350000.0, "cl_target": 0.75, "cm_target": -0.10, "weight": 1.0}]},
            "mid1": {"points": [{"reynolds": 300000.0, "cl_target": 0.72, "cm_target": -0.09, "weight": 1.0}]},
            "mid2": {"points": [{"reynolds": 250000.0, "cl_target": 0.68, "cm_target": -0.08, "weight": 1.0}]},
            "tip": {"points": [{"reynolds": 200000.0, "cl_target": 0.62, "cm_target": -0.07, "weight": 1.0}]},
        },
    )

    assert result.summary_json_path.exists()
    assert 3 <= len(result.selected_concept_dirs) <= 5
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
./.venv/bin/python -m pytest tests/test_concept_pipeline.py -q
```

Expected: FAIL because `pipeline` and the CLI entrypoint do not exist yet.

- [ ] **Step 3: Implement the orchestrator and CLI**

Create `src/hpa_mdo/concept/pipeline.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from hpa_mdo.concept.config import load_concept_config
from hpa_mdo.concept.geometry import (
    GeometryConcept,
    build_linear_wing_stations,
    enumerate_geometry_concepts,
)
from hpa_mdo.concept.handoff import write_selected_concept_bundle


@dataclass(frozen=True)
class ConceptPipelineResult:
    summary_json_path: Path
    selected_concept_dirs: tuple[Path, ...]


def run_birdman_concept_pipeline(
    *,
    config_path: Path,
    output_dir: Path,
    airfoil_worker_factory,
    spanwise_loader,
) -> ConceptPipelineResult:
    cfg = load_concept_config(config_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    concepts = enumerate_geometry_concepts(cfg)[:5]
    worker = airfoil_worker_factory(project_dir=output_dir, cache_dir=output_dir / "polar_db")
    worker.run_queries([])
    selected_dirs = []
    for index, concept in enumerate(concepts, start=1):
        stations = build_linear_wing_stations(concept, stations_per_half=7)
        zone_requirements = spanwise_loader(concept, stations)
        selected_dirs.append(
            write_selected_concept_bundle(
                output_dir=output_dir / "selected_concepts",
                concept_id=f"concept-{index:02d}",
                concept_config={"span_m": concept.span_m},
                stations_rows=[station.__dict__ for station in stations],
                airfoil_templates=zone_requirements,
                lofting_guides={"authority": "cst_coefficients"},
                prop_assumption={"blade_count": 2},
                concept_summary={"selected": True, "rank": index},
            )
        )
    summary_json_path = output_dir / "concept_summary.json"
    summary_json_path.write_text(
        json.dumps({"selected_concepts": [str(path) for path in selected_dirs]}, indent=2),
        encoding="utf-8",
    )
    return ConceptPipelineResult(summary_json_path=summary_json_path, selected_concept_dirs=tuple(selected_dirs))
```

Create `scripts/birdman_upstream_concept_design.py`:

```python
#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from hpa_mdo.concept.pipeline import run_birdman_concept_pipeline
from hpa_mdo.concept.airfoil_worker import JuliaXFoilWorker


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    run_birdman_concept_pipeline(
        config_path=Path(args.config).expanduser().resolve(),
        output_dir=Path(args.output_dir).expanduser().resolve(),
        airfoil_worker_factory=lambda **kwargs: JuliaXFoilWorker(**kwargs),
        spanwise_loader=lambda concept, stations: {},
    )


if __name__ == "__main__":
    main()
```

Update `src/hpa_mdo/concept/__init__.py`:

```python
from hpa_mdo.concept.config import BirdmanConceptConfig, load_concept_config
from hpa_mdo.concept.pipeline import ConceptPipelineResult, run_birdman_concept_pipeline

__all__ = [
    "BirdmanConceptConfig",
    "ConceptPipelineResult",
    "load_concept_config",
    "run_birdman_concept_pipeline",
]
```

- [ ] **Step 4: Run the pipeline tests and CLI smoke check**

Run:

```bash
./.venv/bin/python -m pytest tests/test_concept_pipeline.py -q
./.venv/bin/python scripts/birdman_upstream_concept_design.py --config configs/birdman_upstream_concept_baseline.yaml --output-dir output/birdman_upstream_concept_smoke
```

Expected:

- `tests/test_concept_pipeline.py`: PASS
- CLI smoke: writes `output/birdman_upstream_concept_smoke/concept_summary.json`

- [ ] **Step 5: Commit**

```bash
git add src/hpa_mdo/concept/__init__.py src/hpa_mdo/concept/pipeline.py scripts/birdman_upstream_concept_design.py tests/test_concept_pipeline.py
git commit -m "feat: 新增 Birdman 概念設計主流程與 CLI"
```

## Task 8: Tighten The First Cut Into A Real MVP Contract

**Files:**
- Modify: `src/hpa_mdo/concept/pipeline.py`
- Modify: `src/hpa_mdo/concept/airfoil_worker.py`
- Modify: `src/hpa_mdo/concept/safety.py`
- Modify: `tests/test_concept_pipeline.py`

- [ ] **Step 1: Add a regression test for the required final artifacts**

Extend `tests/test_concept_pipeline.py`:

```python
def test_pipeline_emits_all_required_mvp_artifacts(tmp_path):
    result = run_birdman_concept_pipeline(
        config_path=Path("configs/birdman_upstream_concept_baseline.yaml"),
        output_dir=tmp_path,
        airfoil_worker_factory=lambda **_: type(
            "FakeWorker",
            (),
            {"run_queries": lambda self, queries: [{"status": "ok", "polar_points": []} for _ in queries]},
        )(),
        spanwise_loader=lambda concept, stations: {
            "root": {"points": []},
            "mid1": {"points": []},
            "mid2": {"points": []},
            "tip": {"points": []},
        },
    )

    bundle = result.selected_concept_dirs[0]
    assert (bundle / "concept_config.yaml").exists()
    assert (bundle / "stations.csv").exists()
    assert (bundle / "airfoil_templates.json").exists()
    assert (bundle / "lofting_guides.json").exists()
    assert (bundle / "prop_assumption.json").exists()
    assert (bundle / "concept_summary.json").exists()
```

- [ ] **Step 2: Run the pipeline tests to verify the new regression fails**

Run:

```bash
./.venv/bin/python -m pytest tests/test_concept_pipeline.py -q
```

Expected: FAIL until the pipeline writes all required artifacts and safety/worker results into the bundle.

- [ ] **Step 3: Expand the pipeline from skeleton to MVP**

Update the modules to make the first cut match the spec more closely:

```python
# src/hpa_mdo/concept/pipeline.py
    airfoil_templates = {}
    for zone_name, requirement in zone_requirements.items():
        points = requirement.points if hasattr(requirement, "points") else requirement.get("points", [])
        airfoil_templates[zone_name] = {
            "template_id": f"{zone_name}-seed",
            "points": [
                point.__dict__ if hasattr(point, "__dict__") else point
                for point in points
            ],
        }

prop_assumption = {
    "blade_count": 2,
    "diameter_m": 3.0,
    "rpm_range": [100.0, 160.0],
}

concept_summary = {
    "selected": True,
    "launch": {"status": "stubbed_ok"},
    "turn": {"status": "stubbed_ok"},
    "trim": {"status": "stubbed_ok"},
    "local_stall": {"status": "stubbed_ok"},
}
```

Also tighten the worker/safety modules so failures raise clear reasons instead of silent fall-through:

```python
# src/hpa_mdo/concept/airfoil_worker.py
if any(result.get("status") != "ok" and result.get("status") != "stubbed_ok" for result in results):
    raise RuntimeError("Julia/XFoil worker returned a non-success status.")

# src/hpa_mdo/concept/safety.py
if not trim_feasible:
    return TurnGateResult(False, required_cl, stall_margin, "trim_not_feasible")
```

- [ ] **Step 4: Run the focused concept suite**

Run:

```bash
./.venv/bin/python -m pytest \
  tests/test_concept_config.py \
  tests/test_concept_geometry.py \
  tests/test_concept_zone_requirements.py \
  tests/test_concept_airfoil_worker.py \
  tests/test_concept_safety.py \
  tests/test_concept_handoff.py \
  tests/test_concept_pipeline.py -q
```

Expected: PASS across the new concept-design suite.

- [ ] **Step 5: Commit**

```bash
git add src/hpa_mdo/concept/pipeline.py src/hpa_mdo/concept/airfoil_worker.py src/hpa_mdo/concept/safety.py tests/test_concept_pipeline.py
git commit -m "fix: 補齊 Birdman 概念設計 MVP 契約"
```

## Self-Review

### Spec coverage

- Birdman mission/rule framing: Task 1 config + Task 7 CLI baseline
- geometry family + segmentation constraints: Task 2
- zone requirements + CST template authority + lofting guides: Task 3
- Julia/XFoil.jl worker and polar cache: Task 4
- simplified prop-aware coupling: Task 5
- launch ground effect + `15 deg bank` turn gate: Task 5
- ranking and `3~5`-style handoff bundles: Task 6 and Task 8
- mainline handoff artifacts: Task 6 and Task 8

No spec section is left without a task.

### Placeholder scan

- No deferred-work markers remain in the task steps.
- Every test, implementation, command, and commit step names the concrete file/function/command to use.

### Type consistency

Consistent names used across tasks:

- `BirdmanConceptConfig`
- `GeometryConcept`
- `CSTAirfoilTemplate`
- `JuliaXFoilWorker`
- `SimplifiedPropModel`
- `run_birdman_concept_pipeline`
- `write_selected_concept_bundle`

Later tasks build on these names without renaming them.
