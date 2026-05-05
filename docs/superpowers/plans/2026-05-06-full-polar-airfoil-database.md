# Full Polar Airfoil Database Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the CST/NSGA target-Cl screening workflow into a reusable full-polar airfoil database plus a mission/zone query layer.

**Architecture:** Keep the existing CST/NSGA screening outputs as a candidate discovery layer, but downgrade their labels so they are never mistaken for final full-polar evidence. Add a raw reusable polar archive keyed by airfoil geometry, Re, alpha, roughness, and worker settings, then add a mission-specific query layer that can be regenerated quickly from MissionContract, FourierTarget, loaded-shape AVL, and zone envelopes.

**Tech Stack:** Python dataclasses, CSV/JSON artifacts, existing `hpa_mdo.airfoils.database`, existing `hpa_mdo.airfoils.cst_database_builder`, existing persistent Julia/XFoil worker in `hpa_mdo.concept.airfoil_worker`, pytest, AVL sidecar smoke route.

---

## Current Rescue Findings To Preserve

- Tip rescue completed with `tip` generation 0-7, `1024` evaluated candidates, and `1024` `cst_xfoil_mission_grade_candidate` records under the current target-Cl screening rules.
- The current generated DB is still screening-grade because it uses `analysis_mode="screening_target_cl"` and sparse target-Cl work points, not a reusable full alpha polar.
- `scripts/birdman_spanload_design_smoke.py` currently loads the CST DB for zone top-k diagnostics, but `_sidecar_available_airfoil_ids()` only permits fixed seed/DAE geometry IDs for AVL rerun combinations. As a result, the CST DB is visible in `zone_airfoil_topk`, but CST candidates are not yet emitted as actual sidecar AVL combinations.
- No aircraft main ranking or hard gates should change in this upgrade.

## File Structure

- Modify `src/hpa_mdo/airfoils/database.py`
  - Extend schema for full-polar records, raw polar rows, quality flags, and mission query results while keeping existing lookup behavior compatible.
- Modify `src/hpa_mdo/airfoils/cst_database_builder.py`
  - Relabel current target-Cl screening records as screening-grade and export enough screening metadata for full-polar shortlist selection.
- Create `src/hpa_mdo/airfoils/full_polar.py`
  - Own reusable full-polar dataclasses, alpha-sweep quality checks, derived aero metrics, and artifact read/write helpers.
- Create `src/hpa_mdo/airfoils/mission_query.py`
  - Own mission/zone query, coverage gap detection, per-zone ranking, and query output artifacts.
- Modify `src/hpa_mdo/airfoils/sidecar.py`
  - Allow sidecar combinations to use generated CST geometry paths from database records when explicitly enabled.
- Modify `scripts/birdman_spanload_design_smoke.py`
  - Add source-priority behavior for screening DB, full-polar DB, and mission query output without changing main ranking.
- Create `scripts/build_full_polar_airfoil_db.py`
  - Build full alpha sweep database for a shortlist selected from existing screening outputs and seed airfoils.
- Create `scripts/query_airfoil_db_for_mission.py`
  - Query an existing full-polar archive for the current MissionContract/FourierTarget/loaded-shape AVL zone envelope.
- Create `scripts/gap_fill_airfoil_db.py`
  - Add only missing Re/alpha/roughness coverage to an existing full-polar archive.
- Create `tests/test_full_polar_airfoil_database.py`
  - Unit tests for schema, full-polar quality, alpha fitting, coverage, and gap detection.
- Modify `tests/test_cst_airfoil_database_builder.py`
  - Assert current CST/NSGA output is screening-grade, not full-polar mission-grade.
- Modify `tests/test_airfoil_sidecar.py` and `tests/test_birdman_spanload_design_smoke.py`
  - Assert sidecar preference order and no main ranking changes.
- Create `docs/airfoil_full_polar_database_workflow.md`
  - User-facing workflow for pilot/mission changes, query-only reuse, and gap-fill.

---

### Task 1: Relabel Current Target-Cl Screening Output

**Files:**
- Modify: `src/hpa_mdo/airfoils/cst_database_builder.py`
- Modify: `tests/test_cst_airfoil_database_builder.py`

- [ ] **Step 1: Write failing tests for screening labels**

Add tests that assert target-Cl screening records expose a screening label and do not claim full-polar status.

