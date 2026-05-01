import json
from pathlib import Path

from hpa_meshing.main_wing_station_seam_export_format_boundary_probe import (
    build_main_wing_station_seam_export_format_boundary_probe_report,
    write_main_wing_station_seam_export_format_boundary_probe_report,
)


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def _write_source_csm(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "mark",
        "skbeg 1.0 -1.0 0.0",
        "   spline 0.4 -1.0 0.08",
        "   spline 0.0 -1.0 0.0",
        "   spline 0.4 -1.0 -0.08",
        "   linseg 1.0 -1.0 0.0",
        "skend",
        "skbeg 1.0 1.0 0.0",
        "   spline 0.4 1.0 0.08",
        "   spline 0.0 1.0 0.0",
        "   spline 0.4 1.0 -0.08",
        "   linseg 1.0 1.0 0.0",
        "skend",
        "rule",
        "DUMP !export_path 0 1",
        "END",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _profile_audit(path: Path, source_csm_path: Path) -> Path:
    return _write_json(
        path,
        {
            "schema_version": "main_wing_station_seam_profile_parametrization_audit.v1",
            "source_csm_path": str(source_csm_path),
            "target_station_y_m": [-1.0, 1.0],
        },
    )


def _source_audit(path: Path) -> Path:
    return _write_json(
        path,
        {
            "schema_version": "main_wing_station_seam_export_metadata_source_audit.v1",
            "audit_status": "export_metadata_generation_source_boundary_captured",
        },
    )


def test_export_format_boundary_detects_step_loss_when_brep_passes(tmp_path: Path):
    source_csm_path = _write_source_csm(tmp_path / "rebuild.csm")

    def materializer(**kwargs):
        export_path = Path(kwargs["out_dir"]) / kwargs["export_filename"]
        export_path.parent.mkdir(parents=True, exist_ok=True)
        export_path.write_text("dummy\n", encoding="utf-8")
        return {
            "status": "materialized",
            "format": kwargs["format_name"],
            "export_path": str(export_path),
            "topology": {"volume_count": 1, "surface_count": 12},
        }

    def validator(**kwargs):
        format_name = kwargs["format_name"]
        if format_name == "step":
            return {"probe_status": "side_aware_candidate_station_brep_edges_suspect"}
        if format_name == "brep":
            return {"probe_status": "side_aware_candidate_station_brep_edges_valid"}
        return {
            "probe_status": "side_aware_candidate_station_brep_validation_unavailable"
        }

    report = build_main_wing_station_seam_export_format_boundary_probe_report(
        profile_parametrization_audit_path=_profile_audit(
            tmp_path / "profile_audit.json",
            source_csm_path,
        ),
        export_metadata_source_audit_path=_source_audit(
            tmp_path / "source_audit.json",
        ),
        formats=["step", "brep", "egads"],
        materialize_formats=True,
        materialization_root=tmp_path / "artifacts",
        external_src_root=tmp_path / "external-src",
        format_materializer=materializer,
        format_validator=validator,
    )

    assert report.probe_status == "export_format_boundary_step_loss_suspected"
    assert report.production_default_changed is False
    assert report.format_summary["materialized_format_count"] == 3
    assert report.format_summary["passed_formats"] == ["brep"]
    assert "step_serialization_or_step_import_metadata_loss_suspected" in (
        report.blocking_reasons
    )
    assert report.next_actions[0] == (
        "run_gmsh_handoff_on_recovered_brep_without_promoting_default"
    )


def test_export_format_boundary_does_not_treat_brep_step_reader_failure_as_geometry_failure(
    tmp_path: Path,
):
    source_csm_path = _write_source_csm(tmp_path / "rebuild.csm")

    def materializer(**kwargs):
        export_path = Path(kwargs["out_dir"]) / kwargs["export_filename"]
        export_path.parent.mkdir(parents=True, exist_ok=True)
        export_path.write_text("dummy\n", encoding="utf-8")
        return {
            "status": "materialized",
            "format": kwargs["format_name"],
            "export_path": str(export_path),
            "topology": {"volume_count": 1, "surface_count": 12},
        }

    def validator(**kwargs):
        if kwargs["format_name"] == "step":
            return {"probe_status": "side_aware_candidate_station_brep_edges_suspect"}
        return {
            "probe_status": "side_aware_candidate_station_brep_validation_unavailable",
            "format_boundary_normalization_reason": (
                "existing_station_hotspot_gate_uses_step_reader_for_non_step_export"
            ),
        }

    report = build_main_wing_station_seam_export_format_boundary_probe_report(
        profile_parametrization_audit_path=_profile_audit(
            tmp_path / "profile_audit.json",
            source_csm_path,
        ),
        export_metadata_source_audit_path=_source_audit(
            tmp_path / "source_audit.json",
        ),
        formats=["step", "brep"],
        materialize_formats=True,
        materialization_root=tmp_path / "artifacts",
        external_src_root=tmp_path / "external-src",
        format_materializer=materializer,
        format_validator=validator,
    )

    assert (
        report.probe_status
        == "export_format_boundary_step_suspect_non_step_validation_unavailable"
    )
    assert "non_step_format_station_gate_reader_unavailable" in (
        report.blocking_reasons
    )
    assert report.next_actions[0] == (
        "add_brep_capable_station_hotspot_reader_or_occ_import_gate"
    )


def test_write_export_format_boundary_probe_report(tmp_path: Path):
    source_csm_path = _write_source_csm(tmp_path / "rebuild.csm")

    written = write_main_wing_station_seam_export_format_boundary_probe_report(
        tmp_path / "out",
        profile_parametrization_audit_path=_profile_audit(
            tmp_path / "profile_audit.json",
            source_csm_path,
        ),
        export_metadata_source_audit_path=_source_audit(
            tmp_path / "source_audit.json",
        ),
        formats=["step", "brep"],
        materialize_formats=False,
        external_src_root=tmp_path / "external-src",
    )

    payload = json.loads(written["json"].read_text(encoding="utf-8"))
    markdown = written["markdown"].read_text(encoding="utf-8")
    assert (
        payload["schema_version"]
        == "main_wing_station_seam_export_format_boundary_probe.v1"
    )
    assert (
        payload["probe_status"]
        == "export_format_boundary_source_only_ready_for_materialization"
    )
    assert "Export Format Boundary Probe v1" in markdown
