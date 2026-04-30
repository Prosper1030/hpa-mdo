import json
import subprocess
from pathlib import Path

from hpa_meshing.main_wing_esp_rebuilt_geometry_smoke import (
    MainWingESPRebuiltGeometrySmokeReport,
)
from hpa_meshing.main_wing_real_mesh_handoff_probe import (
    _run_bounded_mesh_job,
    build_main_wing_real_mesh_handoff_probe_report,
    write_main_wing_real_mesh_handoff_probe_report,
)


def _provider_report(tmp_path: Path) -> MainWingESPRebuiltGeometrySmokeReport:
    normalized = tmp_path / "normalized.stp"
    normalized.write_text("ISO-10303-21;\nEND-ISO-10303-21;\n", encoding="utf-8")
    return MainWingESPRebuiltGeometrySmokeReport(
        source_path=str(tmp_path / "blackcat_004_origin.vsp3"),
        case_dir=str(tmp_path / "provider"),
        geometry_smoke_status="geometry_smoke_pass",
        provider_status="materialized",
        validation_status="success",
        normalized_geometry_path=str(normalized),
        effective_component="main_wing",
        selected_geom_name="Main Wing",
        selected_geom_span_y=16.47465195857948,
        selected_geom_chord_x=1.3023502084398801,
        body_count=1,
        surface_count=32,
        volume_count=1,
        hpa_mdo_guarantees=[
            "real_vsp3_source_consumed",
            "esp_rebuilt_main_wing_geometry_materialized",
        ],
        blocking_reasons=["main_wing_real_geometry_mesh_handoff_not_run"],
    )


