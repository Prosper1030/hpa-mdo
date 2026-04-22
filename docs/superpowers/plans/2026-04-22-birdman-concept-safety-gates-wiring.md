# Birdman Concept Safety Gates Wiring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Birdman upstream concept line's `launch / turn / trim / local_stall` placeholder summaries with real first-version safety judgments driven by the current YAML input surface.

**Architecture:** Keep the current concept pipeline structure intact, but extend `src/hpa_mdo/concept/safety.py` into a small, honest safety-evaluation module and wire `src/hpa_mdo/concept/pipeline.py` to derive representative concept-level safety inputs from the current stations and zone requirements. This remains a coarse concept-design filter, not a full mission solver.

**Tech Stack:** Python 3, current `hpa_mdo.concept` package, `pytest` via `../../.venv/bin/python -m pytest`, YAML/JSON concept artifacts.

---

## Scope Check

This plan is one implementation wave because all changes serve the same narrow objective:

- normalize the safety-threshold config into an engineering-usable form
- extend the concept safety contract
- wire those safety results into the concept pipeline
- verify with tests and a CLI smoke run

It does **not** include full mission-power coupling, high-fidelity launch dynamics, or route simulation.

## File Structure

### Modify

- `src/hpa_mdo/concept/config.py`
  - Tighten/clarify the safety-related config contract, especially `launch.min_stall_margin`.
- `configs/birdman_upstream_concept_baseline.yaml`
  - Keep the baseline YAML physically reasonable for the new first-version safety interpretation.
- `src/hpa_mdo/concept/safety.py`
  - Add trim/local-stall evaluators and make launch/turn thresholds configurable.
- `src/hpa_mdo/concept/pipeline.py`
  - Derive representative safety state from concept geometry + zone requirements and serialize the results.
- `tests/test_concept_config.py`
  - Validate the updated safety-threshold config behavior.
- `tests/test_concept_safety.py`
  - Cover new safety evaluators and threshold-sensitive behavior.
- `tests/test_concept_pipeline.py`
  - Cover pipeline wiring so `concept_summary.json` no longer reports unconditional placeholders.

### No New Runtime Files

- Reuse the existing `concept` package layout.
- Do **not** add a separate mission solver module in this wave.

## Engineering Note Before Implementation

The current baseline has:

```yaml
launch:
  min_stall_margin: 2.0
```

If interpreted as a `CL` headroom, `2.0` is not physically reasonable for this MVP. A first-version concept gate should work with a stall-margin threshold closer to `0.10` in `CL` headroom terms.

This plan therefore normalizes the config contract to:

- `launch.min_stall_margin` is a dimensionless `CL` headroom threshold
- baseline value becomes `0.10`

That keeps the safety gate numerically meaningful instead of baking nonsense into the code.

### Task 1: Normalize Safety-Threshold Config

**Files:**
- Modify: `src/hpa_mdo/concept/config.py`
- Modify: `configs/birdman_upstream_concept_baseline.yaml`
- Test: `tests/test_concept_config.py`

- [ ] **Step 1: Write the failing config tests**

Add these tests to `tests/test_concept_config.py`:

```python
def test_load_concept_config_reads_normalized_safety_thresholds():
    repo_root = Path(__file__).resolve().parents[1]
    cfg = load_concept_config(
        repo_root / "configs" / "birdman_upstream_concept_baseline.yaml"
    )

    assert cfg.launch.min_trim_margin_deg == pytest.approx(2.0)
    assert cfg.launch.min_stall_margin == pytest.approx(0.10)


def test_load_concept_config_rejects_nonphysical_stall_margin_threshold():
    with pytest.raises(ValueError, match="launch.min_stall_margin"):
        BirdmanConceptConfig.model_validate(
            {
                "environment": {"temperature_c": 33.0, "relative_humidity": 80.0},
                "mass": {
                    "pilot_mass_kg": 60.0,
                    "baseline_aircraft_mass_kg": 40.0,
                    "gross_mass_sweep_kg": [95.0, 100.0, 105.0],
                },
                "mission": {"target_distance_km": 42.195},
                "launch": {
                    "release_speed_mps": 8.0,
                    "release_rpm": 140.0,
                    "min_trim_margin_deg": 2.0,
                    "min_stall_margin": 2.0,
                    "platform_height_m": 10.0,
                    "runup_length_m": 10.0,
                },
                "prop": {
                    "blade_count": 2,
                    "diameter_m": 3.0,
                    "rpm_min": 100.0,
                    "rpm_max": 160.0,
                    "position_mode": "between_wing_and_tail",
                },
            }
        )
```