```python
def test_target_cl_screening_records_are_not_full_polar_mission_grade():
    result = _candidate_result(
        airfoil_id="cst_tip_screening_001",
        zone_name="tip",
        template=_valid_template(),
        envelope=_tip_envelope(),
        work_points=zone_work_points_from_envelope(_tip_envelope()),
        worker_results=_successful_target_cl_worker_results(),
        expected_query_count=10,
        backend_name="julia_xfoil",
        config=CSTZoneSearchConfig(),
        stage="nsga_generation_0",
    )

    assert result["screening_quality"] == "target_cl_screening_pass"
    assert result["source_quality"] == "cst_target_cl_screening_candidate"
    assert result["full_polar_quality"] == "not_full_polar_verified"
```

- [ ] **Step 2: Run the failing tests**

Run:

```bash
./.venv/bin/python -m pytest tests/test_cst_airfoil_database_builder.py::test_target_cl_screening_records_are_not_full_polar_mission_grade -q
```

Expected: FAIL because `screening_quality` and `full_polar_quality` do not exist yet, and successful screening currently uses `cst_xfoil_mission_grade_candidate`.

- [ ] **Step 3: Implement screening labels**

In `_candidate_result`, keep existing numeric metrics but change the quality label contract:

```python
if "cd_nonfinite_or_nonpositive" in issues or not finite_positive:
    source_quality = "cst_target_cl_screening_failed_not_mission_grade"
    screening_quality = "target_cl_screening_failed"
elif not real_xfoil_backend or issues:
    source_quality = "cst_target_cl_screening_candidate"
    screening_quality = "target_cl_screening_not_mission_grade"
else:
    source_quality = "cst_target_cl_screening_candidate"
    screening_quality = "target_cl_screening_pass"

full_polar_quality = "not_full_polar_verified"
```

Add these keys to the returned candidate dict:

```python
"screening_quality": screening_quality,
"full_polar_quality": full_polar_quality,
"screening_analysis_mode": "screening_target_cl",
```

- [ ] **Step 4: Keep backward-readable aggregate reports**

Where `source_quality_counts` are written, do not remove old fields from reports. Add `screening_quality_counts` beside `source_quality_counts`.

```python
"screening_quality_counts": dict(Counter(row.get("screening_quality", "unknown") for row in rows)),
```

- [ ] **Step 5: Run focused tests**

Run:

```bash
./.venv/bin/python -m pytest tests/test_cst_airfoil_database_builder.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add -p src/hpa_mdo/airfoils/cst_database_builder.py tests/test_cst_airfoil_database_builder.py
git commit -m "fix: label CST target-Cl screening quality"
```

---

### Task 2: Add Full-Polar Schema And Artifact IO

**Files:**
- Create: `src/hpa_mdo/airfoils/full_polar.py`
- Modify: `src/hpa_mdo/airfoils/database.py`
- Create: `tests/test_full_polar_airfoil_database.py`

- [ ] **Step 1: Write schema load/save tests**

```python
def test_full_polar_artifact_round_trips(tmp_path):
    artifact = FullPolarDatabaseArtifact(
        records=[
            FullPolarAirfoilRecord(
                airfoil_id="cst_tip_demo",
                zone_origin="tip",
                cst_upper=(0.1, 0.2, 0.3),
                cst_lower=(-0.1, -0.05, -0.02),
                coordinate_path="coordinates/cst_tip_demo.dat",
                geometry_hash="abc123",
                thickness_ratio=0.13,
                max_camber=0.04,
                max_thickness_x=0.31,
                trailing_edge_thickness=0.002,
                spar_depth_25_35_percent=0.11,
                source="cst_nsga_screening",
                screening_metadata={"original_zone": "tip", "generation": 7},
                full_polar_metadata=FullPolarBuildMetadata(
                    re_grid=(100000.0, 150000.0),
                    alpha_grid=(-6.0, -5.75),
                    roughness_modes=("clean",),
                    panel_count=96,
                    max_iterations=40,
                    worker_version="julia_xfoil_worker_v1",
                    build_timestamp_utc="2026-05-06T00:00:00Z",
                    cache_key="cache-demo",
                    geometry_hash="abc123",
                ),
                derived_metrics=FullPolarDerivedMetrics.empty(),
                source_quality="full_polar_candidate_not_mission_grade",
            )
        ],
        polar_points=[
            FullPolarPoint(
                airfoil_id="cst_tip_demo",
                Re=150000.0,
                roughness_mode="clean",
                alpha_deg=0.0,
                cl=0.4,
                cd=0.012,
                cm=-0.04,
                converged=True,
                warning_flags=(),
                branch_label="prestall",
            )
        ],
        run_metadata={"source": "unit_test"},
    )

    path = tmp_path / "full_polar_db.json"
    write_full_polar_database(artifact, path)
    loaded = load_full_polar_database(path)

    assert loaded.records[0].airfoil_id == "cst_tip_demo"
    assert loaded.polar_points[0].branch_label == "prestall"
```

