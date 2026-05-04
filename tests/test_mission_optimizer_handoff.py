import csv
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from hpa_mdo.mission import (
    FakeAnchorCurve,
    MissionQuickScreenResult,
    MissionDesignSpaceFilters,
    load_mission_design_space_spec,
)
from hpa_mdo.mission.design_space import build_candidate_seed_pool
from hpa_mdo.mission.optimizer_handoff import (
    MissionGateInput,
    evaluate_optimizer_mission_gate,
    assign_optimizer_seed_tier,
    assign_optimizer_exploration_tier,
)
from scripts.mission_design_space_explorer import (
    CANDIDATE_SEED_POOL_CSV_FILENAME,
    HUMAN_READABLE_SUMMARY_JSON_FILENAME,
    OPTIMIZER_HANDOFF_JSON_FILENAME,
    SUMMARY_JSON_FILENAME,
    run_mission_design_space,
)


def _build_result(
    *,
    speed_mps: float,
    span_m: float,
    aspect_ratio: float,
    cd0_total: float,
    mass_kg: float,
    oswald_e: float,
    cl_max_effective: float,
    cl_to_clmax_ratio: float,
    power_margin: float | None,
    power_passed: bool,
    cl_band: str,
    stall_band: str,
) -> MissionQuickScreenResult:
    return MissionQuickScreenResult(
        speed_mps=speed_mps,
        span_m=span_m,
        aspect_ratio=aspect_ratio,
        mass_kg=mass_kg,
        oswald_e=oswald_e,
        air_density_kg_m3=1.1357,
        eta_prop=0.86,
        eta_trans=0.96,
        wing_area_m2=30.0,
        cd0_total=cd0_total,
        required_time_min=100.0,
        cl_required=1.2,
        cd_induced=0.01,
        induced_power_air_w=80.0,
        parasite_power_air_w=100.0,
        total_power_air_w=180.0,
        required_crank_power_w=190.0,
        cl_max_effective=cl_max_effective,
        cl_to_clmax_ratio=cl_to_clmax_ratio,
        cl_margin_to_clmax=0.3,
        stall_speed_mps=5.8,
        stall_margin_speed_ratio=1.2,
        stall_band=stall_band,
        pilot_power_test_w=210.0,
        pilot_power_hot_w=205.0,
        power_margin_crank_w=power_margin,
        critical_drag_n=2.0,
        cd0_max=0.02,
        power_passed=power_passed,
        cl_band=cl_band,
    )


def _write_tmp_power_csv(tmp_path: Path) -> tuple[Path, Path]:
    power_csv = tmp_path / "power.csv"
    power_csv.write_text("secs,watts\n6000,213\n6600,212\n7200,211\n", encoding="utf-8")
    metadata_yaml = tmp_path / "metadata.yaml"
    metadata_yaml.write_text(
        """\
schema_version: rider_power_curve_metadata_v1
source_csv: power.csv
measurement_environment:
  temperature_c: 26.0
  relative_humidity_percent: 70.0
""",
        encoding="utf-8",
    )
    return power_csv, metadata_yaml


def _write_explorer_config(tmp_path: Path) -> Path:
    power_csv, metadata_yaml = _write_tmp_power_csv(tmp_path)
    output_dir = tmp_path / "mission_design_space"
    config_yaml = tmp_path / "explorer.yaml"
    config_yaml.write_text(
        f"""
schema_version: mission_design_space_v1
mission:
  target_range_km: 42.195
rider:
  power_csv: {power_csv}
  metadata_yaml: {metadata_yaml}
environment:
  target_temperature_c: 33.0
  target_relative_humidity_percent: 80.0
  heat_loss_coefficient_per_h_c: 0.008
aircraft:
  mass_kg: [98.5]
  air_density_kg_m3: [1.1357]
  oswald_e: [0.9]
  eta_prop: [0.86]
  eta_trans: [0.96]
design_space:
  speeds_mps:
    min: 6.0
    max: 6.0
    step: 0.1
  spans_m: [34.0]
  aspect_ratios: [38.0]
  cd0_totals: [0.018, 0.020]
  cl_max_effectives: [1.55]
filters:
  min_power_margin_crank_w: 5.0
  robust_power_margin_crank_w: 10.0
  allowed_cl_bands: ["normal"]
  allowed_stall_bands: ["healthy", "caution"]
  max_cl_to_clmax_ratio: 0.90
outputs:
  output_dir: {output_dir}
  write_full_results_csv: true
  write_envelope_csv: true
  write_markdown_report: false
  write_plots: false
plots:
  dpi: 160
  format: png
  max_candidate_rows_in_report: 10
""",
        encoding="utf-8",
    )
    return config_yaml