- [ ] **Step 2: Run the config tests to verify they fail**

Run:

```bash
PYTHONPATH=src ../../.venv/bin/python -m pytest tests/test_concept_config.py -q
```

Expected:

- FAIL because the baseline still uses `2.0`
- FAIL because the current config schema still accepts unbounded positive values

- [ ] **Step 3: Implement the normalized safety-threshold contract**

Update `src/hpa_mdo/concept/config.py`:

```python
class LaunchConfig(ConceptBaseModel):
    mode: Literal["restrained_pre_spin"] = "restrained_pre_spin"
    prop_ready_before_release: bool = True
    release_speed_mps: float = Field(8.0, gt=0.0)
    release_rpm: float = Field(140.0, gt=0.0)
    min_trim_margin_deg: float = Field(2.0, gt=0.0)
    min_stall_margin: float = Field(0.10, gt=0.0, lt=1.0)
    platform_height_m: float = Field(10.0, gt=0.0)
    runup_length_m: float = Field(10.0, gt=0.0)
    use_ground_effect: bool = True
```

Update `configs/birdman_upstream_concept_baseline.yaml`:

```yaml
launch:
  mode: restrained_pre_spin
  prop_ready_before_release: true
  release_speed_mps: 8.0
  release_rpm: 140.0
  min_trim_margin_deg: 2.0
  min_stall_margin: 0.10
  platform_height_m: 10.0
  runup_length_m: 10.0
  use_ground_effect: true
```

- [ ] **Step 4: Run the config tests to verify they pass**

Run:

```bash
PYTHONPATH=src ../../.venv/bin/python -m pytest tests/test_concept_config.py -q
```

Expected:

- PASS

- [ ] **Step 5: Commit**

```bash
git add src/hpa_mdo/concept/config.py configs/birdman_upstream_concept_baseline.yaml tests/test_concept_config.py
git commit -m "fix: 正規化 Birdman concept 安全門檻設定"
```

### Task 2: Extend Safety Evaluators Beyond Placeholder Contracts

**Files:**
- Modify: `src/hpa_mdo/concept/safety.py`
- Test: `tests/test_concept_safety.py`

- [ ] **Step 1: Write the failing safety tests**

Update `tests/test_concept_safety.py` with these tests:

```python
from hpa_mdo.concept.safety import (
    evaluate_launch_gate,
    evaluate_local_stall,
    evaluate_trim_proxy,
    evaluate_turn_gate,
)


def test_launch_gate_respects_required_trim_margin():
    result = evaluate_launch_gate(
        platform_height_m=10.0,
        wing_span_m=32.0,
        speed_mps=8.0,
        cl_required=0.95,
        cl_available=1.10,
        trim_margin_deg=1.5,
        required_trim_margin_deg=2.0,
        use_ground_effect=True,
    )

    assert result.feasible is False
    assert result.reason == "trim_margin_insufficient"


def test_turn_gate_uses_configured_stall_margin_threshold():
    result = evaluate_turn_gate(
        bank_angle_deg=15.0,
        speed_mps=8.0,
        cl_level=0.95,
        cl_max=1.12,
        trim_feasible=True,
        required_stall_margin=0.10,
    )

    assert result.feasible is False
    assert result.reason == "stall_margin_insufficient"


def test_trim_proxy_flips_when_required_margin_is_tightened():
    loose = evaluate_trim_proxy(
        representative_cm=-0.10,
        required_margin_deg=1.5,
    )
    tight = evaluate_trim_proxy(
        representative_cm=-0.10,
        required_margin_deg=2.5,
    )

    assert loose.feasible is True
    assert tight.feasible is False
    assert tight.reason == "trim_margin_insufficient"


def test_local_stall_flags_tip_critical_case():
    result = evaluate_local_stall(
        station_points=[
            {"station_y_m": 1.0, "cl_target": 0.70, "cl_max_proxy": 0.92},
            {"station_y_m": 14.0, "cl_target": 0.82, "cl_max_proxy": 0.90},
        ],
        half_span_m=16.0,
        required_stall_margin=0.10,
    )

    assert result.feasible is False
    assert result.tip_critical is True
    assert result.min_margin_station_y_m == pytest.approx(14.0)
    assert result.reason == "stall_margin_insufficient"
```