- [ ] **Step 2: Run the failing test**

Run:

```bash
./.venv/bin/python -m pytest tests/test_full_polar_airfoil_database.py::test_full_polar_artifact_round_trips -q
```

Expected: FAIL because the module and dataclasses do not exist.

- [ ] **Step 3: Implement dataclasses**

Create `src/hpa_mdo/airfoils/full_polar.py` with:

```python
@dataclass(frozen=True)
class FullPolarPoint:
    airfoil_id: str
    Re: float
    roughness_mode: str
    alpha_deg: float
    cl: float
    cd: float
    cm: float
    converged: bool
    warning_flags: tuple[str, ...] = ()
    branch_label: str = "unknown"


@dataclass(frozen=True)
class FullPolarBuildMetadata:
    re_grid: tuple[float, ...]
    alpha_grid: tuple[float, ...]
    roughness_modes: tuple[str, ...]
    panel_count: int
    max_iterations: int
    worker_version: str
    build_timestamp_utc: str
    cache_key: str
    geometry_hash: str


@dataclass(frozen=True)
class FullPolarDerivedMetrics:
    alpha_L0_deg: float
    cl_alpha_per_rad: float
    usable_clmax: float
    safe_clmax: float
    cd_min: float
    cd_p90_over_zone: float
    cm_mean: float
    roughness_sensitivity: float
    convergence_pass_rate: float
    polar_continuity_flags: tuple[str, ...]
    pre_stall_branch_valid: bool

    @classmethod
    def empty(cls) -> "FullPolarDerivedMetrics":
        return cls(
            alpha_L0_deg=float("nan"),
            cl_alpha_per_rad=float("nan"),
            usable_clmax=float("nan"),
            safe_clmax=float("nan"),
            cd_min=float("nan"),
            cd_p90_over_zone=float("nan"),
            cm_mean=float("nan"),
            roughness_sensitivity=float("nan"),
            convergence_pass_rate=0.0,
            polar_continuity_flags=(),
            pre_stall_branch_valid=False,
        )
```

Add `FullPolarAirfoilRecord`, `FullPolarDatabaseArtifact`, `to_dict`, `from_dict`, `write_full_polar_database`, and `load_full_polar_database` in the same module.

- [ ] **Step 4: Export schema from package**

Add these names to `src/hpa_mdo/airfoils/__init__.py`:

```python
from .full_polar import (
    FullPolarAirfoilRecord,
    FullPolarBuildMetadata,
    FullPolarDatabaseArtifact,
    FullPolarDerivedMetrics,
    FullPolarPoint,
    load_full_polar_database,
    write_full_polar_database,
)
```

- [ ] **Step 5: Run tests**

Run:

```bash
./.venv/bin/python -m pytest tests/test_full_polar_airfoil_database.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add -p src/hpa_mdo/airfoils/full_polar.py src/hpa_mdo/airfoils/__init__.py tests/test_full_polar_airfoil_database.py
git commit -m "feat: add full-polar airfoil database schema"
```

---

### Task 3: Implement Full Alpha Sweep Quality Metrics

**Files:**
- Modify: `src/hpa_mdo/airfoils/full_polar.py`
- Modify: `tests/test_full_polar_airfoil_database.py`

- [ ] **Step 1: Write fitting and Clmax tests**

```python
def test_alpha_l0_and_cl_alpha_fit_use_linear_cl_range_only():
    points = [
        FullPolarPoint("af", 200000.0, "clean", -2.0, 0.0, 0.011, -0.04, True),
        FullPolarPoint("af", 200000.0, "clean", 0.0, 0.22, 0.010, -0.04, True),
        FullPolarPoint("af", 200000.0, "clean", 4.0, 0.66, 0.012, -0.04, True),
        FullPolarPoint("af", 200000.0, "clean", 8.0, 1.10, 0.018, -0.04, True),
        FullPolarPoint("af", 200000.0, "clean", 12.0, 1.18, 0.080, -0.06, True),
    ]

    metrics = derive_full_polar_metrics(points, zone_work_points=())

    assert metrics.cl_alpha_per_rad > 5.0
    assert metrics.usable_clmax == pytest.approx(1.18)
    assert metrics.safe_clmax == pytest.approx(0.90 * 1.18 - 0.05)
```

