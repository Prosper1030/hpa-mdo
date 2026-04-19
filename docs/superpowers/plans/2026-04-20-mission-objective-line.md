# Mission Objective Line Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a mission-objective layer that supports `max_range` and `min_power`, uses a fake rider `P(t)` curve anchored at `300 W @ 30 min`, and exposes a configurable `target_range_km` requirement with `42.195 km` as the first default.

**Architecture:** Introduce a small mission module that owns rider power-duration modeling and speed-sweep mission evaluation, then thread its outputs into the existing outer-loop candidate summaries without replacing the current realizability mainline. Mission ranking remains additive: the new layer chooses which candidate is worth pushing downstream, while the existing inverse-design / CFRP flow still decides whether the design can actually be realized.

**Tech Stack:** Python 3, Pydantic config models, existing outer-loop scripts, `pytest` via `./.venv/bin/python -m pytest`

---

## File Structure

### New files

- `src/hpa_mdo/mission/__init__.py`
  - Public exports for the mission-objective layer.
- `src/hpa_mdo/mission/objective.py`
  - Rider model, fake `P(t)` utilities, inverse duration lookup, speed-sweep mission evaluator, and mission result dataclasses.
- `tests/test_mission_objective.py`
  - Unit tests for the fake rider curve, inversion, range / min-power evaluation, and `target_range_km` requirement behavior.

### Existing files to modify

- `src/hpa_mdo/core/config.py`
  - Add a small mission config surface with schema validation and defaults.
- `configs/blackcat_004.yaml`
  - Add default mission config values, including `target_range_km: 42.195`.
- `tests/test_config.py`
  - Verify mission config defaults and custom override behavior.
- `scripts/dihedral_sweep_campaign.py`
  - Attach mission evaluation to each campaign candidate, expose mission fields in CSV / JSON / text report, and let ranking honor `objective_mode`.
- `tests/test_dihedral_sweep_campaign.py`
  - Add focused tests for mission-aware campaign rows and winner selection.
- `scripts/direct_dual_beam_inverse_design_feasibility_sweep.py`
  - Mirror the same mission evaluation / reporting contract in feasibility sweep outputs.
- `tests/test_inverse_design.py`
  - Add focused tests for mission fields in feasibility summaries and selection outputs.

### Write-scope notes

- Do not reopen the inverse-design solver core for this feature.
- Do not mix transport / segmentation constraints into the first implementation.
- Do not add wind, launch, climb, or full mission segmentation in this plan.

## Task 1: Add Mission Config Surface

**Files:**
- Create: none
- Modify: `src/hpa_mdo/core/config.py`
- Modify: `configs/blackcat_004.yaml`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing config tests**

Add tests near the other config-default checks in `tests/test_config.py`:

```python
def test_blackcat_mission_defaults_loaded_from_config():
    repo_root = Path(__file__).resolve().parents[1]
    config_path = repo_root / "configs" / "blackcat_004.yaml"

    cfg = load_config(config_path)

    assert cfg.mission.objective_mode == "max_range"
    assert cfg.mission.target_range_km == pytest.approx(42.195)
    assert cfg.mission.speed_sweep_min_mps == pytest.approx(6.0)
    assert cfg.mission.speed_sweep_max_mps == pytest.approx(10.0)
    assert cfg.mission.speed_sweep_points == 9
    assert cfg.mission.rider_model == "fake_anchor_curve"
    assert cfg.mission.anchor_power_w == pytest.approx(300.0)
    assert cfg.mission.anchor_duration_min == pytest.approx(30.0)


def test_load_config_accepts_custom_mission_override(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    config_path = repo_root / "configs" / "blackcat_004.yaml"
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    data["mission"]["objective_mode"] = "min_power"
    data["mission"]["target_range_km"] = 21.0975
    data["mission"]["speed_sweep_points"] = 5

    cfg_path = tmp_path / "mission_override.yaml"
    cfg_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    cfg = load_config(cfg_path)

    assert cfg.mission.objective_mode == "min_power"
    assert cfg.mission.target_range_km == pytest.approx(21.0975)
    assert cfg.mission.speed_sweep_points == 5
```