- [ ] **Step 2: Run the safety tests to verify they fail**

Run:

```bash
PYTHONPATH=src ../../.venv/bin/python -m pytest tests/test_concept_safety.py -q
```

Expected:

- FAIL because `evaluate_launch_gate()` and `evaluate_turn_gate()` do not yet accept configurable thresholds
- FAIL because `evaluate_trim_proxy()` and `evaluate_local_stall()` do not exist yet

- [ ] **Step 3: Implement the minimal safety evaluators**

Update `src/hpa_mdo/concept/safety.py` with these additions:

```python
@dataclass(frozen=True)
class TrimGateResult:
    feasible: bool
    margin_deg: float
    required_margin_deg: float
    reason: str


@dataclass(frozen=True)
class LocalStallResult:
    feasible: bool
    min_margin: float
    min_margin_station_y_m: float
    tip_critical: bool
    reason: str


def evaluate_trim_proxy(
    *,
    representative_cm: float,
    required_margin_deg: float,
    cm_limit_abs: float = 0.15,
) -> TrimGateResult:
    if required_margin_deg <= 0.0:
        raise ValueError("required_margin_deg must be positive.")
    if cm_limit_abs <= 0.0:
        raise ValueError("cm_limit_abs must be positive.")

    margin_deg = max(
        0.0,
        6.0 * (cm_limit_abs - abs(float(representative_cm))) / cm_limit_abs,
    )
    feasible = margin_deg >= float(required_margin_deg)
    return TrimGateResult(
        feasible=feasible,
        margin_deg=margin_deg,
        required_margin_deg=float(required_margin_deg),
        reason="ok" if feasible else "trim_margin_insufficient",
    )


def evaluate_local_stall(
    *,
    station_points: list[dict[str, float]],
    half_span_m: float,
    required_stall_margin: float,
) -> LocalStallResult:
    if not station_points:
        raise ValueError("station_points must not be empty.")
    if half_span_m <= 0.0:
        raise ValueError("half_span_m must be positive.")
    if required_stall_margin <= 0.0:
        raise ValueError("required_stall_margin must be positive.")

    min_point = min(
        station_points,
        key=lambda item: float(item["cl_max_proxy"]) - float(item["cl_target"]),
    )
    min_margin = float(min_point["cl_max_proxy"]) - float(min_point["cl_target"])
    y_m = float(min_point["station_y_m"])
    tip_critical = y_m >= 0.75 * float(half_span_m)
    feasible = min_margin >= float(required_stall_margin)
    return LocalStallResult(
        feasible=feasible,
        min_margin=min_margin,
        min_margin_station_y_m=y_m,
        tip_critical=tip_critical,
        reason="ok" if feasible else "stall_margin_insufficient",
    )
```

Also update the existing evaluators:

```python
def evaluate_launch_gate(
    *,
    platform_height_m: float,
    wing_span_m: float,
    speed_mps: float,
    cl_required: float,
    cl_available: float,
    trim_margin_deg: float,
    required_trim_margin_deg: float,
    use_ground_effect: bool,
) -> LaunchGateResult:
    ...
    feasible = (
        float(cl_available) >= adjusted_cl_required
        and float(trim_margin_deg) >= float(required_trim_margin_deg)
    )
    if float(cl_available) < adjusted_cl_required:
        reason = "launch_cl_insufficient"
    elif float(trim_margin_deg) < float(required_trim_margin_deg):
        reason = "trim_margin_insufficient"
    else:
        reason = "ok"
```