def test_main_wing_real_mesh_handoff_probe_records_pass_when_bounded_job_writes_handoff(
    monkeypatch,
    tmp_path: Path,
):
    source = tmp_path / "blackcat_004_origin.vsp3"
    source.write_text("<Vsp_Geometry />\n", encoding="utf-8")

    monkeypatch.setattr(
        "hpa_meshing.main_wing_real_mesh_handoff_probe.build_main_wing_esp_rebuilt_geometry_smoke_report",
        lambda out_dir, source_path=None: _provider_report(tmp_path),
    )

    mesh_metadata_path = tmp_path / "mesh_metadata.json"
    mesh_metadata_path.write_text(
        json.dumps(
            {
                "quality_metrics": {
                    "tetrahedron_count": 584460,
                    "ill_shaped_tet_count": 78,
                    "non_positive_min_sicn_count": 0,
                    "non_positive_min_sige_count": 0,
                    "non_positive_volume_count": 0,
                    "min_gamma": 8.13e-7,
                    "min_sicn": 7.79e-4,
                    "min_sige": 8.65e-4,
                    "min_volume": 1.09e-6,
                    "gamma_percentiles": {"p01": 0.133, "p05": 0.332},
                    "worst_20_tets": [{"element_id": 515801}],
                }
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "hpa_meshing.main_wing_real_mesh_handoff_probe._run_bounded_mesh_job",
        lambda **_: {
            "status": "completed",
            "timeout_seconds": 12.0,
            "result": {
                "status": "success",
                "failure_code": None,
                "mesh": {
                    "contract": "mesh_handoff.v1",
                    "route_stage": "real_gmsh",
                    "metadata_path": str(mesh_metadata_path),
                    "marker_summary_path": str(tmp_path / "marker_summary.json"),
                    "node_count": 120,
                    "element_count": 300,
                    "surface_element_count": 180,
                    "volume_element_count": 120,
                    "marker_summary": {
                        "main_wing": {"exists": True},
                        "farfield": {"exists": True},
                    },
                },
            },
            "error": None,
        },
    )

    report = build_main_wing_real_mesh_handoff_probe_report(
        tmp_path / "probe",
        source_path=source,
    )

    assert report.schema_version == "main_wing_real_mesh_handoff_probe.v1"
    assert report.probe_status == "mesh_handoff_pass"
    assert report.mesh_handoff_status == "written"
    assert report.provider_status == "materialized"
    assert report.provider_volume_count == 1
    assert report.no_su2_execution is True
    assert report.production_default_changed is False
    assert report.probe_profile == "coarse_first_volume_insertion_probe_not_production_default"
    assert report.coarse_first_tetra_enabled is True
    assert "mesh_handoff_v1_written_for_real_main_wing_probe" in report.hpa_mdo_guarantees
    assert "main_wing_solver_not_run" in report.blocking_reasons
    assert report.mesh_quality_status == "warn"
    assert report.mesh_quality_metrics["ill_shaped_tet_count"] == 78
    assert report.mesh_quality_metrics["worst_tet_sample_count"] == 1
    assert "gmsh_ill_shaped_tets_present" in report.mesh_quality_advisory_flags
    assert "gmsh_min_gamma_below_1e_minus_4" in report.mesh_quality_advisory_flags


def test_main_wing_real_mesh_handoff_probe_records_bounded_timeout(
    monkeypatch,
    tmp_path: Path,
):
    source = tmp_path / "blackcat_004_origin.vsp3"
    source.write_text("<Vsp_Geometry />\n", encoding="utf-8")

    monkeypatch.setattr(
        "hpa_meshing.main_wing_real_mesh_handoff_probe.build_main_wing_esp_rebuilt_geometry_smoke_report",
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
            (
                "{"
                '"status": "triggered_while_meshing", '
                '"timeout_phase_classification": "volume_insertion", '
                '"nodes_created_per_boundary_node": 13.5, '
                '"iteration_count": 160000, '
                '"latest_worst_tet_radius": 1.43'
                "}\n"
            ),
            encoding="utf-8",
        )
        (mesh_dir / "surface_patch_diagnostics.json").write_text(
            json.dumps(
                {
                    "family_hint_counts": {
                        "high_aspect_strip_candidate": 24,
                        "short_curve_candidate": 22,
                        "span_extreme_candidate": 8,
                        "tiny_face_candidate": 22,
                    },
                    "suspicious_surfaces": [
                        {"tag": 31, "family_hints": ["tiny_face_candidate"]},
                        {"tag": 32, "family_hints": ["tiny_face_candidate"]},
                        {"tag": 6, "family_hints": ["high_aspect_strip_candidate"]},
                    ],
                }
            )
            + "\n",
            encoding="utf-8",
        )
        return {
            "status": "timeout",
            "timeout_seconds": 12.0,
            "result": None,
            "error": "bounded_mesh_handoff_timeout_after_12.0s",
        }

    monkeypatch.setattr(
        "hpa_meshing.main_wing_real_mesh_handoff_probe._run_bounded_mesh_job",
        _timeout_runner,
    )

    report = build_main_wing_real_mesh_handoff_probe_report(
        tmp_path / "probe",
        source_path=source,
    )

    assert report.probe_status == "mesh_handoff_timeout"
    assert report.mesh_handoff_status == "missing"
    assert report.mesh_probe_status == "timeout"
    assert "main_wing_real_geometry_mesh_handoff_timeout" in report.blocking_reasons
    assert "main_wing_real_geometry_mesh3d_volume_insertion_timeout" in report.blocking_reasons
    assert report.mesh2d_watchdog_status == "completed_without_timeout"
    assert report.mesh3d_watchdog_status == "triggered_while_meshing"
    assert report.mesh3d_timeout_phase_classification == "volume_insertion"
    assert report.mesh3d_nodes_created_per_boundary_node == 13.5
    assert report.probe_profile == "coarse_first_volume_insertion_probe_not_production_default"
    assert report.coarse_first_tetra_enabled is True
    assert report.surface_patch_diagnostics_status == "available"
    assert report.surface_family_hint_counts["high_aspect_strip_candidate"] == 24
    assert report.suspicious_surface_tags == [31, 32, 6]
    assert "bounded_mesh_probe_executed" in report.hpa_mdo_guarantees


def test_main_wing_real_mesh_handoff_probe_classifies_invalid_boundary_mesh(
    monkeypatch,
    tmp_path: Path,
):
    source = tmp_path / "blackcat_004_origin.vsp3"
    source.write_text("<Vsp_Geometry />\n", encoding="utf-8")

    monkeypatch.setattr(
        "hpa_meshing.main_wing_real_mesh_handoff_probe.build_main_wing_esp_rebuilt_geometry_smoke_report",
        lambda out_dir, source_path=None: _provider_report(tmp_path),
    )

    def _failed_runner(**kwargs):
        mesh_dir = kwargs["case_dir"] / "artifacts" / "mesh"
        mesh_dir.mkdir(parents=True, exist_ok=True)
        (mesh_dir / "mesh2d_watchdog.json").write_text(
            '{"status": "completed_without_timeout"}\n',
            encoding="utf-8",
        )
        (mesh_dir / "mesh3d_watchdog.json").write_text(
            (
                "{"
                '"status": "failed_without_timeout", '
                '"timeout_phase_classification": "boundary_recovery"'
                "}\n"
            ),
            encoding="utf-8",
        )
        return {
            "status": "failed",
            "timeout_seconds": 12.0,
            "result": {
                "status": "failed",
                "failure_code": "gmsh_invalid_boundary_mesh",
                "error": "Invalid boundary mesh (overlapping facets) on surface 39 surface 58",
                "mesh": {
                    "node_count": 3894,
                    "element_count": 8737,
                    "surface_element_count": 7780,
                    "volume_element_count": 0,
                },
            },
            "error": "child stderr should not hide the structured gmsh error",
        }

    monkeypatch.setattr(
        "hpa_meshing.main_wing_real_mesh_handoff_probe._run_bounded_mesh_job",
        _failed_runner,
    )

    report = build_main_wing_real_mesh_handoff_probe_report(
        tmp_path / "probe",
        source_path=source,
        global_min_size=0.35,
        global_max_size=1.4,
    )

    assert report.probe_status == "mesh_handoff_blocked"
    assert report.mesh_probe_status == "failed"
    assert report.mesh_failure_classification == "invalid_boundary_mesh_overlapping_facets"
    assert (
        "main_wing_real_geometry_invalid_boundary_mesh_overlapping_facets"
        in report.blocking_reasons
    )
    assert report.failure_code == "gmsh_invalid_boundary_mesh"
    assert report.mesh3d_watchdog_status == "failed_without_timeout"
    assert report.mesh3d_timeout_phase_classification == "boundary_recovery"
    assert report.volume_element_count == 0


def test_main_wing_real_mesh_handoff_probe_classifies_boundary_parametrization_failure(
    monkeypatch,
    tmp_path: Path,
):
    source = tmp_path / "blackcat_004_origin.vsp3"
    source.write_text("<Vsp_Geometry />\n", encoding="utf-8")

    monkeypatch.setattr(
        "hpa_meshing.main_wing_real_mesh_handoff_probe.build_main_wing_esp_rebuilt_geometry_smoke_report",
        lambda out_dir, source_path=None: _provider_report(tmp_path),
    )

    monkeypatch.setattr(
        "hpa_meshing.main_wing_real_mesh_handoff_probe._run_bounded_mesh_job",
        lambda **_: {
            "status": "failed",
            "timeout_seconds": 12.0,
            "result": {
                "status": "failed",
                "failure_code": "gmsh_boundary_parametrization_topology",
                "error": "Wrong topology of boundary mesh for parametrization",
            },
            "error": None,
        },
    )

    report = build_main_wing_real_mesh_handoff_probe_report(
        tmp_path / "probe",
        source_path=source,
    )

    assert report.probe_status == "mesh_handoff_blocked"
    assert report.mesh_failure_classification == "boundary_parametrization_topology_failed"
    assert (
        "main_wing_real_geometry_boundary_parametrization_topology_failed"
        in report.blocking_reasons
    )


def test_main_wing_real_mesh_probe_child_payload_uses_coarse_first_volume_profile(
    monkeypatch,
    tmp_path: Path,
):
    source = tmp_path / "blackcat_004_origin.vsp3"
    source.write_text("<Vsp_Geometry />\n", encoding="utf-8")
    captured: dict[str, object] = {}

    def _fake_run(cmd, **kwargs):
        payload = json.loads(Path(cmd[-1]).read_text(encoding="utf-8"))
        captured["metadata"] = payload["metadata"]
        captured["global_min_size"] = payload["global_min_size"]
        captured["global_max_size"] = payload["global_max_size"]
        Path(payload["result_path"]).write_text(
            json.dumps({"status": "failed", "failure_code": "intentional_probe_stop"})
            + "\n",
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(cmd, returncode=1, stdout="", stderr="intentional")

    monkeypatch.setattr(
        "hpa_meshing.main_wing_real_mesh_handoff_probe.subprocess.run",
        _fake_run,
    )

    mesh_run = _run_bounded_mesh_job(
        source_path=source,
        case_dir=tmp_path / "case",
        timeout_seconds=3.0,
        global_min_size=0.35,
        global_max_size=1.4,
    )

    assert mesh_run["status"] == "failed"
    metadata = captured["metadata"]
    assert isinstance(metadata, dict)
    assert captured["global_min_size"] == 0.35
    assert captured["global_max_size"] == 1.4
    assert metadata["coarse_first_tetra_enabled"] is True
    assert metadata["mesh3d_watchdog_timeout_sec"] == 8.0
    assert metadata["reference_geometry"]["ref_area"] == 34.65
    assert (
        metadata["probe_profile"]
        == "coarse_first_volume_insertion_probe_not_production_default"
    )


def test_main_wing_real_mesh_probe_child_payload_uses_absolute_paths_for_relative_case_dir(
    monkeypatch,
    tmp_path: Path,
):
    monkeypatch.chdir(tmp_path)
    source = Path("blackcat_004_origin.vsp3")
    source.write_text("<Vsp_Geometry />\n", encoding="utf-8")
    captured: dict[str, object] = {}

    def _fake_run(cmd, **kwargs):
        payload_path = Path(cmd[-1])
        assert payload_path.is_absolute()
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
        captured["source_path"] = payload["source_path"]
        captured["case_dir"] = payload["case_dir"]
        captured["result_path"] = payload["result_path"]
        Path(payload["result_path"]).write_text(
            json.dumps({"status": "failed", "failure_code": "intentional_probe_stop"})
            + "\n",
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(cmd, returncode=1, stdout="", stderr="intentional")

    monkeypatch.setattr(
        "hpa_meshing.main_wing_real_mesh_handoff_probe.subprocess.run",
        _fake_run,
    )

    mesh_run = _run_bounded_mesh_job(
        source_path=source,
        case_dir=Path("relative_probe_case"),
        timeout_seconds=3.0,
    )

    assert mesh_run["status"] == "failed"
    assert Path(str(captured["source_path"])).is_absolute()
    assert Path(str(captured["case_dir"])).is_absolute()
    assert Path(str(captured["result_path"])).is_absolute()


def test_main_wing_real_mesh_probe_report_records_probe_sizing(
    monkeypatch,
    tmp_path: Path,
):
    source = tmp_path / "blackcat_004_origin.vsp3"
    source.write_text("<Vsp_Geometry />\n", encoding="utf-8")
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "hpa_meshing.main_wing_real_mesh_handoff_probe.build_main_wing_esp_rebuilt_geometry_smoke_report",
        lambda out_dir, source_path=None: _provider_report(tmp_path),
    )

    def _fake_runner(**kwargs):
        captured.update(kwargs)
        return {
            "status": "failed",
            "timeout_seconds": kwargs["timeout_seconds"],
            "result": {"status": "failed", "failure_code": "intentional_probe_stop"},
            "error": "intentional",
        }

    monkeypatch.setattr(
        "hpa_meshing.main_wing_real_mesh_handoff_probe._run_bounded_mesh_job",
        _fake_runner,
    )

    report = build_main_wing_real_mesh_handoff_probe_report(
        tmp_path / "probe",
        source_path=source,
        global_min_size=0.35,
        global_max_size=1.4,
    )

    assert captured["global_min_size"] == 0.35
    assert captured["global_max_size"] == 1.4
    assert report.probe_global_min_size == 0.35
    assert report.probe_global_max_size == 1.4


def test_main_wing_real_mesh_handoff_probe_writer_outputs_json_and_markdown(
    monkeypatch,
    tmp_path: Path,
):
    source = tmp_path / "blackcat_004_origin.vsp3"
    source.write_text("<Vsp_Geometry />\n", encoding="utf-8")

    monkeypatch.setattr(
        "hpa_meshing.main_wing_real_mesh_handoff_probe.build_main_wing_esp_rebuilt_geometry_smoke_report",
        lambda out_dir, source_path=None: _provider_report(tmp_path),
    )
    monkeypatch.setattr(
        "hpa_meshing.main_wing_real_mesh_handoff_probe._run_bounded_mesh_job",
        lambda **_: {
            "status": "timeout",
            "timeout_seconds": 12.0,
            "result": None,
            "error": "bounded_mesh_handoff_timeout_after_12.0s",
        },
    )

    paths = write_main_wing_real_mesh_handoff_probe_report(
        tmp_path / "probe",
        source_path=source,
    )

    assert set(paths) == {"json", "markdown"}
    assert paths["json"].exists()
    assert "mesh_handoff_timeout" in paths["markdown"].read_text(encoding="utf-8")
