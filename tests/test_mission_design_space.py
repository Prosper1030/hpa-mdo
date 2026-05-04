from pathlib import Path
import json
import subprocess
import sys

import pytest

from hpa_mdo.mission.design_space import (
    MissionDesignSpaceFilters,
    build_boundary_tables,
    build_feasible_envelope,
    build_speed_values,
    load_mission_design_space_spec,
    write_design_space_report,
    summarize_design_space,
)
from hpa_mdo.mission.objective import RiderPowerEnvironment
from hpa_mdo.mission.quick_screen import MissionQuickScreenResult


def _format_markdown_table_rows(
    text: str,
    section_title: str,
) -> tuple[list[str], list[dict[str, str]]]:
    lines = text.splitlines()
    start = None
    for idx, line in enumerate(lines):
        if line.strip() == f"### {section_title}":
            start = idx + 1
            break
    if start is None:
        raise AssertionError(f"section not found: {section_title}")
    idx = start
    while idx < len(lines) and lines[idx].strip() == "":
        idx += 1
    if idx >= len(lines) or lines[idx].strip() == "No cases.":
        return [], []
    if not lines[idx].startswith("| "):
        return [], []
    header = [col.strip() for col in lines[idx].strip().strip("|").split("|")]
    idx += 1
    if idx >= len(lines) or not lines[idx].startswith("|---"):
        return header, []
    idx += 1
    rows: list[dict[str, str]] = []
    while idx < len(lines):
        line = lines[idx].strip()
        if not line.startswith("|"):
            break
        cells = [col.strip() for col in line.strip().strip("|").split("|")]
        if len(cells) == len(header):
            rows.append(dict(zip(header, cells)))
        idx += 1
    return header, rows


def _build_report_for_cases(
    tmp_path: Path,
    results: list[MissionQuickScreenResult],
    filters: MissionDesignSpaceFilters,
) -> str:
    yaml_path = tmp_path / "mission_space_report.yaml"
    _write_tmp_yaml(
        yaml_path,
        f"""
schema_version: mission_design_space_v1
mission:
  target_range_km: 42.195
rider:
  power_csv: temp_power.csv
  metadata_yaml: temp_metadata.yaml
environment:
  target_temperature_c: 33.0
  target_relative_humidity_percent: 80.0
  heat_loss_coefficient_per_h_c: 0.008
aircraft:
  mass_kg: [98.5, 99.0]
  air_density_kg_m3: [1.1357]
  oswald_e: [0.9, 0.91]
  eta_prop: [0.86]
  eta_trans: [0.96]
design_space:
  speeds_mps:
    min: 6.0
    max: 6.4
    step: 0.2
  spans_m: [34.0]
  aspect_ratios: [38.0]
  cd0_totals: [0.017, 0.018]
  cl_max_effectives: [1.45, 1.55]
filters:
  min_power_margin_crank_w: 5.0
  robust_power_margin_crank_w: 10.0
  allowed_cl_bands: ["normal"]
  allowed_stall_bands: ["healthy", "caution"]
  max_cl_to_clmax_ratio: 0.90
outputs:
  output_dir: {tmp_path}/mission_design_space
""",
    )
    spec = load_mission_design_space_spec(yaml_path)
    report_path = tmp_path / "report.md"
    write_design_space_report(
        report_path,
        spec=spec,
        results=results,
        summary=summarize_design_space(results, filters),
        envelopes=build_feasible_envelope(results, filters),
        boundary_tables=build_boundary_tables(results, filters),
        test_env=RiderPowerEnvironment(26.0, 70.0),
        target_env=RiderPowerEnvironment(33.0, 80.0),
        heat_derate=0.9,
        filters=filters,
    )
    return report_path.read_text(encoding="utf-8")