```python
def test_true_usable_clmax_can_exceed_target_cl_screening_max():
    points = [
        FullPolarPoint("af", 200000.0, "clean", 0.0, 0.3, 0.010, -0.03, True),
        FullPolarPoint("af", 200000.0, "clean", 4.0, 0.8, 0.012, -0.03, True),
        FullPolarPoint("af", 200000.0, "clean", 8.0, 1.35, 0.021, -0.04, True),
    ]

    metrics = derive_full_polar_metrics(points, zone_work_points=())

    assert metrics.usable_clmax == pytest.approx(1.35)
```

- [ ] **Step 2: Run tests and confirm failure**

```bash
./.venv/bin/python -m pytest tests/test_full_polar_airfoil_database.py::test_alpha_l0_and_cl_alpha_fit_use_linear_cl_range_only tests/test_full_polar_airfoil_database.py::test_true_usable_clmax_can_exceed_target_cl_screening_max -q
```

Expected: FAIL because `derive_full_polar_metrics` does not exist.

- [ ] **Step 3: Implement metrics**

Add:

```python
def derive_full_polar_metrics(
    points: Sequence[FullPolarPoint],
    *,
    zone_work_points: Sequence[Mapping[str, float]],
) -> FullPolarDerivedMetrics:
    converged = [p for p in points if p.converged and math.isfinite(p.cl) and math.isfinite(p.cd)]
    finite_cd = [p for p in converged if p.cd >= 0.0]
    pass_rate = len(finite_cd) / max(1, len(points))
    linear = [p for p in finite_cd if 0.1 <= p.cl <= 1.1]
    alpha_l0, cl_alpha = fit_linear_lift_curve(linear)
    usable_clmax = max((p.cl for p in finite_cd), default=float("nan"))
    safe_clmax = 0.90 * usable_clmax - 0.05 if math.isfinite(usable_clmax) else float("nan")
    cd_values = [p.cd for p in finite_cd]
    cm_values = [p.cm for p in finite_cd if math.isfinite(p.cm)]
    flags = detect_polar_continuity_flags(finite_cd)
    return FullPolarDerivedMetrics(
        alpha_L0_deg=alpha_l0,
        cl_alpha_per_rad=cl_alpha,
        usable_clmax=usable_clmax,
        safe_clmax=safe_clmax,
        cd_min=min(cd_values) if cd_values else float("nan"),
        cd_p90_over_zone=cd_p90_at_work_points(finite_cd, zone_work_points),
        cm_mean=float(np.mean(cm_values)) if cm_values else float("nan"),
        roughness_sensitivity=roughness_sensitivity_at_work_points(finite_cd, zone_work_points),
        convergence_pass_rate=pass_rate,
        polar_continuity_flags=tuple(flags),
        pre_stall_branch_valid="non_monotonic_cl_alpha_prestall" not in flags,
    )
```

- [ ] **Step 4: Add nonphysical Cd quality tests**

```python
def test_negative_cd_downgrades_full_polar_quality():
    points = [
        FullPolarPoint("af", 200000.0, "clean", 0.0, 0.3, -0.001, -0.03, True),
        FullPolarPoint("af", 200000.0, "clean", 2.0, 0.5, 0.011, -0.03, True),
    ]

    quality = classify_full_polar_quality(
        points,
        zone_envelope=_zone_envelope(),
        metadata_complete=True,
    )

    assert quality.source_quality == "full_polar_failed_not_mission_grade"
    assert "negative_cd" in quality.flags
```

- [ ] **Step 5: Run tests**

```bash
./.venv/bin/python -m pytest tests/test_full_polar_airfoil_database.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add -p src/hpa_mdo/airfoils/full_polar.py tests/test_full_polar_airfoil_database.py
git commit -m "feat: derive full-polar airfoil quality metrics"
```

---

### Task 4: Build Full-Polar Verification CLI

**Files:**
- Create: `scripts/build_full_polar_airfoil_db.py`
- Modify: `src/hpa_mdo/airfoils/full_polar.py`
- Modify: `tests/test_full_polar_airfoil_database.py`

- [ ] **Step 1: Write dry-run CLI test**

```python
def test_full_polar_builder_dry_run_creates_archive(tmp_path):
    screening_dir = tmp_path / "screening"
    screening_dir.mkdir()
    _write_minimal_screening_artifacts(screening_dir)
    output_dir = tmp_path / "full_polar"

    result = subprocess.run(
        [
            sys.executable,
            "scripts/build_full_polar_airfoil_db.py",
            "--screening-output-dir",
            str(screening_dir),
            "--zone-envelope-json",
            str(screening_dir / "zone_envelope.json"),
            "--output-dir",
            str(output_dir),
            "--dry-run",
            "--top-k-per-zone",
            "2",
            "--pareto-per-zone",
            "2",
        ],
        check=True,
        text=True,
        capture_output=True,
    )

    assert (output_dir / "airfoil_records.json").is_file()
    assert (output_dir / "polar_points.csv").is_file()
    assert (output_dir / "full_polar_build_report.json").is_file()
    assert "full_polar_build_report" in result.stdout
```