```python
def evaluate_turn_gate(
    *,
    bank_angle_deg: float,
    speed_mps: float,
    cl_level: float,
    cl_max: float,
    trim_feasible: bool,
    required_stall_margin: float,
) -> TurnGateResult:
    ...
    feasible = bool(trim_feasible and stall_margin >= float(required_stall_margin))
```

- [ ] **Step 4: Run the safety tests to verify they pass**

Run:

```bash
PYTHONPATH=src ../../.venv/bin/python -m pytest tests/test_concept_safety.py -q
```

Expected:

- PASS

- [ ] **Step 5: Commit**

```bash
git add src/hpa_mdo/concept/safety.py tests/test_concept_safety.py
git commit -m "feat: 實作 Birdman concept 安全 gate 評估器"
```

### Task 3: Wire Safety Summaries Into The Concept Pipeline

**Files:**
- Modify: `src/hpa_mdo/concept/pipeline.py`
- Test: `tests/test_concept_pipeline.py`

- [ ] **Step 1: Write the failing pipeline tests**

Extend `tests/test_concept_pipeline.py` with:

```python
def test_pipeline_replaces_stubbed_safety_summary_with_numeric_outputs(tmp_path: Path) -> None:
    result = run_birdman_concept_pipeline(
        config_path=Path("configs/birdman_upstream_concept_baseline.yaml"),
        output_dir=tmp_path,
        airfoil_worker_factory=lambda **_: type(
            "FakeWorker",
            (),
            {"backend_name": "test_stub", "run_queries": lambda self, queries: []},
        )(),
        spanwise_loader=lambda concept, stations: {
            "root": {
                "points": [
                    {
                        "reynolds": 350000.0,
                        "cl_target": 0.70,
                        "cm_target": -0.08,
                        "weight": 1.0,
                        "station_y_m": 1.0,
                    }
                ]
            },
            "tip": {
                "points": [
                    {
                        "reynolds": 220000.0,
                        "cl_target": 0.82,
                        "cm_target": -0.10,
                        "weight": 1.0,
                        "station_y_m": 14.0,
                    }
                ]
            },
        },
    )

    bundle = result.selected_concept_dirs[0]
    concept_summary = json.loads((bundle / "concept_summary.json").read_text(encoding="utf-8"))

    assert concept_summary["launch"]["status"] in {"ok", "launch_cl_insufficient", "trim_margin_insufficient"}
    assert concept_summary["launch"]["status"] != "stubbed_ok"
    assert "adjusted_cl_required" in concept_summary["launch"]
    assert concept_summary["turn"]["status"] in {"ok", "stall_margin_insufficient", "trim_not_feasible"}
    assert "required_cl" in concept_summary["turn"]
    assert concept_summary["trim"]["status"] in {"ok", "trim_margin_insufficient"}
    assert "margin_deg" in concept_summary["trim"]
    assert concept_summary["local_stall"]["status"] in {"ok", "stall_margin_insufficient"}
    assert "min_margin" in concept_summary["local_stall"]
```

```python
def test_pipeline_summary_record_surfaces_safety_blocks(tmp_path: Path) -> None:
    result = run_birdman_concept_pipeline(
        config_path=Path("configs/birdman_upstream_concept_baseline.yaml"),
        output_dir=tmp_path,
        airfoil_worker_factory=lambda **_: type(
            "FakeWorker",
            (),
            {"backend_name": "test_stub", "run_queries": lambda self, queries: []},
        )(),
        spanwise_loader=lambda concept, stations: {"root": {"points": []}},
    )

    summary = json.loads(result.summary_json_path.read_text(encoding="utf-8"))
    first = summary["selected_concepts"][0]

    assert "launch" in first
    assert "turn" in first
    assert "trim" in first
    assert "local_stall" in first
```

- [ ] **Step 2: Run the pipeline tests to verify they fail**

Run:

```bash
PYTHONPATH=src ../../.venv/bin/python -m pytest tests/test_concept_pipeline.py -q
```