def _run_explorer(tmp_path: Path) -> tuple[Path, dict[str, Any], list[MissionQuickScreenResult]]:
    config_path = _write_explorer_config(tmp_path)
    spec = load_mission_design_space_spec(config_path)
    output_dir = Path(spec.output_dir)
    _full_csv, _report_md, cases = run_mission_design_space(
        spec=spec,
        output_dir_override=output_dir,
        dry_run=False,
        limit=None,
        skip_plots=True,
    )
    handoff_path = output_dir / OPTIMIZER_HANDOFF_JSON_FILENAME
    summary_path = output_dir / SUMMARY_JSON_FILENAME
    candidate_pool_path = output_dir / CANDIDATE_SEED_POOL_CSV_FILENAME
    human_summary_path = output_dir / HUMAN_READABLE_SUMMARY_JSON_FILENAME

    return output_dir, {
        "handoff_path": handoff_path,
        "summary_path": summary_path,
        "candidate_pool_path": candidate_pool_path,
        "human_summary_path": human_summary_path,
    }, cases


def test_build_candidate_seed_pool_grouping():
    filters = MissionDesignSpaceFilters(
        min_power_margin_crank_w=5.0,
        robust_power_margin_crank_w=10.0,
        allowed_cl_bands=("normal",),
        allowed_stall_bands=("healthy", "caution"),
        max_cl_to_clmax_ratio=0.90,
    )
    results = [
        _build_result(
            speed_mps=6.0,
            span_m=34.0,
            aspect_ratio=38.0,
            cd0_total=0.018,
            mass_kg=98.5,
            oswald_e=0.9,
            cl_max_effective=1.55,
            cl_to_clmax_ratio=0.82,
            power_margin=12.0,
            power_passed=True,
            cl_band="normal",
            stall_band="healthy",
        ),
        _build_result(
            speed_mps=6.0,
            span_m=34.0,
            aspect_ratio=38.0,
            cd0_total=0.018,
            mass_kg=99.0,
            oswald_e=0.91,
            cl_max_effective=1.55,
            cl_to_clmax_ratio=0.83,
            power_margin=14.0,
            power_passed=True,
            cl_band="normal",
            stall_band="healthy",
        ),
        _build_result(
            speed_mps=6.0,
            span_m=34.0,
            aspect_ratio=38.0,
            cd0_total=0.020,
            mass_kg=98.5,
            oswald_e=0.9,
            cl_max_effective=1.45,
            cl_to_clmax_ratio=0.86,
            power_margin=4.0,
            power_passed=True,
            cl_band="high_but_possible",
            stall_band="caution",
        ),
    ]

    rows = build_candidate_seed_pool(results, filters=filters)
    assert len(rows) == 2
    seed_row = next(
        row for row in rows if row["speed_mps"] == 6.0 and row["cd0_total"] == 0.018
    )
    assert seed_row["total_scenarios"] == 2
    assert seed_row["robust_scenarios"] == 2
    assert seed_row["robust_fraction"] == 1.0


def test_assign_optimizer_seed_tier_rules():
    assert (
        assign_optimizer_seed_tier(
            robust_fraction=0.6,
            power_passed_scenarios=4,
            p10_power_margin_crank_w=12.0,
            max_cl_to_clmax_ratio=0.82,
        )
        == "high_confidence"
    )
    assert (
        assign_optimizer_seed_tier(
            robust_fraction=0.30,
            power_passed_scenarios=4,
            p10_power_margin_crank_w=7.0,
            max_cl_to_clmax_ratio=0.85,
        )
        == "primary"
    )
    assert (
        assign_optimizer_seed_tier(
            robust_fraction=0.0,
            power_passed_scenarios=3,
            p10_power_margin_crank_w=3.0,
            max_cl_to_clmax_ratio=1.0,
        )
        == "boundary"
    )
    assert (
        assign_optimizer_seed_tier(
            robust_fraction=0.0,
            power_passed_scenarios=0,
            p10_power_margin_crank_w=None,
            max_cl_to_clmax_ratio=1.0,
        )
        == "reject"
    )


def test_assign_optimizer_exploration_tier_rules():
    assert (
        assign_optimizer_exploration_tier(
            robust_scenarios=2,
            power_passed_scenarios=4,
            median_power_margin_crank_w=6.0,
            max_cl_to_clmax_ratio=0.90,
        )
        == "exploration_primary"
    )
    assert (
        assign_optimizer_exploration_tier(
            robust_scenarios=1,
            power_passed_scenarios=4,
            median_power_margin_crank_w=1.0,
            max_cl_to_clmax_ratio=1.00,
        )
        == "exploration_promising"
    )
    assert (
        assign_optimizer_exploration_tier(
            robust_scenarios=0,
            power_passed_scenarios=4,
            median_power_margin_crank_w=10.0,
            max_cl_to_clmax_ratio=0.90,
        )
        == "exploration_boundary"
    )
    assert (
        assign_optimizer_exploration_tier(
            robust_scenarios=0,
            power_passed_scenarios=0,
            median_power_margin_crank_w=10.0,
            max_cl_to_clmax_ratio=0.90,
        )
        == "exploration_reject"
    )