def _build_result(
    *,
    speed_mps: float,
    cd0_total: float,
    power_margin: float | None,
    cl_band: str,
    stall_band: str,
    cl_to_clmax_ratio: float = 0.85,
    cl_max_effective: float = 1.55,
    span_m: float = 34.0,
    aspect_ratio: float = 38.0,
    mass_kg: float = 98.5,
    oswald_e: float = 0.9,
    power_passed: bool | None = None,
) -> MissionQuickScreenResult:
    resolved_power_passed = (
        power_margin is not None and power_margin >= 0.0
        if power_passed is None
        else power_passed
    )
    return MissionQuickScreenResult(
        speed_mps=speed_mps,
        span_m=span_m,
        aspect_ratio=aspect_ratio,
        mass_kg=mass_kg,
        oswald_e=oswald_e,
        air_density_kg_m3=1.1357,
        eta_prop=0.86,
        eta_trans=0.96,
        wing_area_m2=10.0,
        cd0_total=cd0_total,
        required_time_min=100.0,
        cl_required=1.2,
        cd_induced=0.01,
        induced_power_air_w=50.0,
        parasite_power_air_w=120.0,
        total_power_air_w=170.0,
        required_crank_power_w=180.0,
        cl_max_effective=cl_max_effective,
        cl_to_clmax_ratio=cl_to_clmax_ratio,
        cl_margin_to_clmax=0.35,
        stall_speed_mps=5.8,
        stall_margin_speed_ratio=1.1,
        stall_band=stall_band,
        pilot_power_test_w=200.0 if power_margin is not None else None,
        pilot_power_hot_w=210.0 if power_margin is not None else None,
        power_margin_crank_w=power_margin,
        critical_drag_n=2.0 if power_margin is not None else None,
        cd0_max=0.02 if power_margin is not None else None,
        power_passed=resolved_power_passed,
        cl_band=cl_band,
    )


def _write_tmp_yaml(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def test_design_space_speed_range_expansion():
    assert build_speed_values(6.0, 6.2, 0.1) == (6.0, 6.1, 6.2)


def test_load_mission_design_space_spec_parsing(tmp_path: Path) -> None:
    yaml_path = tmp_path / "mission_design_space.yaml"
    _write_tmp_yaml(
        yaml_path,
        """
schema_version: mission_design_space_v1
mission:
  target_range_km: 42.195
rider:
  power_csv: data/pilot_power_curves/current_pilot_power_curve.csv
  metadata_yaml: data/pilot_power_curves/current_pilot_power_curve.metadata.yaml
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
    max: 6.2
    step: 0.1
  spans_m: [34.0,35.0]
  aspect_ratios: [38.0]
  cd0_totals: [0.017,0.020]
  cl_max_effectives: [1.55]
filters:
  min_power_margin_crank_w: 5.0
  robust_power_margin_crank_w: 10.0
outputs:
  output_dir: output/mission_design_space
""",
    )
    spec = load_mission_design_space_spec(yaml_path)

    assert spec.speeds_mps == (6.0, 6.1, 6.2)
    assert spec.spans_m == (34.0, 35.0)
    assert spec.filters.max_cl_to_clmax_ratio == 0.90


def test_summarize_design_space_counts():
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
            cd0_total=0.017,
            power_margin=12.0,
            cl_band="normal",
            stall_band="healthy",
            cl_to_clmax_ratio=0.80,
        ),
        _build_result(
            speed_mps=6.0,
            cd0_total=0.018,
            power_margin=7.0,
            cl_band="normal",
            stall_band="caution",
            cl_to_clmax_ratio=0.85,
        ),
        _build_result(
            speed_mps=6.2,
            cd0_total=0.018,
            power_margin=None,
            cl_band="high_but_possible",
            stall_band="healthy",
            cl_to_clmax_ratio=0.95,
        ),
        _build_result(
            speed_mps=6.4,
            cd0_total=0.018,
            power_margin=-1.0,
            cl_band="normal",
            stall_band="healthy",
            cl_to_clmax_ratio=0.80,
        ),
    ]

    summary = summarize_design_space(results, filters)
    assert summary["total_cases"] == 4
    assert summary["power_passed_cases"] == 2
    assert summary["robust_cases"] == 2
    assert summary["normal_cl_cases"] == 3
    assert summary["healthy_or_caution_stall_cases"] == 4
    assert summary["margin_ge_min_cases"] == 2
    assert summary["margin_ge_robust_cases"] == 1