- [ ] **Step 2: Run config tests to verify they fail**

Run:

```bash
./.venv/bin/python -m pytest tests/test_config.py -q
```

Expected: FAIL because `cfg.mission` does not exist yet.

- [ ] **Step 3: Add the minimal mission config schema**

Update `src/hpa_mdo/core/config.py` with a new config model plus a field on the root config:

```python
class MissionConfig(BaseModel):
    objective_mode: Literal["max_range", "min_power"] = "max_range"
    target_range_km: float = Field(42.195, gt=0.0)
    speed_sweep_min_mps: float = Field(6.0, gt=0.0)
    speed_sweep_max_mps: float = Field(10.0, gt=0.0)
    speed_sweep_points: int = Field(9, ge=2)
    rider_model: Literal["fake_anchor_curve"] = "fake_anchor_curve"
    anchor_power_w: float = Field(300.0, gt=0.0)
    anchor_duration_min: float = Field(30.0, gt=0.0)

    @model_validator(mode="after")
    def validate_speed_window(self) -> "MissionConfig":
        if self.speed_sweep_max_mps <= self.speed_sweep_min_mps:
            raise ValueError("mission.speed_sweep_max_mps must exceed mission.speed_sweep_min_mps.")
        return self
```

Attach it to the root config with a default factory:

```python
mission: MissionConfig = Field(default_factory=MissionConfig)
```

Update `configs/blackcat_004.yaml` with:

```yaml
mission:
  objective_mode: max_range
  target_range_km: 42.195
  speed_sweep_min_mps: 6.0
  speed_sweep_max_mps: 10.0
  speed_sweep_points: 9
  rider_model: fake_anchor_curve
  anchor_power_w: 300.0
  anchor_duration_min: 30.0
```

- [ ] **Step 4: Run config tests to verify they pass**

Run:

```bash
./.venv/bin/python -m pytest tests/test_config.py -q
```

Expected: PASS, including the new mission-default tests.

- [ ] **Step 5: Commit**

```bash
git add src/hpa_mdo/core/config.py configs/blackcat_004.yaml tests/test_config.py
git commit -m "feat: 新增 mission objective config"
```

## Task 2: Build The Mission Evaluator Module

**Files:**
- Create: `src/hpa_mdo/mission/__init__.py`
- Create: `src/hpa_mdo/mission/objective.py`
- Test: `tests/test_mission_objective.py`

- [ ] **Step 1: Write the failing mission-objective tests**

Create `tests/test_mission_objective.py`:

```python
from __future__ import annotations

import pytest

from hpa_mdo.mission.objective import (
    FakeAnchorCurve,
    MissionEvaluationInputs,
    evaluate_mission_objective,
)


def test_fake_anchor_curve_matches_anchor_point():
    curve = FakeAnchorCurve(anchor_power_w=300.0, anchor_duration_min=30.0)
    assert curve.power_at_duration_min(30.0) == pytest.approx(300.0)


def test_fake_anchor_curve_duration_drops_with_higher_power():
    curve = FakeAnchorCurve(anchor_power_w=300.0, anchor_duration_min=30.0)
    assert curve.duration_at_power_w(360.0) < curve.duration_at_power_w(300.0)


def test_evaluate_mission_objective_returns_best_range_and_target_margin():
    result = evaluate_mission_objective(
        MissionEvaluationInputs(
            objective_mode="max_range",
            target_range_km=42.195,
            speed_mps=[6.0, 7.0, 8.0, 9.0],
            power_required_w=[240.0, 255.0, 275.0, 320.0],
            rider_curve=FakeAnchorCurve(anchor_power_w=300.0, anchor_duration_min=30.0),
        )
    )

    assert result.best_range_m > 0.0
    assert result.best_range_speed_mps in {6.0, 7.0, 8.0, 9.0}
    assert result.target_range_km == pytest.approx(42.195)
    assert result.target_range_margin_m == pytest.approx(result.best_range_m - 42195.0)


def test_evaluate_mission_objective_returns_min_power_mode_metrics():
    result = evaluate_mission_objective(
        MissionEvaluationInputs(
            objective_mode="min_power",
            target_range_km=42.195,
            speed_mps=[6.0, 7.0, 8.0],
            power_required_w=[260.0, 220.0, 240.0],
            rider_curve=FakeAnchorCurve(anchor_power_w=300.0, anchor_duration_min=30.0),
        )
    )

    assert result.min_power_w == pytest.approx(220.0)
    assert result.min_power_speed_mps == pytest.approx(7.0)
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run:

```bash
./.venv/bin/python -m pytest tests/test_mission_objective.py -q
```

Expected: FAIL because `hpa_mdo.mission` does not exist yet.

- [ ] **Step 3: Implement the mission module**

Create `src/hpa_mdo/mission/objective.py` with a focused API:

```python
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Sequence