def test_optimizer_handoff_json_schema_and_files(tmp_path: Path):
    output_dir, paths, _cases = _run_explorer(tmp_path)
    assert paths["handoff_path"].exists()
    payload = json.loads(paths["handoff_path"].read_text(encoding="utf-8"))
    assert payload["schema_version"] == "mission_optimizer_handoff_v1"
    assert "search_bounds" in payload
    assert "mission_gate" in payload
    assert payload["seed_policy"]["scenario_dimensions"] == [
        "mass_kg",
        "oswald_e",
        "cl_max_effective",
        "eta_prop",
        "eta_trans",
        "air_density_kg_m3",
    ]
    assert payload["optimizer_exploration_policy"]["description"]
    assert set(payload["optimizer_exploration_policy"]["tier_counts"].keys()) == {
        "exploration_primary",
        "exploration_promising",
        "exploration_boundary",
        "exploration_reject",
    }
    assert "output_files" in payload
    assert paths["candidate_pool_path"].exists()


def test_candidate_seed_pool_csv_structure(tmp_path: Path):
    output_dir, paths, _cases = _run_explorer(tmp_path)
    assert paths["candidate_pool_path"].exists()
    with paths["candidate_pool_path"].open("r", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        rows = list(reader)
    assert rows
    row = rows[0]
    for key in [
        "speed_mps",
        "span_m",
        "aspect_ratio",
        "cd0_total",
        "robust_fraction",
        "p10_power_margin_crank_w",
        "tier",
        "strict_tier",
        "optimizer_exploration_tier",
    ]:
        assert key in row


def test_exploration_tier_splits_boundary_strict_region():
    filters = MissionDesignSpaceFilters(
        min_power_margin_crank_w=5.0,
        robust_power_margin_crank_w=10.0,
        allowed_cl_bands=("normal",),
        allowed_stall_bands=("healthy", "caution"),
        max_cl_to_clmax_ratio=0.90,
    )
    results = [
        _build_result(
            speed_mps=6.0,
            span_m=34.0,
            aspect_ratio=38.0,
            cd0_total=0.018,
            mass_kg=98.5,
            oswald_e=0.9,
            cl_max_effective=1.55,
            cl_to_clmax_ratio=0.88,
            power_margin=6.0,
            power_passed=True,
            cl_band="normal",
            stall_band="healthy",
        ),
        _build_result(
            speed_mps=6.0,
            span_m=34.0,
            aspect_ratio=38.0,
            cd0_total=0.018,
            mass_kg=98.6,
            oswald_e=0.9,
            cl_max_effective=1.55,
            cl_to_clmax_ratio=0.92,
            power_margin=5.5,
            power_passed=True,
            cl_band="high_but_possible",
            stall_band="healthy",
        ),
        _build_result(
            speed_mps=6.0,
            span_m=34.0,
            aspect_ratio=38.0,
            cd0_total=0.018,
            mass_kg=98.7,
            oswald_e=0.9,
            cl_max_effective=1.55,
            cl_to_clmax_ratio=0.95,
            power_margin=5.2,
            power_passed=True,
            cl_band="high_but_possible",
            stall_band="caution",
        ),
        _build_result(
            speed_mps=6.0,
            span_m=34.0,
            aspect_ratio=38.0,
            cd0_total=0.018,
            mass_kg=98.8,
            oswald_e=0.9,
            cl_max_effective=1.55,
            cl_to_clmax_ratio=0.92,
            power_margin=-3.0,
            power_passed=False,
            cl_band="normal",
            stall_band="healthy",
        ),
        _build_result(
            speed_mps=6.0,
            span_m=34.0,
            aspect_ratio=38.0,
            cd0_total=0.018,
            mass_kg=99.0,
            oswald_e=0.9,
            cl_max_effective=1.55,
            cl_to_clmax_ratio=0.92,
            power_margin=-4.0,
            power_passed=False,
            cl_band="normal",
            stall_band="healthy",
        ),
        _build_result(
            speed_mps=6.0,
            span_m=34.0,
            aspect_ratio=38.0,
            cd0_total=0.020,
            mass_kg=98.5,
            oswald_e=0.9,
            cl_max_effective=1.55,
            cl_to_clmax_ratio=0.89,
            power_margin=6.0,
            power_passed=True,
            cl_band="normal",
            stall_band="healthy",
        ),
        _build_result(
            speed_mps=6.0,
            span_m=34.0,
            aspect_ratio=38.0,
            cd0_total=0.020,
            mass_kg=98.6,
            oswald_e=0.9,
            cl_max_effective=1.55,
            cl_to_clmax_ratio=0.99,
            power_margin=4.0,
            power_passed=True,
            cl_band="high_but_possible",
            stall_band="healthy",
        ),
        _build_result(
            speed_mps=6.0,
            span_m=34.0,
            aspect_ratio=38.0,
            cd0_total=0.020,
            mass_kg=98.7,
            oswald_e=0.9,
            cl_max_effective=1.55,
            cl_to_clmax_ratio=0.99,
            power_margin=1.0,
            power_passed=True,
            cl_band="high_but_possible",
            stall_band="caution",
        ),
        _build_result(
            speed_mps=6.0,
            span_m=34.0,
            aspect_ratio=38.0,
            cd0_total=0.020,
            mass_kg=98.8,
            oswald_e=0.9,
            cl_max_effective=1.55,
            cl_to_clmax_ratio=0.99,
            power_margin=-4.0,
            power_passed=False,
            cl_band="normal",
            stall_band="healthy",
        ),
        _build_result(
            speed_mps=6.0,
            span_m=34.0,
            aspect_ratio=38.0,
            cd0_total=0.020,
            mass_kg=98.9,
            oswald_e=0.9,
            cl_max_effective=1.55,
            cl_to_clmax_ratio=0.99,
            power_margin=-5.0,
            power_passed=False,
            cl_band="normal",
            stall_band="healthy",
        ),
    ]

    rows = build_candidate_seed_pool(results, filters=filters)
    primary_seed = next(
        row for row in rows if row["speed_mps"] == 6.0 and row["cd0_total"] == 0.018
    )
    promising_seed = next(
        row for row in rows if row["speed_mps"] == 6.0 and row["cd0_total"] == 0.020
    )
    assert primary_seed["strict_tier"] == "boundary"
    assert primary_seed["optimizer_exploration_tier"] == "exploration_primary"
    assert promising_seed["strict_tier"] == "boundary"
    assert promising_seed["optimizer_exploration_tier"] == "exploration_promising"


def test_optimizer_handoff_adapter_reference_case():
    payload = evaluate_optimizer_mission_gate(
        MissionGateInput(
            speed_mps=6.5,
            span_m=35.0,
            aspect_ratio=38.0,
            mass_kg=98.5,
            cd0_total=0.020,
            cl_max_effective=1.55,
            oswald_e=0.9,
            air_density_kg_m3=1.1357,
            eta_prop=0.86,
            eta_trans=0.96,
            target_range_km=42.195,
            rider_curve=FakeAnchorCurve(
                anchor_power_w=213.0,
                anchor_duration_min=108.1923076923077,
                exponent=1.0,
            ),
            thermal_derate_factor=0.9159364331845841,
        )
    )
    assert set(payload.keys()) >= {
        "power_passed",
        "robust_passed",
        "power_margin_crank_w",
        "cl_required",
        "cl_to_clmax_ratio",
        "stall_band",
        "cl_band",
        "required_time_min",
        "penalty",
    }
    assert (payload["power_passed"] is False) or (payload["penalty"] > 0)


def test_human_readable_summary_json_output(tmp_path: Path):
    output_dir, paths, _cases = _run_explorer(tmp_path)
    payload = json.loads(paths["human_summary_path"].read_text(encoding="utf-8"))
    assert "headline" in payload
    assert "risk_summary" in payload
    assert "important_paths" in payload
    assert payload["important_paths"]["candidate_seed_pool_csv"] == str(
        paths["candidate_pool_path"],
    )
    assert payload["important_paths"]["optimizer_handoff_json"] == str(
        paths["handoff_path"],
    )


def test_summary_json_contains_optimizer_handoff_block(tmp_path: Path):
    output_dir, paths, _cases = _run_explorer(tmp_path)
    payload = json.loads(paths["summary_path"].read_text(encoding="utf-8"))
    assert "optimizer_handoff" in payload
    assert payload["optimizer_handoff"]["candidate_seed_pool_csv"] == CANDIDATE_SEED_POOL_CSV_FILENAME
    assert payload["optimizer_handoff"]["optimizer_handoff_json"] == OPTIMIZER_HANDOFF_JSON_FILENAME
    counts = payload["optimizer_handoff"]["seed_tier_counts"]
    assert set(counts.keys()) == {
        "high_confidence",
        "primary",
        "boundary",
        "reject",
    }
    explorer_counts = payload["optimizer_handoff"]["optimizer_exploration_tier_counts"]
    assert set(explorer_counts.keys()) == {
        "exploration_primary",
        "exploration_promising",
        "exploration_boundary",
        "exploration_reject",
    }
