import json
from pathlib import Path

import pytest

from hpa_meshing.providers.esp_runtime import detect_esp_runtime
from hpa_meshing.tail_wing_esp_rebuilt_geometry_smoke import (
    build_tail_wing_esp_rebuilt_geometry_smoke_report,
    write_tail_wing_esp_rebuilt_geometry_smoke_report,
)


def _blackcat_vsp_path() -> Path:
    return Path(__file__).resolve().parents[2] / "data" / "blackcat_004_origin.vsp3"


def _skip_without_esp_runtime() -> None:
    runtime = detect_esp_runtime()
    if not runtime.available:
        pytest.skip("ESP/OpenCSM runtime not available")
    pytest.importorskip("openvsp")
    if not _blackcat_vsp_path().exists():
        pytest.skip("blackcat_004_origin.vsp3 not available")


def test_tail_wing_esp_rebuilt_geometry_smoke_materializes_real_provider_geometry(
    tmp_path: Path,
):
    _skip_without_esp_runtime()

    report = build_tail_wing_esp_rebuilt_geometry_smoke_report(tmp_path / "smoke")

    assert report.schema_version == "tail_wing_esp_rebuilt_geometry_smoke.v1"
    assert report.component == "tail_wing"
    assert report.source_fixture == "blackcat_004_origin_vsp3"
    assert report.geometry_smoke_status == "geometry_smoke_pass"
    assert report.provider_status == "materialized"
    assert report.validation_status == "success"
    assert report.geometry_family == "thin_sheet_lifting_surface"
    assert report.no_gmsh_execution is True
    assert report.no_su2_execution is True
    assert report.production_default_changed is False
    assert report.mesh_handoff_status == "not_run"
    assert report.su2_handoff_status == "not_run"
    assert report.effective_component == "horizontal_tail"
    assert report.selected_geom_name == "Elevator"
    assert report.normalized_geometry_path is not None
    assert Path(report.normalized_geometry_path).exists()
    assert report.surface_count >= 1
    assert "esp_rebuilt_tail_wing_geometry_materialized" in report.hpa_mdo_guarantees
    assert "tail_real_geometry_mesh_handoff_not_run" in report.blocking_reasons


def test_tail_wing_esp_rebuilt_geometry_smoke_writer_outputs_json_and_markdown(
    tmp_path: Path,
):
    _skip_without_esp_runtime()

    paths = write_tail_wing_esp_rebuilt_geometry_smoke_report(tmp_path / "smoke")

    assert set(paths) == {"json", "markdown"}
    payload = json.loads(paths["json"].read_text(encoding="utf-8"))
    markdown = paths["markdown"].read_text(encoding="utf-8")

    assert payload["geometry_smoke_status"] == "geometry_smoke_pass"
    assert payload["provider_status"] == "materialized"
    assert payload["effective_component"] == "horizontal_tail"
    assert "tail_wing" in markdown
    assert "esp_rebuilt" in markdown
