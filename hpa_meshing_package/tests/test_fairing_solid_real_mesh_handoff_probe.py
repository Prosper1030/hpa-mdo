import json
from pathlib import Path

from hpa_meshing.fairing_solid_real_geometry_smoke import (
    FairingSolidRealGeometrySmokeReport,
)
from hpa_meshing.fairing_solid_real_mesh_handoff_probe import (
    build_fairing_solid_real_mesh_handoff_probe_report,
    write_fairing_solid_real_mesh_handoff_probe_report,
)


def _provider_report(tmp_path: Path) -> FairingSolidRealGeometrySmokeReport:
    normalized = tmp_path / "normalized.stp"
    normalized.write_text("ISO-10303-21;\nEND-ISO-10303-21;\n", encoding="utf-8")
    return FairingSolidRealGeometrySmokeReport(
        source_path=str(tmp_path / "best_design.vsp3"),
        case_dir=str(tmp_path / "provider"),
        gmsh_topology_probe_status="observed",
        geometry_smoke_status="geometry_smoke_pass",
        provider_status="materialized",
        validation_status="success",
        normalized_geometry_path=str(normalized),
        selected_geom_id="FAIRING",
        selected_geom_name="best_design",
        selected_geom_type="Fuselage",
        source_geom_count=1,
        fairing_candidate_count=1,
        body_count=1,
        surface_count=8,
        volume_count=1,
        units="m",
        backend_rescale_required=True,
        hpa_mdo_guarantees=[
            "real_fairing_vsp3_source_consumed",
            "fairing_closed_solid_topology_observed",
        ],
        blocking_reasons=["fairing_real_geometry_mesh_handoff_not_run"],
    )


def test_fairing_solid_real_mesh_handoff_probe_records_pass_when_bounded_job_writes_handoff(
    monkeypatch,
    tmp_path: Path,
):
    source = tmp_path / "best_design.vsp3"
    source.write_text("<Vsp_Geometry />\n", encoding="utf-8")
    marker_summary_path = tmp_path / "marker_summary.json"
    mesh_metadata_path = tmp_path / "mesh_metadata.json"

    monkeypatch.setattr(
        "hpa_meshing.fairing_solid_real_mesh_handoff_probe.build_fairing_solid_real_geometry_smoke_report",
        lambda out_dir, source_path=None: _provider_report(tmp_path),
    )
    monkeypatch.setattr(
        "hpa_meshing.fairing_solid_real_mesh_handoff_probe._run_bounded_mesh_job",
        lambda **_: {
            "status": "completed",
            "timeout_seconds": 30.0,
            "result": {
                "status": "success",
                "failure_code": None,
                "mesh": {
                    "contract": "mesh_handoff.v1",
                    "route_stage": "baseline",
                    "metadata_path": str(mesh_metadata_path),
                    "marker_summary_path": str(marker_summary_path),
                    "node_count": 240,
                    "element_count": 720,
                    "surface_element_count": 300,
                    "volume_element_count": 420,
                    "marker_summary": {
                        "fairing_solid": {"exists": True},
                        "farfield": {"exists": True},
                    },
                    "unit_normalization": {
                        "backend_rescale_applied": True,
                        "import_scale_to_units": 0.001,
                    },
                },
            },
            "error": None,
        },
    )

    report = build_fairing_solid_real_mesh_handoff_probe_report(
        tmp_path / "probe",
        source_path=source,
    )

    assert report.schema_version == "fairing_solid_real_mesh_handoff_probe.v1"
    assert report.probe_status == "mesh_handoff_pass"
    assert report.mesh_probe_status == "completed"
    assert report.mesh_handoff_status == "written"
    assert report.provider_status == "materialized"
    assert report.marker_summary_status == "component_wall_and_farfield_present"
    assert report.fairing_force_marker_status == "component_specific_marker_present"
    assert report.provider_volume_count == 1
    assert report.volume_element_count == 420
    assert report.backend_rescale_applied is True
    assert report.import_scale_to_units == 0.001
    assert report.no_su2_execution is True
    assert report.production_default_changed is False
    assert "mesh_handoff_v1_written_for_real_fairing_probe" in report.hpa_mdo_guarantees
    assert "fairing_real_geometry_su2_handoff_not_run" in report.blocking_reasons
    assert "fairing_solver_not_run" in report.blocking_reasons