- [ ] **Step 2: Run failing CLI test**

```bash
./.venv/bin/python -m pytest tests/test_full_polar_airfoil_database.py::test_full_polar_builder_dry_run_creates_archive -q
```

Expected: FAIL because the script does not exist.

- [ ] **Step 3: Implement shortlist selection**

The script should select:

```python
selected = select_full_polar_shortlist(
    screening_output_dir=args.screening_output_dir,
    top_k_per_zone=args.top_k_per_zone,
    pareto_per_zone=args.pareto_per_zone,
    include_seed_airfoils=args.include_seed_airfoils,
)
```

Selection rules:

```python
top_k_per_zone = 16
pareto_per_zone = 32
seed_airfoil_ids = ("fx76mp140", "clarkysm", "dae11", "dae21", "dae31", "dae41")
```

- [ ] **Step 4: Implement alpha/Re grid generation**

Use:

```python
GLOBAL_HPA_RE_GRID = (
    100_000.0, 125_000.0, 150_000.0, 175_000.0, 200_000.0,
    250_000.0, 300_000.0, 350_000.0, 400_000.0, 500_000.0,
    600_000.0, 700_000.0,
)

def alpha_grid(alpha_min: float = -6.0, alpha_max: float = 18.0, step: float = 0.25) -> tuple[float, ...]:
    count = int(round((alpha_max - alpha_min) / step))
    return tuple(round(alpha_min + index * step, 6) for index in range(count + 1))
```

The Re grid is:

```python
sorted(set(GLOBAL_HPA_RE_GRID + zone_re_points + robustness_re_points))
```

- [ ] **Step 5: Run persistent worker full alpha sweeps**

Use existing `JuliaXFoilWorker` and a new `analysis_mode="full_alpha_sweep"` query path. The dry-run backend should generate deterministic smooth polar points so CI does not require Julia.

- [ ] **Step 6: Write required artifacts**

Write:

```text
output/airfoil_db/full_polar_archive/
  airfoil_records.json
  airfoil_records.csv
  polar_points.csv
  full_polar_build_report.md
  full_polar_build_report.json
  quality_report.csv
  coverage_report.csv
  gap_report.csv
  per_zone_top_k.csv
  per_zone_pareto.csv
  run_metadata.json
```

- [ ] **Step 7: Run focused tests**

```bash
./.venv/bin/python -m pytest tests/test_full_polar_airfoil_database.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add -p scripts/build_full_polar_airfoil_db.py src/hpa_mdo/airfoils/full_polar.py tests/test_full_polar_airfoil_database.py
git commit -m "feat: build reusable full-polar airfoil archive"
```

---

### Task 5: Add Mission/Zone Query Layer

**Files:**
- Create: `src/hpa_mdo/airfoils/mission_query.py`
- Create: `scripts/query_airfoil_db_for_mission.py`
- Modify: `tests/test_full_polar_airfoil_database.py`

- [ ] **Step 1: Write rerank-without-XFOIL test**

```python
def test_query_layer_reranks_same_db_for_changed_zone_envelope_without_worker(tmp_path):
    db_path = _write_two_airfoil_full_polar_db(tmp_path)
    low_cl = _zone_envelope(zone_name="tip", re_min=250000.0, re_p50=300000.0, re_max=350000.0, cl_max=0.5)
    high_cl = _zone_envelope(zone_name="tip", re_min=250000.0, re_p50=300000.0, re_max=350000.0, cl_max=0.9)

    low_result = query_full_polar_database_for_zones(db_path, [low_cl])
    high_result = query_full_polar_database_for_zones(db_path, [high_cl])

    assert low_result.per_zone_top_k["tip"][0].airfoil_id != high_result.per_zone_top_k["tip"][0].airfoil_id
    assert low_result.worker_invocations == 0
    assert high_result.worker_invocations == 0
```

- [ ] **Step 2: Run failing test**

```bash
./.venv/bin/python -m pytest tests/test_full_polar_airfoil_database.py::test_query_layer_reranks_same_db_for_changed_zone_envelope_without_worker -q
```

Expected: FAIL because the query layer does not exist.

- [ ] **Step 3: Implement query result dataclasses**

In `mission_query.py` add:

```python
@dataclass(frozen=True)
class MissionAirfoilScore:
    zone_name: str
    airfoil_id: str
    mean_cd: float
    cd_p90: float
    min_stall_margin: float
    safe_clmax_margin: float
    roughness_sensitivity: float
    abs_cm_mean: float
    alpha_L0_penalty: float
    source_quality: str
    warnings: tuple[str, ...]
    score: float
```

```python
@dataclass(frozen=True)
class MissionAirfoilQueryResult:
    per_zone_top_k: dict[str, tuple[MissionAirfoilScore, ...]]
    per_zone_pareto: dict[str, tuple[MissionAirfoilScore, ...]]
    coverage_rows: tuple[dict[str, Any], ...]
    gap_rows: tuple[dict[str, Any], ...]
    worker_invocations: int = 0
```

- [ ] **Step 4: Implement scoring**

Rank by:

```python
score = (
    mean_cd
    + 0.35 * cd_p90
    + 0.002 * max(0.0, -safe_clmax_margin)
    + 0.001 * max(0.0, -min_stall_margin)
    + 0.25 * max(0.0, roughness_sensitivity)
    + 0.002 * abs_cm_mean
    + alpha_L0_penalty
    + source_quality_penalty
)
```

Use `source_quality_penalty = 0.0` for `full_polar_mission_grade_candidate`, `0.01` for `full_polar_candidate_not_mission_grade`, `0.05` for target-Cl screening candidates, and `0.10` for placeholders.

- [ ] **Step 5: Implement CLI output**

`scripts/query_airfoil_db_for_mission.py` writes:

```text
per_zone_top_k.csv
per_zone_pareto.csv
coverage_report.csv
gap_report.csv
run_metadata.json
```

- [ ] **Step 6: Run tests**

```bash
./.venv/bin/python -m pytest tests/test_full_polar_airfoil_database.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add -p src/hpa_mdo/airfoils/mission_query.py scripts/query_airfoil_db_for_mission.py tests/test_full_polar_airfoil_database.py
git commit -m "feat: query full-polar airfoils for mission zones"
```

---

### Task 6: Add Gap-Fill Mode

**Files:**
- Create: `scripts/gap_fill_airfoil_db.py`
- Modify: `src/hpa_mdo/airfoils/mission_query.py`
- Modify: `tests/test_full_polar_airfoil_database.py`

- [ ] **Step 1: Write missing coverage test**

```python
def test_gap_report_detects_missing_re_and_cl_coverage(tmp_path):
    db_path = _write_full_polar_db_with_re_range(tmp_path, re_values=(150000.0, 200000.0), cl_max=0.6)
    envelope = _zone_envelope(zone_name="tip", re_min=250000.0, re_p50=300000.0, re_max=388000.0, cl_max=0.8)

    result = query_full_polar_database_for_zones(db_path, [envelope])

    assert any(row["gap_type"] == "missing_re_coverage" for row in result.gap_rows)
    assert any(row["gap_type"] == "missing_cl_coverage" for row in result.gap_rows)
```

- [ ] **Step 2: Run failing test**

```bash
./.venv/bin/python -m pytest tests/test_full_polar_airfoil_database.py::test_gap_report_detects_missing_re_and_cl_coverage -q
```

Expected: FAIL until gap rows are implemented.

- [ ] **Step 3: Implement gap detection**

Add a helper:

```python
def required_gap_points(envelope: ZoneEnvelope, record: FullPolarAirfoilRecord) -> tuple[dict[str, Any], ...]:
    gaps = []
    if envelope.re_min < min(record.full_polar_metadata.re_grid):
        gaps.append({"gap_type": "missing_re_coverage", "required_re": envelope.re_min})
    if envelope.re_max > max(record.full_polar_metadata.re_grid):
        gaps.append({"gap_type": "missing_re_coverage", "required_re": envelope.re_max})
    if envelope.cl_max > record.derived_metrics.safe_clmax:
        gaps.append({"gap_type": "missing_cl_coverage", "required_cl": envelope.cl_max})
    if math.isfinite(envelope.max_fourier_target_cl) and envelope.max_fourier_target_cl > record.derived_metrics.safe_clmax:
        gaps.append({"gap_type": "missing_fourier_cl_coverage", "required_cl": envelope.max_fourier_target_cl})
    return tuple(gaps)
```

- [ ] **Step 4: Implement gap-fill CLI**

`scripts/gap_fill_airfoil_db.py` should:

```text
1. load existing full polar DB
2. load new zone envelope
3. select affected airfoils
4. run only missing Re/alpha/roughness sweeps
5. merge new points by (airfoil_id, Re, roughness_mode, alpha_deg)
6. rewrite DB artifact and gap_fill_report.md
```

