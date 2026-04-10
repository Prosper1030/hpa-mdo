from __future__ import annotations

import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts.compare_structural_runs import (  # noqa: E402
    compare_runs,
    load_run,
    main,
    parse_run_spec,
)


def test_compare_runs_from_text_sources(tmp_path: Path) -> None:
    baseline_txt = tmp_path / "optimization_summary.txt"
    baseline_txt.write_text(
        "\n".join(
            [
                "HPA-MDO Spar Optimization Summary",
                "  Spar mass (full): 9.4540 kg",
                "  Tip deflection  : 2500.00 mm",
                "  Max twist       : 0.213 deg",
                "  Failure index   : -0.46588",
                "  Buckling index  : -0.80105",
                "  OPTIMIZATION TIMING [s]",
                "  Total            : 71.000000",
            ]
        ),
        encoding="utf-8",
    )

    dual_txt = tmp_path / "dual_beam_internal_report.txt"
    dual_txt.write_text(
        "\n".join(
            [
                "Internal Dual-Beam Analysis Report",
                "Internal dual-beam outputs:",
                "  Tip deflection main (mm)         : 2837.618",
                "  Tip deflection rear (mm)         : 3373.731",
                "  Max |UZ| anywhere (mm)           : 3373.731",
                "  Spar mass full-span              : 9.763 kg",
                "  Failure index (non-gating here)  : -0.4314",
            ]
        ),
        encoding="utf-8",
    )

    baseline = load_run(parse_run_spec(f"baseline={baseline_txt}"))
    dual = load_run(parse_run_spec(f"dual_refined={dual_txt}"))
    summary = compare_runs([baseline, dual], baseline_label="baseline")

    runs = {item["label"]: item for item in summary["runs"]}

    assert runs["baseline"]["metrics"]["mass_kg"] == 9.454
    assert runs["baseline"]["metrics"]["runtime_s"] == 71.0

    assert runs["dual_refined"]["metrics"]["rear_tip_displacement_mm"] == 3373.731
    assert runs["dual_refined"]["metrics"]["rear_main_tip_ratio"] == 3373.731 / 2837.618
    assert runs["dual_refined"]["delta_pct_vs_baseline"]["mass_kg"] > 3.0
    assert runs["dual_refined"]["classification"] == "heavier and riskier"


def test_load_guardrail_json_with_selector(tmp_path: Path) -> None:
    payload = {
        "baseline_unguarded": {
            "equivalent_beam": {
                "mass_kg": 9.45,
                "tip_deflection_mm": 2500.0,
                "failure_index": -0.46,
                "buckling_index": -0.80,
                "twist_max_deg": 0.21,
                "wall_time_s": 78.8,
            },
            "dual_beam": {
                "mass_kg": 9.46,
                "tip_main_mm": 2837.6,
                "tip_rear_mm": 3373.7,
                "max_uz_any_mm": 3373.7,
                "failure_index": -0.44,
            },
        }
    }
    json_path = tmp_path / "guardrail_summary.json"
    json_path.write_text(json.dumps(payload), encoding="utf-8")

    eq = load_run(parse_run_spec(f"eq={json_path}::baseline_unguarded.equivalent_beam"))
    dual = load_run(parse_run_spec(f"dual={json_path}::baseline_unguarded.dual_beam"))

    assert eq.metrics["mass_kg"] == 9.45
    assert eq.metrics["runtime_s"] == 78.8
    assert dual.metrics["tip_deflection_mm"] == 2837.6
    assert dual.metrics["rear_tip_displacement_mm"] == 3373.7
    assert dual.metrics["rear_main_tip_ratio"] == 3373.7 / 2837.6


def test_internal_dual_beam_ansys_profile_and_main_json_output(tmp_path: Path) -> None:
    dual_with_ansys_txt = tmp_path / "dual_beam_internal_report.txt"
    dual_with_ansys_txt.write_text(
        "\n".join(
            [
                "Internal Dual-Beam Analysis Report",
                "Compared against ANSYS results in: /tmp/ansys",
                "",
                "Metric                                         Internal        ANSYS    Error %",
                "----------------------------------------------------------------------------------------",
                "Tip deflection main (mm)                       2837.618     2853.556       0.56",
                "Max |UZ| anywhere (mm)                         3373.731     3390.902       0.51",
                "Spar mass full-span (kg)                          9.455        9.472       0.18",
            ]
        ),
        encoding="utf-8",
    )

    baseline_txt = tmp_path / "baseline_optimization_summary.txt"
    baseline_txt.write_text(
        "\n".join(
            [
                "HPA-MDO Spar Optimization Summary",
                "  Spar mass (full): 9.4540 kg",
                "  Tip deflection  : 2500.00 mm",
                "  Failure index   : -0.46588",
                "  Buckling index  : -0.80105",
            ]
        ),
        encoding="utf-8",
    )

    json_out = tmp_path / "structural_compare_summary.json"
    md_out = tmp_path / "structural_compare_summary.md"

    rc = main(
        [
            "--run",
            f"baseline={baseline_txt}",
            "--run",
            f"ansys_spot={dual_with_ansys_txt}::ansys",
            "--baseline",
            "baseline",
            "--json-out",
            str(json_out),
            "--md-out",
            str(md_out),
        ]
    )

    assert rc == 0
    assert json_out.exists()
    assert md_out.exists()

    summary = json.loads(json_out.read_text(encoding="utf-8"))
    runs = {item["label"]: item for item in summary["runs"]}

    assert runs["ansys_spot"]["metrics"]["tip_deflection_mm"] == 2853.556
    assert runs["ansys_spot"]["metrics"]["mass_kg"] == 9.472
