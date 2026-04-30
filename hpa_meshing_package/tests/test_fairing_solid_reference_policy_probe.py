import json
from pathlib import Path

from hpa_meshing.fairing_solid_reference_policy_probe import (
    build_fairing_solid_reference_policy_probe_report,
    write_fairing_solid_reference_policy_probe_report,
)


def _write_external_project(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "HPA-Fairing-Optimization-Project"
    config = root / "config" / "fluid_conditions.json"
    config.parent.mkdir(parents=True)
    config.write_text(
        json.dumps(
            {
                "flow_conditions": {
                    "velocity": {"value": 6.5},
                    "density": {"value": 1.225},
                    "viscosity": {"value": 1.7894e-5},
                    "temperature": {"value": 15.0},
                },
                "reference_values": {"Sref": {"value": 1.0}},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    cfg = root / "output" / "best_gene" / "su2_case.cfg"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(
        "\n".join(
            [
                "REF_AREA= 1.0",
                "REF_LENGTH= 2.82880659",
                "REF_VELOCITY= 6.50000000",
                "REF_VISCOSITY= 1.7894000000e-05",
                "INC_DENSITY_INIT= 1.22500000",
                "INC_VELOCITY_INIT= ( 6.50000000, 0.0, 0.0 )",
                "MU_CONSTANT= 1.7894000000e-05",
                "MARKER_MONITORING = ( fairing )",
                "MARKER_FAR= ( farfield )",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return root, cfg


def _write_hpa_probe(tmp_path: Path) -> Path:
    runtime_cfg = tmp_path / "hpa" / "su2_runtime.cfg"
    runtime_cfg.parent.mkdir()
    runtime_cfg.write_text(
        "\n".join(
            [
                "REF_AREA= 100.000000",
                "REF_LENGTH= 1.000000",
                "INC_VELOCITY_INIT= ( 10.000000, 0.000000, 0.000000 )",
                "MU_CONSTANT= 1.789000e-05",
                "INC_DENSITY_INIT= 1.225000",
                "MARKER_MONITORING= ( fairing_solid )",
                "MARKER_FAR= ( farfield )",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    probe = tmp_path / "fairing_solid_real_su2_handoff_probe.v1.json"
    probe.write_text(
        json.dumps(
            {
                "schema_version": "fairing_solid_real_su2_handoff_probe.v1",
                "materialization_status": "su2_handoff_written",
                "reference_geometry_status": "warn",
                "runtime_cfg_path": str(runtime_cfg),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return probe


def test_fairing_solid_reference_policy_probe_reports_external_candidate_and_mismatch(
    tmp_path: Path,
):
    external_root, external_cfg = _write_external_project(tmp_path)
    hpa_probe = _write_hpa_probe(tmp_path)

    report = build_fairing_solid_reference_policy_probe_report(
        tmp_path / "report",
        external_project_root=external_root,
        external_su2_cfg_path=external_cfg,
        hpa_su2_probe_report_path=hpa_probe,
    )

    assert report.schema_version == "fairing_solid_reference_policy_probe.v1"
    assert report.reference_policy_status == "reference_mismatch_observed"
    assert report.external_reference_status == "candidate_available"
    assert report.hpa_current_reference_status == "warn"
    assert report.external_reference.ref_area == 1.0
    assert report.external_reference.ref_length == 2.82880659
    assert report.external_reference.velocity_mps == 6.5
    assert report.external_reference.wall_marker == "fairing"
    assert report.hpa_current_reference.ref_area == 100.0
    assert report.hpa_current_reference.wall_marker == "fairing_solid"
    assert set(report.reference_mismatch_fields) >= {"ref_area", "ref_length", "velocity_mps"}
    assert report.marker_mapping_status == "compatible_mapping_required"
    assert "external_fairing_reference_policy_candidate_available" in report.hpa_mdo_guarantees
    assert "hpa_current_reference_policy_mismatch" in report.blocking_reasons


def test_fairing_solid_reference_policy_probe_records_missing_external_project(
    tmp_path: Path,
):
    report = build_fairing_solid_reference_policy_probe_report(
        tmp_path / "report",
        external_project_root=tmp_path / "missing",
        hpa_su2_probe_report_path=None,
    )

    assert report.reference_policy_status == "missing"
    assert report.external_reference_status == "missing"
    assert "external_fairing_project_missing" in report.blocking_reasons


def test_fairing_solid_reference_policy_probe_resolves_hpa_report_relative_runtime_cfg(
    tmp_path: Path,
    monkeypatch,
):
    external_root, external_cfg = _write_external_project(tmp_path)
    package_root = tmp_path / "hpa_meshing_package"
    report_dir = package_root / "docs" / "reports" / "fairing_probe"
    runtime_cfg = report_dir / "artifacts" / "su2_runtime.cfg"
    runtime_cfg.parent.mkdir(parents=True)
    runtime_cfg.write_text(
        "\n".join(
            [
                "REF_AREA= 100.000000",
                "REF_LENGTH= 1.000000",
                "INC_VELOCITY_INIT= ( 10.000000, 0.000000, 0.000000 )",
                "MU_CONSTANT= 1.789000e-05",
                "INC_DENSITY_INIT= 1.225000",
                "MARKER_MONITORING= ( fairing_solid )",
                "MARKER_FAR= ( farfield )",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    probe = report_dir / "fairing_solid_real_su2_handoff_probe.v1.json"
    probe.write_text(
        json.dumps(
            {
                "reference_geometry_status": "warn",
                "runtime_cfg_path": "hpa_meshing_package/docs/reports/fairing_probe/artifacts/su2_runtime.cfg",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(package_root)

    report = build_fairing_solid_reference_policy_probe_report(
        tmp_path / "report",
        external_project_root=external_root,
        external_su2_cfg_path=external_cfg,
        hpa_su2_probe_report_path=probe,
    )

    assert report.reference_policy_status == "reference_mismatch_observed"
    assert report.hpa_current_reference.ref_area == 100.0
    assert report.marker_mapping_status == "compatible_mapping_required"


def test_fairing_solid_reference_policy_probe_writer_outputs_json_and_markdown(
    tmp_path: Path,
):
    external_root, external_cfg = _write_external_project(tmp_path)
    hpa_probe = _write_hpa_probe(tmp_path)

    paths = write_fairing_solid_reference_policy_probe_report(
        tmp_path / "report",
        external_project_root=external_root,
        external_su2_cfg_path=external_cfg,
        hpa_su2_probe_report_path=hpa_probe,
    )

    assert set(paths) == {"json", "markdown"}
    payload = json.loads(paths["json"].read_text(encoding="utf-8"))
    markdown = paths["markdown"].read_text(encoding="utf-8")

    assert payload["reference_policy_status"] == "reference_mismatch_observed"
    assert payload["external_reference"]["ref_area"] == 1.0
    assert "reference_mismatch_observed" in markdown
