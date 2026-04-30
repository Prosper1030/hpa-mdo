import json
from pathlib import Path

import pytest

from hpa_meshing.fairing_solid_real_geometry_smoke import (
    build_fairing_solid_real_geometry_smoke_report,
    write_fairing_solid_real_geometry_smoke_report,
)
from hpa_meshing.providers.esp_runtime import detect_esp_runtime


def _external_fairing_vsp_path() -> Path:
    return Path(
        "/Volumes/Samsung SSD/HPA-Fairing-Optimization-Project/output/"
        "hpa_run_20260417_155036/vsp_models/best_design.vsp3"
    )


def _skip_without_real_fairing_source() -> None:
    runtime = detect_esp_runtime()
    if not runtime.available:
        pytest.skip("ESP/OpenVSP runtime not available")
    pytest.importorskip("openvsp")
    if not _external_fairing_vsp_path().exists():
        pytest.skip("external fairing best_design.vsp3 not available")


def _fake_validation_result(source: Path, normalized: Path) -> dict:
    normalized.parent.mkdir(parents=True, exist_ok=True)
    normalized.write_text("ISO-10303-21;\nEND-ISO-10303-21;\n", encoding="utf-8")
    topology_report = normalized.parent / "topology.json"
    provider_log = normalized.parent / "provider_log.json"
    topology = {
        "units": "m",
        "bounds": {
            "x_min": 0.0,
            "x_max": 2.8,
            "y_min": -0.28,
            "y_max": 0.28,
            "z_min": -0.27,
            "z_max": 0.85,
        },
        "import_bounds": {
            "x_min": 0.0,
            "x_max": 2800.0,
            "y_min": -280.0,
            "y_max": 280.0,
            "z_min": -270.0,
            "z_max": 850.0,
        },
        "import_scale_to_units": 0.001,
        "backend_rescale_required": True,
        "body_count": 1,
        "surface_count": 8,
        "volume_count": 1,
        "notes": [
            "gmsh_occ_import_requires_rescale_to_declared_units:scale=0.001",
        ],
    }
    topology_report.write_text(json.dumps(topology), encoding="utf-8")
    provider_log.write_text("{}", encoding="utf-8")
    return {
        "status": "success",
        "geometry": str(source),
        "normalized_geometry": str(normalized),
        "geometry_provider": "openvsp_surface_intersection",
        "geometry_family": "closed_solid",
        "provider": {
            "status": "materialized",
            "topology": topology,
            "artifacts": {
                "topology_report": str(topology_report),
                "provider_log": str(provider_log),
            },
        },
        "validation": {"ok": True},
    }


def test_fairing_solid_real_geometry_smoke_materializes_closed_solid_with_fake_runtime(
    tmp_path: Path,
    monkeypatch,
):
    from hpa_meshing import fairing_solid_real_geometry_smoke as smoke_module

    source = tmp_path / "best_design.vsp3"
    source.write_text("<vsp3/>", encoding="utf-8")
    monkeypatch.setattr(
        smoke_module,
        "_inspect_openvsp_geometries",
        lambda path: {
            "geometries": [
                {
                    "geom_id": "FAIRING",
                    "name": "best_design",
                    "type_name": "Fuselage",
                }
            ],
            "selected_geom": {
                "geom_id": "FAIRING",
                "name": "best_design",
                "type_name": "Fuselage",
            },
            "fairing_candidate_count": 1,
        },
    )
    monkeypatch.setattr(
        smoke_module,
        "validate_geometry_only",
        lambda config: _fake_validation_result(
            source,
            tmp_path / "smoke" / "artifacts" / "providers" / "normalized.stp",
        ),
    )

    report = build_fairing_solid_real_geometry_smoke_report(
        tmp_path / "smoke",
        source_path=source,
    )

    assert report.schema_version == "fairing_solid_real_geometry_smoke.v1"
    assert report.component == "fairing_solid"
    assert report.source_fixture == "custom_vsp3"
    assert report.geometry_smoke_status == "geometry_smoke_pass"
    assert report.provider_status == "materialized"
    assert report.validation_status == "success"
    assert report.geometry_provider == "openvsp_surface_intersection"
    assert report.geometry_family == "closed_solid"
    assert report.no_gmsh_meshing_execution is True
    assert report.gmsh_topology_probe_status == "observed"
    assert report.no_su2_execution is True
    assert report.production_default_changed is False
    assert report.selected_geom_name == "best_design"
    assert report.selected_geom_type == "Fuselage"
    assert report.body_count == 1
    assert report.surface_count == 8
    assert report.volume_count == 1
    assert report.backend_rescale_required is True
    assert "real_fairing_vsp3_source_consumed" in report.hpa_mdo_guarantees
    assert "fairing_closed_solid_topology_observed" in report.hpa_mdo_guarantees
    assert "fairing_real_geometry_mesh_handoff_not_run" in report.blocking_reasons