@dataclass(frozen=True)
class FakeAnchorCurve:
    anchor_power_w: float
    anchor_duration_min: float
    exponent: float = 0.15
    min_power_w: float = 180.0
    max_power_w: float = 450.0

    def power_at_duration_min(self, duration_min: float) -> float:
        raw = self.anchor_power_w * (self.anchor_duration_min / float(duration_min)) ** self.exponent
        return min(self.max_power_w, max(self.min_power_w, raw))

    def duration_at_power_w(self, power_w: float) -> float:
        clipped = min(self.max_power_w, max(self.min_power_w, float(power_w)))
        return self.anchor_duration_min * (self.anchor_power_w / clipped) ** (1.0 / self.exponent)


@dataclass(frozen=True)
class MissionEvaluationInputs:
    objective_mode: str
    target_range_km: float
    speed_mps: Sequence[float]
    power_required_w: Sequence[float]
    rider_curve: FakeAnchorCurve


@dataclass(frozen=True)
class MissionEvaluationResult:
    mission_objective_mode: str
    mission_feasible: bool
    target_range_km: float
    target_range_passed: bool
    target_range_margin_m: float
    best_range_m: float
    best_range_speed_mps: float
    best_endurance_s: float
    min_power_w: float
    min_power_speed_mps: float
    mission_score: float
    mission_score_reason: str
    pilot_power_model: str
    pilot_power_anchor: str
    speed_sweep_window_mps: tuple[float, float]


def evaluate_mission_objective(inputs: MissionEvaluationInputs) -> MissionEvaluationResult:
    speeds = [float(v) for v in inputs.speed_mps]
    powers = [float(p) for p in inputs.power_required_w]
    if len(speeds) != len(powers):
        raise ValueError("speed_mps and power_required_w must have the same length.")
    if len(speeds) < 2:
        raise ValueError("Need at least two sampled speeds for mission evaluation.")

    best_range_m = -math.inf
    best_range_speed = speeds[0]
    best_endurance_s = 0.0
    for speed_mps, power_w in zip(speeds, powers, strict=True):
        duration_min = inputs.rider_curve.duration_at_power_w(power_w)
        range_m = speed_mps * duration_min * 60.0
        if range_m > best_range_m:
            best_range_m = range_m
            best_range_speed = speed_mps
            best_endurance_s = duration_min * 60.0

    min_idx = min(range(len(powers)), key=lambda idx: powers[idx])
    min_power_w = powers[min_idx]
    min_power_speed_mps = speeds[min_idx]
    target_range_m = float(inputs.target_range_km) * 1000.0
    target_margin_m = best_range_m - target_range_m

    if inputs.objective_mode == "max_range":
        mission_score = -best_range_m
        reason = "maximize_range"
    elif inputs.objective_mode == "min_power":
        mission_score = min_power_w
        reason = "minimize_power"
    else:
        raise ValueError(f"Unsupported objective_mode: {inputs.objective_mode}")

    return MissionEvaluationResult(
        mission_objective_mode=str(inputs.objective_mode),
        mission_feasible=True,
        target_range_km=float(inputs.target_range_km),
        target_range_passed=bool(target_margin_m >= 0.0),
        target_range_margin_m=float(target_margin_m),
        best_range_m=float(best_range_m),
        best_range_speed_mps=float(best_range_speed),
        best_endurance_s=float(best_endurance_s),
        min_power_w=float(min_power_w),
        min_power_speed_mps=float(min_power_speed_mps),
        mission_score=float(mission_score),
        mission_score_reason=reason,
        pilot_power_model="fake_anchor_curve",
        pilot_power_anchor=f"{inputs.rider_curve.anchor_power_w:.1f}W@{inputs.rider_curve.anchor_duration_min:.1f}min",
        speed_sweep_window_mps=(float(min(speeds)), float(max(speeds))),
    )