- [ ] **Step 5: Run tests**

```bash
./.venv/bin/python -m pytest tests/test_full_polar_airfoil_database.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add -p scripts/gap_fill_airfoil_db.py src/hpa_mdo/airfoils/mission_query.py tests/test_full_polar_airfoil_database.py
git commit -m "feat: add full-polar airfoil gap fill"
```

---

### Task 7: Integrate Full-Polar And Screening DBs Into Sidecar

**Files:**
- Modify: `src/hpa_mdo/airfoils/sidecar.py`
- Modify: `scripts/birdman_spanload_design_smoke.py`
- Modify: `tests/test_airfoil_sidecar.py`
- Modify: `tests/test_birdman_spanload_design_smoke.py`

- [ ] **Step 1: Write sidecar source-priority test**

```python
def test_sidecar_prefers_full_polar_over_screening_and_placeholders():
    candidates = [
        {"airfoil_id": "seed", "source_quality": "manual_placeholder_not_mission_grade", "score": 0.001},
        {"airfoil_id": "screen", "source_quality": "cst_target_cl_screening_candidate", "score": 0.001},
        {"airfoil_id": "full", "source_quality": "full_polar_mission_grade_candidate", "score": 0.002},
    ]

    ranked = sorted(candidates, key=sidecar_source_priority_key)

    assert ranked[0]["airfoil_id"] == "full"
```

- [ ] **Step 2: Write CST-combination test**

```python
def test_sidecar_combination_generator_allows_cst_airfoil_with_coordinate_path():
    baseline = fixed_seed_zone_airfoil_assignments()
    topk = {"tip": [{"airfoil_id": "cst_tip_full_001", "source_quality": "full_polar_mission_grade_candidate"}]}
    available = {"fx76mp140", "clarkysm", "cst_tip_full_001"}

    combos = generate_airfoil_sidecar_combinations(
        baseline,
        topk,
        available_airfoil_ids=available,
        max_airfoil_combinations=4,
    )

    assert any(any(a.airfoil_id == "cst_tip_full_001" for a in combo) for combo in combos)
```

- [ ] **Step 3: Run failing tests**

```bash
./.venv/bin/python -m pytest tests/test_airfoil_sidecar.py::test_sidecar_combination_generator_allows_cst_airfoil_with_coordinate_path tests/test_birdman_spanload_design_smoke.py::test_sidecar_prefers_full_polar_over_screening_and_placeholders -q
```

Expected: FAIL because source priority and generated coordinate availability are not fully wired.

- [ ] **Step 4: Fix available airfoil IDs**

Replace the hardcoded sidecar availability behavior with a database-aware helper:

```python
def _sidecar_available_airfoil_ids(database: AirfoilDatabase) -> tuple[str, ...]:
    ids = set()
    for airfoil_id, record in database.records.items():
        if _airfoil_geometry_path(airfoil_id) is not None:
            ids.add(airfoil_id)
            continue
        coordinate_path = coordinate_path_from_record(record)
        if coordinate_path is not None and coordinate_path.is_file():
            ids.add(airfoil_id)
    return tuple(sorted(ids))
```

Generated CST airfoils must write their coordinate `.dat` files into each sidecar AVL case directory before AVL rerun.

- [ ] **Step 5: Add source priority**

Use:

```python
SOURCE_PRIORITY = {
    "full_polar_mission_grade_candidate": 0,
    "full_polar_candidate_not_mission_grade": 1,
    "cst_target_cl_screening_candidate": 2,
    "cst_xfoil_mission_grade_candidate": 2,
    "manual_xfoil_single_re_reference_not_mission_grade": 3,
    "manual_placeholder_not_mission_grade": 4,
}
```

Keep unknown qualities at priority `5`.

- [ ] **Step 6: Ensure profile drag uses rerun AVL actual Cl**

Keep the existing invariant:

```python
assert result["profile_drag_cl_source_shape_mode"] == "loaded_dihedral_avl"
```

Do not use Fourier target Cl for final profile drag integration.

- [ ] **Step 7: Run focused tests**

```bash
./.venv/bin/python -m pytest tests/test_airfoil_sidecar.py tests/test_birdman_spanload_design_smoke.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add -p src/hpa_mdo/airfoils/sidecar.py scripts/birdman_spanload_design_smoke.py tests/test_airfoil_sidecar.py tests/test_birdman_spanload_design_smoke.py
git commit -m "feat: let sidecar consume full-polar CST airfoils"
```

---

### Task 8: Document Pilot/Mission Change Workflow