def test_fairing_solid_real_geometry_smoke_missing_source_is_unavailable(tmp_path: Path):
    missing = tmp_path / "missing.vsp3"

    report = build_fairing_solid_real_geometry_smoke_report(
        tmp_path / "smoke",
        source_path=missing,
    )

    assert report.geometry_smoke_status == "unavailable"
    assert report.provider_status == "unavailable"
    assert report.validation_status == "not_run"
    assert report.promotion_status == "not_evaluated"
    assert "fairing_real_source_vsp3_missing" in report.blocking_reasons


def test_fairing_solid_real_geometry_smoke_writer_outputs_json_and_markdown(
    tmp_path: Path,
    monkeypatch,
):
    from hpa_meshing import fairing_solid_real_geometry_smoke as smoke_module

    source = tmp_path / "best_design.vsp3"
    source.write_text("<vsp3/>", encoding="utf-8")
    monkeypatch.setattr(
        smoke_module,
        "_inspect_openvsp_geometries",
        lambda path: {
            "geometries": [
                {
                    "geom_id": "FAIRING",
                    "name": "best_design",
                    "type_name": "Fuselage",
                }
            ],
            "selected_geom": {
                "geom_id": "FAIRING",
                "name": "best_design",
                "type_name": "Fuselage",
            },
            "fairing_candidate_count": 1,
        },
    )
    monkeypatch.setattr(
        smoke_module,
        "validate_geometry_only",
        lambda config: _fake_validation_result(
            source,
            tmp_path / "smoke" / "artifacts" / "providers" / "normalized.stp",
        ),
    )

    paths = write_fairing_solid_real_geometry_smoke_report(
        tmp_path / "smoke",
        source_path=source,
    )

    assert set(paths) == {"json", "markdown"}
    payload = json.loads(paths["json"].read_text(encoding="utf-8"))
    markdown = paths["markdown"].read_text(encoding="utf-8")
    assert payload["geometry_smoke_status"] == "geometry_smoke_pass"
    assert payload["selected_geom_type"] == "Fuselage"
    assert payload["gmsh_topology_probe_status"] == "observed"
    assert "fairing_solid" in markdown
    assert "openvsp_surface_intersection" in markdown


def test_fairing_solid_real_geometry_smoke_materializes_external_best_design(
    tmp_path: Path,
):
    _skip_without_real_fairing_source()

    report = build_fairing_solid_real_geometry_smoke_report(tmp_path / "smoke")

    assert report.source_fixture == "hpa_fairing_best_design_vsp3"
    assert report.geometry_smoke_status == "geometry_smoke_pass"
    assert report.provider_status == "materialized"
    assert report.validation_status == "success"
    assert report.selected_geom_type == "Fuselage"
    assert report.volume_count and report.volume_count >= 1
    assert report.normalized_geometry_path is not None
    assert Path(report.normalized_geometry_path).exists()