```

Create `src/hpa_mdo/mission/__init__.py`:

```python
from hpa_mdo.mission.objective import (
    FakeAnchorCurve,
    MissionEvaluationInputs,
    MissionEvaluationResult,
    evaluate_mission_objective,
)

__all__ = [
    "FakeAnchorCurve",
    "MissionEvaluationInputs",
    "MissionEvaluationResult",
    "evaluate_mission_objective",
]
```

- [ ] **Step 4: Run the mission-objective tests to verify they pass**

Run:

```bash
./.venv/bin/python -m pytest tests/test_mission_objective.py -q
```

Expected: PASS, with the fake curve and both objective modes covered.

- [ ] **Step 5: Commit**

```bash
git add src/hpa_mdo/mission/__init__.py src/hpa_mdo/mission/objective.py tests/test_mission_objective.py
git commit -m "feat: 新增 mission objective evaluator"
```

## Task 3: Integrate Mission Metrics Into The Dihedral Campaign

**Files:**
- Modify: `scripts/dihedral_sweep_campaign.py`
- Test: `tests/test_dihedral_sweep_campaign.py`

- [ ] **Step 1: Write the failing campaign tests**

Add focused tests in `tests/test_dihedral_sweep_campaign.py`:

```python
def test_build_result_row_preserves_mission_fields_when_summary_payload_has_mission():
    summary_payload = {
        "mission": {
            "mission_objective_mode": "max_range",
            "mission_feasible": True,
            "target_range_km": 42.195,
            "target_range_passed": False,
            "target_range_margin_m": -1200.0,
            "best_range_m": 40995.0,
            "best_range_speed_mps": 7.5,
            "best_endurance_s": 5466.0,
            "min_power_w": 232.0,
            "min_power_speed_mps": 6.5,
            "mission_score": -40995.0,
            "mission_score_reason": "maximize_range",
            "pilot_power_model": "fake_anchor_curve",
            "pilot_power_anchor": "300.0W@30.0min",
            "speed_sweep_window_mps": [6.0, 10.0],
        }
    }
    row = _build_result_row(
        multiplier=1.0,
        dihedral_exponent=1.0,
        avl_eval=avl_eval,
        aero_perf_eval=aero_perf_eval,
        beta_eval=None,
        control_eval=None,
        summary_payload=summary_payload,
        selected_output_dir=None,
        summary_json_path=None,
        error_message=None,
    )

    assert row.best_range_m == 40995.0
    assert row.target_range_passed is False
    assert row.mission_objective_mode == "max_range"


def test_campaign_selection_prefers_better_mission_score_before_objective_value():
    worse_mass_better_range = replace(
        self._make_campaign_row(multiplier=1.0),
        objective_value_kg=25.0,
        mission_objective_mode="max_range",
        mission_score=-43000.0,
        best_range_m=43000.0,
        target_range_passed=True,
    )
    lighter_but_shorter = replace(
        self._make_campaign_row(multiplier=1.1),
        objective_value_kg=22.0,
        mission_objective_mode="max_range",
        mission_score=-41000.0,
        best_range_m=41000.0,
        target_range_passed=False,
    )

    annotated, winner_summary = _annotate_campaign_selection(
        [worse_mass_better_range, lighter_but_shorter],
        mission_objective_mode="max_range",
    )

    assert winner_summary["requested_knobs"]["dihedral_multiplier"] == pytest.approx(1.0)