**Files:**
- Create: `docs/airfoil_full_polar_database_workflow.md`
- Modify: `docs/superpowers/plans/2026-05-06-full-polar-airfoil-database.md`

- [ ] **Step 1: Write workflow doc**

Create a doc with this exact workflow:

```markdown
# Full-Polar Airfoil Database Workflow

## When Pilot Or Mission Changes

1. Update MissionContract inputs: pilot mass, power curve, selected speed, density, and non-wing drag budget.
2. Rerun loaded-shape AVL if geometry, speed, mass, or loaded dihedral changed.
3. Rebuild zone envelopes from loaded-shape AVL actual Cl/Re and FourierTarget.
4. Query the existing full-polar archive with `scripts/query_airfoil_db_for_mission.py`.
5. Rerank root/mid1/mid2/tip airfoil candidates at zone level.
6. Rerun Phase 4 sidecar combinations using loaded-shape AVL.
7. Run `scripts/gap_fill_airfoil_db.py` only if `gap_report.csv` shows missing Re/Cl/roughness coverage.

## When To Rerun CST/NSGA

Rerun CST/NSGA only when the new mission envelope is far outside the existing archive, no full-polar candidates satisfy the new zone constraints, or zone geometry requirements such as thickness/spar depth/manufacturability changed substantially.

## What Not To Do

Do not select station-by-station minimum-Cd airfoils. Do not change main aircraft ranking from sidecar output until the full-polar archive, sidecar AVL rerun, and mission drag budget are reviewed as engineering evidence.
```

- [ ] **Step 2: Run doc sanity check**

```bash
rg -n "station-by-station|full-polar|gap_fill|MissionContract|loaded-shape" docs/airfoil_full_polar_database_workflow.md
```

Expected: All required workflow terms appear.

- [ ] **Step 3: Commit**

```bash
git add -p docs/airfoil_full_polar_database_workflow.md docs/superpowers/plans/2026-05-06-full-polar-airfoil-database.md
git commit -m "docs: document reusable full-polar airfoil workflow"
```

---

## Verification Sequence

Run this before declaring implementation complete:

```bash
./.venv/bin/ruff check src/hpa_mdo/airfoils scripts/build_full_polar_airfoil_db.py scripts/query_airfoil_db_for_mission.py scripts/gap_fill_airfoil_db.py tests/test_full_polar_airfoil_database.py tests/test_airfoil_sidecar.py tests/test_birdman_spanload_design_smoke.py
./.venv/bin/python -m pytest tests/test_full_polar_airfoil_database.py tests/test_cst_airfoil_database_builder.py tests/test_airfoil_sidecar.py tests/test_birdman_spanload_design_smoke.py -q
PYTHONPATH=src ./.venv/bin/python scripts/build_full_polar_airfoil_db.py \
  --screening-output-dir output/airfoil_db/overnight_cst_zone_search \
  --zone-envelope-json output/airfoil_db/overnight_cst_zone_search/phase4_seed_sidecar_input/top_candidate_exports/rank_01_sample_0007/zone_envelope.json \
  --output-dir output/airfoil_db/full_polar_archive \
  --dry-run \
  --top-k-per-zone 2 \
  --pareto-per-zone 2
PYTHONPATH=src ./.venv/bin/python scripts/query_airfoil_db_for_mission.py \
  --full-polar-db output/airfoil_db/full_polar_archive/airfoil_records.json \
  --zone-envelope-json output/airfoil_db/overnight_cst_zone_search/phase4_seed_sidecar_input/top_candidate_exports/rank_01_sample_0007/zone_envelope.json \
  --output-dir output/airfoil_db/full_polar_archive/mission_query_smoke
```

Expected:

- Tests pass.
- Dry-run full-polar archive writes `airfoil_records.json`, `polar_points.csv`, and reports.
- Mission query writes top-k, Pareto, coverage, and gap reports without invoking XFOIL.
- Existing aircraft candidate ranking fields remain unchanged.

## Self-Review Checklist

- Every requested subsystem is represented: screening labels, full polar schema, alpha sweep builder, quality checks, mission query, gap fill, sidecar integration, pilot workflow, artifacts, tests.
- The plan preserves existing screening results and does not delete `output/airfoil_db/overnight_cst_zone_search`.
- The plan keeps zone-level top-k/Pareto selection and explicitly forbids station-by-station greedy min-Cd selection.
- The plan keeps final sidecar profile drag tied to AVL actual Cl from loaded-dihedral AVL.
- The plan does not introduce main aircraft ranking changes or hard gates.
- The plan fixes the observed sidecar limitation where CST candidates are visible in top-k but excluded from AVL rerun combinations.