def test_build_feasible_envelope_rows_for_speed_and_cd0():
    results = [
        _build_result(
            speed_mps=6.0,
            cd0_total=0.017,
            power_margin=8.0,
            cl_band="normal",
            stall_band="healthy",
            cl_to_clmax_ratio=0.82,
        ),
        _build_result(
            speed_mps=6.0,
            cd0_total=0.020,
            power_margin=11.0,
            cl_band="normal",
            stall_band="healthy",
            cl_to_clmax_ratio=0.83,
        ),
        _build_result(
            speed_mps=6.2,
            cd0_total=0.017,
            power_margin=13.0,
            cl_band="normal",
            stall_band="caution",
            cl_to_clmax_ratio=0.86,
        ),
        _build_result(
            speed_mps=6.2,
            cd0_total=0.020,
            power_margin=-2.0,
            cl_band="normal",
            stall_band="thin_margin",
            cl_to_clmax_ratio=0.97,
        ),
    ]
    filters = MissionDesignSpaceFilters(
        min_power_margin_crank_w=5.0,
        robust_power_margin_crank_w=10.0,
        allowed_cl_bands=("normal",),
        allowed_stall_bands=("healthy", "caution"),
        max_cl_to_clmax_ratio=0.90,
    )

    envelope_rows = build_feasible_envelope(results, filters)
    by_speed = [row for row in envelope_rows if row["group"] == "by_speed"]
    by_cd0 = [row for row in envelope_rows if row["group"] == "by_cd0"]
    assert len(by_speed) == 2
    assert len(by_cd0) == 2
    row_by_speed_6_0 = next(row for row in by_speed if row["speed_mps"] == 6.0)
    assert row_by_speed_6_0["total_cases"] == 2
    assert row_by_speed_6_0["robust_cases"] == 2
    row_by_cd0_0020 = next(row for row in by_cd0 if row["cd0_total"] == 0.020)
    assert row_by_cd0_0020["total_cases"] == 2


def test_candidate_table_filters_and_columns(tmp_path: Path) -> None:
    filters = MissionDesignSpaceFilters(
        min_power_margin_crank_w=5.0,
        robust_power_margin_crank_w=10.0,
        allowed_cl_bands=("normal",),
        allowed_stall_bands=("healthy", "caution"),
        max_cl_to_clmax_ratio=0.90,
    )
    results = [
        _build_result(
            speed_mps=6.2,
            cd0_total=0.017,
            power_margin=12.0,
            cl_band="normal",
            stall_band="healthy",
            cl_max_effective=1.45,
            mass_kg=98.5,
            oswald_e=0.90,
        ),
        _build_result(
            speed_mps=6.6,
            cd0_total=0.017,
            power_margin=11.0,
            cl_band="normal",
            stall_band="healthy",
            cl_max_effective=1.45,
            mass_kg=99.0,
            oswald_e=0.91,
        ),
        _build_result(
            speed_mps=6.6,
            cd0_total=0.018,
            power_margin=-1.0,
            cl_band="normal",
            stall_band="healthy",
            cl_max_effective=1.55,
            power_passed=False,
        ),
        _build_result(
            speed_mps=6.6,
            cd0_total=0.018,
            power_margin=7.0,
            cl_band="high_but_possible",
            stall_band="healthy",
            cl_max_effective=1.45,
        ),
        _build_result(
            speed_mps=6.8,
            cd0_total=0.020,
            power_margin=6.0,
            cl_band="normal",
            stall_band="thin_margin",
            cl_max_effective=1.55,
        ),
        _build_result(
            speed_mps=6.6,
            cd0_total=0.018,
            power_margin=4.0,
            cl_band="normal",
            stall_band="caution",
            cl_max_effective=1.55,
        ),
    ]
    report_text = _build_report_for_cases(tmp_path, results, filters)

    headers, conservative_rows = _format_markdown_table_rows(
        report_text,
        "Conservative CLmax robust candidates",
    )
    for row in conservative_rows:
        assert row["robust_passed"] == "True"
        assert row["cl_band"] == "normal"
        assert row["stall_band"] in {"healthy", "caution"}

    _, high_speed_rows = _format_markdown_table_rows(
        report_text,
        "High-speed robust candidates",
    )
    assert all(
        row["power_passed"] == "True" and row["robust_passed"] == "True"
        for row in high_speed_rows
    )

    robust_headers, robust_rows = _format_markdown_table_rows(
        report_text,
        "Robust candidates sorted by speed",
    )
    assert "mass_kg" in robust_headers
    assert "oswald_e" in robust_headers
    assert "eta_prop" in robust_headers
    assert "eta_trans" in robust_headers
    assert all(row["robust_passed"] == "True" for row in robust_rows)

    _, boundary_rows = _format_markdown_table_rows(
        report_text,
        "Boundary / risky cases, not recommended as primary design",
    )
    assert boundary_rows
    assert any(
        "### Boundary / risky cases, not recommended as primary design" in line
        for line in report_text.splitlines()
    )