Expected:

- FAIL because the current pipeline still serializes `stubbed_ok`

- [ ] **Step 3: Implement representative safety-state wiring**

Add these helpers to `src/hpa_mdo/concept/pipeline.py`:

```python
def _air_density_from_environment(cfg: BirdmanConceptConfig) -> float:
    temp_c = float(cfg.environment.temperature_c)
    temp_k = temp_c + 273.15
    rel_humidity = float(cfg.environment.relative_humidity) / 100.0
    pressure_pa = 101325.0 * (1.0 - 2.25577e-5 * float(cfg.environment.altitude_m)) ** 5.25588
    saturation_vapor_pa = 610.94 * math.exp((17.625 * temp_c) / (temp_c + 243.04))
    vapor_pa = rel_humidity * saturation_vapor_pa
    dry_pa = pressure_pa - vapor_pa
    return dry_pa / (287.058 * temp_k) + vapor_pa / (461.495 * temp_k)


def _flatten_zone_points(zone_requirements: dict[str, dict[str, Any]]) -> list[dict[str, float]]:
    points: list[dict[str, float]] = []
    for zone_data in zone_requirements.values():
        for point in zone_data.get("points", []):
            points.append(
                {
                    "station_y_m": float(point.get("station_y_m", 0.0)),
                    "cl_target": float(point["cl_target"]),
                    "cm_target": float(point.get("cm_target", 0.0)),
                }
            )
    if not points:
        raise ValueError("zone_requirements must contain at least one point for safety evaluation.")
    return points


def _attach_cl_max_proxies(
    station_points: list[dict[str, float]],
    half_span_m: float,
) -> list[dict[str, float]]:
    enriched: list[dict[str, float]] = []
    for point in station_points:
        eta = 0.0 if half_span_m <= 0.0 else min(max(point["station_y_m"] / half_span_m, 0.0), 1.0)
        headroom = 0.20 - 0.08 * eta
        enriched.append(
            {
                **point,
                "cl_max_proxy": point["cl_target"] + headroom,
            }
        )
    return enriched
```

Then replace the hardcoded summary block inside `_concept_to_bundle_payload()` with:

```python
        "launch": launch_summary,
        "turn": turn_summary,
        "trim": trim_summary,
        "local_stall": local_stall_summary,
```

And inside `run_birdman_concept_pipeline()` compute safety like this:

```python
        station_points = _flatten_zone_points(zone_requirements)
        half_span_m = 0.5 * concept.span_m
        station_points = _attach_cl_max_proxies(station_points, half_span_m)

        representative_cm = max(abs(point["cm_target"]) for point in station_points)
        trim_result = evaluate_trim_proxy(
            representative_cm=-representative_cm,
            required_margin_deg=cfg.launch.min_trim_margin_deg,
        )

        rho = _air_density_from_environment(cfg)
        q = 0.5 * rho * cfg.launch.release_speed_mps**2
        gross_weight_n = max(cfg.mass.gross_mass_sweep_kg) * 9.80665
        cl_required = gross_weight_n / (q * concept.wing_area_m2)
        cl_available = max(point["cl_max_proxy"] for point in station_points)

        launch_result = evaluate_launch_gate(
            platform_height_m=cfg.launch.platform_height_m,
            wing_span_m=concept.span_m,
            speed_mps=cfg.launch.release_speed_mps,
            cl_required=cl_required,
            cl_available=cl_available,
            trim_margin_deg=trim_result.margin_deg,
            required_trim_margin_deg=cfg.launch.min_trim_margin_deg,
            use_ground_effect=cfg.launch.use_ground_effect,
        )

        representative_cl = max(point["cl_target"] for point in station_points)
        turn_result = evaluate_turn_gate(
            bank_angle_deg=cfg.turn.required_bank_angle_deg,
            speed_mps=cfg.launch.release_speed_mps,
            cl_level=representative_cl,
            cl_max=min(point["cl_max_proxy"] for point in station_points),
            trim_feasible=trim_result.feasible,
            required_stall_margin=cfg.launch.min_stall_margin,
        )

        local_stall_result = evaluate_local_stall(
            station_points=station_points,
            half_span_m=half_span_m,
            required_stall_margin=cfg.launch.min_stall_margin,
        )
```