```

- [ ] **Step 2: Run the campaign tests to verify they fail**

Run:

```bash
./.venv/bin/python -m pytest tests/test_dihedral_sweep_campaign.py -q
```

Expected: FAIL because `SweepResult` and selection helpers do not carry mission fields yet.

- [ ] **Step 3: Thread mission evaluation through the campaign script**

Make these focused changes in `scripts/dihedral_sweep_campaign.py`:

```python
from hpa_mdo.mission import FakeAnchorCurve, MissionEvaluationInputs, evaluate_mission_objective
```

Extend `SweepResult` with mission fields:

```python
    mission_objective_mode: str | None = None
    mission_feasible: bool | None = None
    target_range_km: float | None = None
    target_range_passed: bool | None = None
    target_range_margin_m: float | None = None
    best_range_m: float | None = None
    best_range_speed_mps: float | None = None
    best_endurance_s: float | None = None
    min_power_w: float | None = None
    min_power_speed_mps: float | None = None
    mission_score: float | None = None
    mission_score_reason: str | None = None
    pilot_power_model: str | None = None
    pilot_power_anchor: str | None = None
```

Add a small helper that evaluates mission on a narrow speed sweep using available per-speed power estimates:

```python
def _mission_snapshot_from_summary(cfg, summary_payload: dict[str, object] | None) -> dict[str, object]:
    mission = summary_payload.get("mission") if isinstance(summary_payload, dict) else None
    if isinstance(mission, dict):
        return dict(mission)
    return {}
```

For the first implementation, call the mission evaluator from the campaign path where candidate-level summary data is assembled, then store the mission fields on `SweepResult`, CSV, text report, and `winner_summary`.

Update ranking so `mission_objective_mode` can drive `candidate_score` ordering before `objective_value_kg`, while still keeping gate penalties intact.

- [ ] **Step 4: Run the campaign tests to verify they pass**

Run:

```bash
./.venv/bin/python -m pytest tests/test_dihedral_sweep_campaign.py -q
```

Expected: PASS, with mission fields visible on rows and winner selection honoring mission mode.

- [ ] **Step 5: Commit**

```bash
git add scripts/dihedral_sweep_campaign.py tests/test_dihedral_sweep_campaign.py
git commit -m "feat: mission objective 接入 dihedral campaign"
```

## Task 4: Integrate Mission Metrics Into The Feasibility Sweep

**Files:**
- Modify: `scripts/direct_dual_beam_inverse_design_feasibility_sweep.py`
- Test: `tests/test_inverse_design.py`

- [ ] **Step 1: Write the failing feasibility tests**

Add focused tests in `tests/test_inverse_design.py`:

```python
def test_feasibility_case_extracts_mission_snapshot_into_case_result():
    summary = {
        "mission": {
            "mission_objective_mode": "max_range",
            "mission_feasible": True,
            "target_range_km": 42.195,
            "target_range_passed": True,
            "target_range_margin_m": 805.0,
            "best_range_m": 43000.0,
            "best_range_speed_mps": 7.6,
            "best_endurance_s": 5657.0,
            "min_power_w": 228.0,
            "min_power_speed_mps": 6.8,
            "mission_score": -43000.0,
            "mission_score_reason": "maximize_range",
            "pilot_power_model": "fake_anchor_curve",
            "pilot_power_anchor": "300.0W@30.0min",
            "speed_sweep_window_mps": [6.0, 10.0],
        },
        "selected": {"objective_value_kg": 22.0},
    }
    snapshot = _extract_mission_snapshot(summary)
    assert snapshot["target_range_passed"] is True
    assert snapshot["best_range_m"] == pytest.approx(43000.0)