def test_build_boundary_tables_and_cli_smoke(tmp_path: Path) -> None:
    power_csv = tmp_path / "power_curve.csv"
    power_csv.write_text("secs,watts\n6000,213\n6600,212\n7200,211\n", encoding="utf-8")
    metadata_yaml = tmp_path / "metadata.yaml"
    metadata_yaml.write_text(
        """\
schema_version: rider_power_curve_metadata_v1
source_csv: power_curve.csv
measurement_environment:
  temperature_c: 26.0
  relative_humidity_percent: 70.0
""",
        encoding="utf-8",
    )
    config_yaml = tmp_path / "design_space.yaml"
    _write_tmp_yaml(
        config_yaml,
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
    max: 6.3
    step: 0.2
  spans_m: [34.0]
  aspect_ratios: [38.0]
  cd0_totals: [0.017,0.020]
  cl_max_effectives: [1.45,1.55]
filters:
  min_power_margin_crank_w: 5.0
  robust_power_margin_crank_w: 10.0
  allowed_cl_bands: ["normal"]
  allowed_stall_bands: ["healthy", "caution"]
  max_cl_to_clmax_ratio: 0.90
outputs:
  output_dir: {tmp_path / "mission_design_space_smoke"}
""",
    )
    output_dir = tmp_path / "mission_design_space_smoke"
    repo_root = Path(__file__).resolve().parents[1]

    subprocess.run(
        [
            sys.executable,
            "scripts/mission_design_space_explorer.py",
            "--config",
            str(config_yaml),
            "--output-dir",
            str(output_dir),
        ],
        check=True,
        cwd=repo_root,
    )

    assert (output_dir / "full_results.csv").exists()
    assert (output_dir / "report.md").exists()
    assert (output_dir / "boundary_speed_cd0.csv").exists()
    assert (output_dir / "envelope_by_speed.csv").exists()
    assert (output_dir / "summary.json").exists()
    summary_payload = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    assert "robust_speed_envelope" in summary_payload
    assert summary_payload["output_files"]["report_md"] == "report.md"


def test_plot_generation_smoke_test_and_report_summary(tmp_path: Path) -> None:
    power_csv = tmp_path / "power_curve.csv"
    power_csv.write_text("secs,watts\n6000,213\n6600,212\n7200,211\n", encoding="utf-8")
    metadata_yaml = tmp_path / "metadata.yaml"
    metadata_yaml.write_text(
        """\
schema_version: rider_power_curve_metadata_v1
source_csv: power_curve.csv
measurement_environment:
  temperature_c: 26.0
  relative_humidity_percent: 70.0
""",
        encoding="utf-8",
    )
    output_dir = tmp_path / "mission_design_space_plot_smoke"
    output_dir.mkdir()
    summary_json = output_dir / "summary.json"
    summary_json.write_text(json.dumps({"existing": True}) + "\n", encoding="utf-8")
    config_yaml = tmp_path / "design_space_plot.yaml"
    _write_tmp_yaml(
        config_yaml,
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
    max: 6.4
    step: 0.1
  spans_m: [34.0]
  aspect_ratios: [38.0]
  cd0_totals: [0.017, 0.018]
  cl_max_effectives: [1.45, 1.55]
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
  write_markdown_report: true
  write_plots: true
plots:
  dpi: 160
  format: png
  max_candidate_rows_in_report: 10
""",
    )

    repo_root = Path(__file__).resolve().parents[1]
    subprocess.run(
        [
            sys.executable,
            "scripts/mission_design_space_explorer.py",
            "--config",
            str(config_yaml),
        ],
        check=True,
        cwd=repo_root,
    )

    assert (output_dir / "plots").exists()
    expected_pngs = [
        "robust_cases_by_speed.png",
        "max_margin_by_speed.png",
        "feasible_speed_range_by_cd0.png",
        "feasible_speed_range_by_ar.png",
        "feasible_speed_range_by_span.png",
        "robust_cases_by_clmax.png",
        "robust_count_heatmap_speed_cd0.png",
        "raw_best_margin_heatmap_speed_cd0.png",
        "stall_risk_by_speed_clmax.png",
        "robust_candidates_speed_cd0_scatter.png",
    ]
    for filename in expected_pngs:
        assert (output_dir / "plots" / filename).exists()

    report_text = (output_dir / "report.md").read_text(encoding="utf-8")
    assert "## Visual Summary" in report_text
    assert "plots/robust_cases_by_speed.png" in report_text
    assert "plots/feasible_speed_range_by_cd0.png" in report_text
    inputs_block = report_text.split("## Inputs", 1)[1].split("## Case Counts", 1)[0]
    summary_lines = [
        line for line in inputs_block.splitlines() if line.strip().startswith("- summary.json:")
    ]
    assert len(summary_lines) == 1
    assert "### raw best power margin by speed/CD0" in report_text
    assert (
        "This table is power-only and may include stall-risky cases. "
        "Use robust count by speed/CD0 for design-space feasibility."
        in report_text
    )

    summary_payload = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    assert "counts" in summary_payload
    assert "observed_robust_envelope" in summary_payload
    assert "suggested_main_design_region" in summary_payload
    assert "robust_speed_envelope" in summary_payload
    assert "plot_paths" in summary_payload
    assert isinstance(summary_payload["plot_paths"], dict)
    assert set(summary_payload["plot_paths"].keys()) >= {
        "robust_cases_by_speed",
        "feasible_speed_range_by_cd0",
        "robust_count_heatmap_speed_cd0",
    }

    docs_text = Path(__file__).resolve().parents[1].joinpath("docs/mission_design_space_explorer.md").read_text(encoding="utf-8")
    assert "not the unique best solution" in docs_text
    assert "observed_robust_envelope" in docs_text


