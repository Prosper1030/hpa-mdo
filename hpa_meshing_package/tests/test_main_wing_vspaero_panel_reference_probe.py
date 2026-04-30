import json
from pathlib import Path

import pytest

from hpa_meshing.main_wing_vspaero_panel_reference_probe import (
    build_main_wing_vspaero_panel_reference_probe_report,
    write_main_wing_vspaero_panel_reference_probe_report,
)


def _write_panel_artifacts(tmp_path: Path, *, cl: float = 1.287645495943) -> tuple[Path, Path]:
    polar = tmp_path / "black_cat_004.polar"
    polar.write_text(
        "\n".join(
            [
                "Beta Mach AoA Re/1e6 CLo CLi CLtot CDo CDi CDtot CSo CSi CStot L/D E CMox CMoy CMoz",
                f"0.0 0.0 0.0 0.4641 -0.0027 1.2903 {cl:.12f} 0.024 0.021 0.045 0.0 0.0 0.0 28.57 0.81 0.0 0.0 0.0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    setup = tmp_path / "black_cat_004.vspaero"
    setup.write_text(
        "\n".join(
            [
                "Sref = 35.175000",
                "Cref = 1.042500",
                "Bref = 33.000000",
                "AoA = 0.000000",
                "Vinf = 6.500000",
                "Rho = 1.225000",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return polar, setup


def _write_lift_diagnostic(tmp_path: Path, *, cl: float = 0.263161913) -> Path:
    path = tmp_path / "main_wing_lift_acceptance_diagnostic.v1.json"
    path.write_text(
        json.dumps(
            {
                "lift_metrics": {"cl": cl},
                "selected_solver_report": {
                    "runtime_max_iterations": 80,
                    "report_path": "main_wing_real_solver_smoke_probe.v1.json",
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def test_vspaero_panel_reference_probe_records_panel_cl_gt_one_and_su2_gap(
    tmp_path: Path,
):
    polar, setup = _write_panel_artifacts(tmp_path)
    lift_diagnostic = _write_lift_diagnostic(tmp_path)

    report = build_main_wing_vspaero_panel_reference_probe_report(
        polar_path=polar,
        setup_path=setup,
        lift_diagnostic_path=lift_diagnostic,
    )

    assert report.panel_reference_status == "panel_reference_available"
    assert report.hpa_standard_flow_status == "hpa_standard_6p5_observed"
    assert report.lift_acceptance_status == "pass"
    assert report.selected_case["CLtot"] == pytest.approx(1.287645495943)
    assert report.setup_reference["Vinf"] == pytest.approx(6.5)
    assert report.su2_smoke_comparison["status"] == "available"
    assert report.su2_smoke_comparison["panel_reference_cl"] == pytest.approx(
        1.287645495943
    )
    assert report.su2_smoke_comparison["selected_su2_smoke_cl"] == pytest.approx(
        0.263161913
    )
    assert "vspaero_panel_reference_cl_gt_one" in report.engineering_flags
    assert "su2_smoke_below_vspaero_panel_reference" in report.engineering_flags


def test_vspaero_panel_reference_probe_reports_nonstandard_flow(tmp_path: Path):
    polar, setup = _write_panel_artifacts(tmp_path)
    setup.write_text("Vinf = 10.000000\n", encoding="utf-8")

    report = build_main_wing_vspaero_panel_reference_probe_report(
        polar_path=polar,
        setup_path=setup,
        lift_diagnostic_path=_write_lift_diagnostic(tmp_path),
    )

    assert report.panel_reference_status == "panel_reference_nonstandard_flow"
    assert report.hpa_standard_flow_status == "legacy_or_nonstandard_velocity_observed"
    assert report.lift_acceptance_status == "not_evaluated"
    assert "vspaero_panel_reference_nonstandard_flow" in report.engineering_flags


def test_write_vspaero_panel_reference_probe_report(tmp_path: Path):
    polar, setup = _write_panel_artifacts(tmp_path)
    out_dir = tmp_path / "report"

    written = write_main_wing_vspaero_panel_reference_probe_report(
        out_dir,
        polar_path=polar,
        setup_path=setup,
        lift_diagnostic_path=_write_lift_diagnostic(tmp_path),
    )

    payload = json.loads(written["json"].read_text(encoding="utf-8"))
    markdown = written["markdown"].read_text(encoding="utf-8")
    assert payload["schema_version"] == "main_wing_vspaero_panel_reference_probe.v1"
    assert payload["lift_acceptance_status"] == "pass"
    assert "VSPAERO Panel Reference Probe" in markdown