def test_feasibility_selection_prefers_better_mission_score_when_requested():
    better_range = FeasibilitySweepCaseResult(
        ...,
        mission_objective_mode="max_range",
        mission_score=-43000.0,
        best_range_m=43000.0,
        target_range_passed=True,
    )
    lower_mass_only = FeasibilitySweepCaseResult(
        ...,
        mission_objective_mode="max_range",
        mission_score=-41000.0,
        best_range_m=41000.0,
        target_range_passed=False,
    )
    cases, winner = _annotate_case_selection(
        [better_range, lower_mass_only],
        mission_objective_mode="max_range",
    )
    assert winner["candidate_score"] == better_range.candidate_score
```

Use the existing helper style in this file and fill omitted constructor fields with the same minimal values used by nearby tests.

- [ ] **Step 2: Run the feasibility-related tests to verify they fail**

Run:

```bash
./.venv/bin/python -m pytest tests/test_inverse_design.py -q
```

Expected: FAIL because feasibility summaries do not expose mission fields yet.

- [ ] **Step 3: Mirror the mission contract into the feasibility script**

Update `scripts/direct_dual_beam_inverse_design_feasibility_sweep.py`:

- extend `SweepCaseResult` with the same mission fields added to the campaign path
- add `_extract_mission_snapshot(summary)` parallel to the existing aero / recovery extractors
- include mission fields in summary text, JSON, and selection status
- allow top-level selection to honor `mission_objective_mode`

Minimal extraction helper:

```python
def _extract_mission_snapshot(summary: dict[str, object]) -> dict[str, object]:
    mission = summary.get("mission")
    if not isinstance(mission, dict):
        return {
            "mission_objective_mode": None,
            "mission_feasible": None,
            "target_range_km": None,
            "target_range_passed": None,
            "target_range_margin_m": None,
            "best_range_m": None,
            "best_range_speed_mps": None,
            "best_endurance_s": None,
            "min_power_w": None,
            "min_power_speed_mps": None,
            "mission_score": None,
            "mission_score_reason": None,
            "pilot_power_model": None,
            "pilot_power_anchor": None,
        }
    return dict(mission)
```

Update report text so each case visibly states:

- objective mode
- best range
- target-range pass/fail
- target-range margin
- min power

- [ ] **Step 4: Run the feasibility tests to verify they pass**

Run:

```bash
./.venv/bin/python -m pytest tests/test_inverse_design.py -q
```

Expected: PASS, with mission fields carried into feasibility summaries and selection.

- [ ] **Step 5: Commit**

```bash
git add scripts/direct_dual_beam_inverse_design_feasibility_sweep.py tests/test_inverse_design.py
git commit -m "feat: mission objective 接入 feasibility sweep"
```

## Self-Review

### Spec coverage

- Mission config surface: covered by Task 1.
- Fake rider curve and inversion: covered by Task 2.
- `max_range` and `min_power` switching: covered by Tasks 2, 3, and 4.
- `target_range_km = 42.195` requirement: covered by Tasks 1, 2, 3, and 4.
- Campaign / feasibility summaries and winner evidence: covered by Tasks 3 and 4.
- Future compatibility with real rider data and later airfoil work: preserved by the dedicated mission module in Task 2 and additive integration in Tasks 3 and 4.

### Placeholder scan

- No `TODO` / `TBD` markers remain.
- Each task includes explicit files, test commands, implementation snippets, and commit commands.

### Type consistency

- Mission config uses `objective_mode`, `target_range_km`, and rider anchor fields consistently.
- Mission result fields are named the same way across the module and both outer-loop consumer scripts.

Plan complete and saved to `docs/superpowers/plans/2026-04-20-mission-objective-line.md`. Two execution options:

1. Subagent-Driven (recommended) - I dispatch a fresh subagent per task, review between tasks, fast iteration

2. Inline Execution - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