def test_fairing_solid_real_mesh_handoff_probe_records_timeout(
    monkeypatch,
    tmp_path: Path,
):
    source = tmp_path / "best_design.vsp3"
    source.write_text("<Vsp_Geometry />\n", encoding="utf-8")

    monkeypatch.setattr(
        "hpa_meshing.fairing_solid_real_mesh_handoff_probe.build_fairing_solid_real_geometry_smoke_report",
        lambda out_dir, source_path=None: _provider_report(tmp_path),
    )

    def _timeout_runner(**kwargs):
        mesh_dir = kwargs["case_dir"] / "artifacts" / "mesh"
        mesh_dir.mkdir(parents=True, exist_ok=True)
        (mesh_dir / "mesh2d_watchdog.json").write_text(
            '{"status": "completed_without_timeout"}\n',
            encoding="utf-8",
        )
        (mesh_dir / "mesh3d_watchdog.json").write_text(
            '{"status": "triggered_while_meshing", "timeout_phase_classification": "volume_insertion"}\n',
            encoding="utf-8",
        )
        return {
            "status": "timeout",
            "timeout_seconds": 30.0,
            "result": None,
            "error": "bounded_mesh_handoff_timeout_after_30.0s",
        }

    monkeypatch.setattr(
        "hpa_meshing.fairing_solid_real_mesh_handoff_probe._run_bounded_mesh_job",
        _timeout_runner,
    )

    report = build_fairing_solid_real_mesh_handoff_probe_report(
        tmp_path / "probe",
        source_path=source,
    )

    assert report.probe_status == "mesh_handoff_timeout"
    assert report.mesh_probe_status == "timeout"
    assert report.mesh_handoff_status == "missing"
    assert report.mesh2d_watchdog_status == "completed_without_timeout"
    assert report.mesh3d_watchdog_status == "triggered_while_meshing"
    assert report.mesh3d_timeout_phase_classification == "volume_insertion"
    assert "fairing_real_geometry_mesh_handoff_timeout" in report.blocking_reasons
    assert "fairing_real_geometry_mesh3d_volume_insertion_timeout" in report.blocking_reasons


def test_fairing_solid_real_mesh_handoff_probe_writer_outputs_json_and_markdown(
    monkeypatch,
    tmp_path: Path,
):
    source = tmp_path / "best_design.vsp3"
    source.write_text("<Vsp_Geometry />\n", encoding="utf-8")

    monkeypatch.setattr(
        "hpa_meshing.fairing_solid_real_mesh_handoff_probe.build_fairing_solid_real_geometry_smoke_report",
        lambda out_dir, source_path=None: _provider_report(tmp_path),
    )
    monkeypatch.setattr(
        "hpa_meshing.fairing_solid_real_mesh_handoff_probe._run_bounded_mesh_job",
        lambda **_: {
            "status": "timeout",
            "timeout_seconds": 30.0,
            "result": None,
            "error": "bounded_mesh_handoff_timeout_after_30.0s",
        },
    )

    paths = write_fairing_solid_real_mesh_handoff_probe_report(
        tmp_path / "probe",
        source_path=source,
    )

    assert set(paths) == {"json", "markdown"}
    payload = json.loads(paths["json"].read_text(encoding="utf-8"))
    assert payload["probe_status"] == "mesh_handoff_timeout"
    assert "mesh_handoff_timeout" in paths["markdown"].read_text(encoding="utf-8")