Serialize the summaries explicitly:

```python
launch_summary = {
    "status": launch_result.reason,
    "feasible": launch_result.feasible,
    "adjusted_cl_required": launch_result.adjusted_cl_required,
    "cl_available": cl_available,
    "trim_margin_deg": trim_result.margin_deg,
    "release_speed_mps": cfg.launch.release_speed_mps,
    "ground_effect_applied": launch_result.ground_effect_applied,
}
```

```python
turn_summary = {
    "status": turn_result.reason,
    "feasible": turn_result.feasible,
    "required_cl": turn_result.required_cl,
    "stall_margin": turn_result.stall_margin,
    "bank_angle_deg": cfg.turn.required_bank_angle_deg,
}
```

```python
trim_summary = {
    "status": trim_result.reason,
    "feasible": trim_result.feasible,
    "margin_deg": trim_result.margin_deg,
    "required_margin_deg": trim_result.required_margin_deg,
}
```

```python
local_stall_summary = {
    "status": local_stall_result.reason,
    "feasible": local_stall_result.feasible,
    "min_margin": local_stall_result.min_margin,
    "min_margin_station_y_m": local_stall_result.min_margin_station_y_m,
    "tip_critical": local_stall_result.tip_critical,
}
```

- [ ] **Step 4: Run the pipeline tests to verify they pass**

Run:

```bash
PYTHONPATH=src ../../.venv/bin/python -m pytest tests/test_concept_pipeline.py -q
```

Expected:

- PASS

- [ ] **Step 5: Commit**

```bash
git add src/hpa_mdo/concept/pipeline.py tests/test_concept_pipeline.py
git commit -m "feat: 接上 Birdman concept 安全摘要判定"
```

### Task 4: Full Verification And Smoke Result

**Files:**
- No new code expected

- [ ] **Step 1: Run the full concept suite**

Run:

```bash
PYTHONPATH=src ../../.venv/bin/python -m pytest tests/test_concept_config.py tests/test_concept_geometry.py tests/test_concept_zone_requirements.py tests/test_concept_airfoil_worker.py tests/test_concept_safety.py tests/test_concept_handoff.py tests/test_concept_pipeline.py -q
```

Expected:

- PASS

- [ ] **Step 2: Run a CLI smoke**

Run:

```bash
PYTHONPATH=src ../../.venv/bin/python scripts/birdman_upstream_concept_design.py --config configs/birdman_upstream_concept_baseline.yaml --output-dir output/birdman_upstream_concept_safety_smoke
```

Expected:

- exit code `0`
- writes `output/birdman_upstream_concept_safety_smoke/concept_summary.json`
- per-concept bundles contain non-stubbed `launch / turn / trim / local_stall`

- [ ] **Step 3: Inspect the smoke outputs**

Run:

```bash
python3 - <<'PY'
from pathlib import Path
import json

root = Path("output/birdman_upstream_concept_safety_smoke")
summary = json.loads((root / "concept_summary.json").read_text(encoding="utf-8"))
first_bundle = Path(summary["selected_concepts"][0]["bundle_dir"])
concept_summary = json.loads((first_bundle / "concept_summary.json").read_text(encoding="utf-8"))

print("worker_backend =", summary["worker_backend"])
print("selected_count =", len(summary["selected_concepts"]))
print("launch =", concept_summary["launch"])
print("turn =", concept_summary["turn"])
print("trim =", concept_summary["trim"])
print("local_stall =", concept_summary["local_stall"])
PY
```

Expected:

- numeric fields present in all four safety blocks
- no unconditional `stubbed_ok`

- [ ] **Step 4: Commit smoke-safe follow-ups only if needed**

If the verification steps forced a tiny fix, commit only those changes:

```bash
git add <task-specific-files>
git commit -m "fix: 修正 Birdman concept 安全摘要 smoke 問題"
```