def test_skip_plots_still_generates_summary_json(tmp_path: Path) -> None:
    power_csv = tmp_path / "power_curve.csv"
    power_csv.write_text("secs,watts\n6000,213\n6600,212\n7200,211\n", encoding="utf-8")
    metadata_yaml = tmp_path / "metadata.yaml"
    metadata_yaml.write_text(
        """\
schema_version: rider_power_curve_metadata_v1
source_csv: power_curve.csv
measurement_environment:
  temperature_c: 26.0
  relative_humidity_percent: 70.0
""",
        encoding="utf-8",
    )
    output_dir = tmp_path / "mission_design_space_skip_plots"
    config_yaml = tmp_path / "design_space_plot.yaml"
    _write_tmp_yaml(
        config_yaml,
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
    max: 6.4
    step: 0.1
  spans_m: [34.0]
  aspect_ratios: [38.0]
  cd0_totals: [0.017, 0.018]
  cl_max_effectives: [1.45, 1.55]
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
  write_markdown_report: true
  write_plots: true
plots:
  dpi: 160
  format: png
  max_candidate_rows_in_report: 10
""",
    )

    repo_root = Path(__file__).resolve().parents[1]
    subprocess.run(
        [
            sys.executable,
            "scripts/mission_design_space_explorer.py",
            "--config",
            str(config_yaml),
            "--skip-plots",
        ],
        check=True,
        cwd=repo_root,
    )

    assert (output_dir / "summary.json").exists()
    summary_payload = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary_payload["plot_paths"] == {}
