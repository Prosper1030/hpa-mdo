from pathlib import Path

import pytest

from hpa_meshing.providers.esp_runtime import detect_esp_runtime
from hpa_meshing.tail_wing_surface_mesh_probe import (
    build_tail_wing_surface_mesh_probe_report,
    write_tail_wing_surface_mesh_probe_report,
)


def _skip_without_esp_runtime() -> None:
    runtime = detect_esp_runtime()
    if not runtime.available:
        pytest.skip("ESP/OpenCSM runtime not available")
    pytest.importorskip("openvsp")
    pytest.importorskip("gmsh")
    if not (Path(__file__).resolve().parents[2] / "data" / "blackcat_004_origin.vsp3").exists():
        pytest.skip("blackcat_004_origin.vsp3 not available")


def test_tail_wing_surface_mesh_probe_generates_real_surface_mesh_not_handoff(
    tmp_path: Path,
):
    _skip_without_esp_runtime()

    report = build_tail_wing_surface_mesh_probe_report(tmp_path / "probe")

    assert report.schema_version == "tail_wing_surface_mesh_probe.v1"
    assert report.component == "tail_wing"
    assert report.probe_status == "surface_mesh_pass"
    assert report.surface_mesh_status == "written"
    assert report.mesh_handoff_status == "not_written"
    assert report.su2_volume_handoff_status == "not_su2_ready"
    assert report.no_su2_execution is True
    assert report.production_default_changed is False
    assert report.provider_status == "materialized"
    assert report.provider_surface_count >= 1
    assert report.provider_volume_count == 0
    assert report.imported_surface_count >= 1
    assert report.surface_element_count is not None
    assert report.surface_element_count > 0
    assert report.volume_element_count == 0
    assert "tail_wing_surface_marker_present" in report.hpa_mdo_guarantees
    assert "surface_only_tail_mesh_not_external_flow_volume_handoff" in report.blocking_reasons
    assert "mesh_handoff.v1 is not emitted by the surface-only probe." in report.limitations


def test_tail_wing_surface_mesh_probe_writer_outputs_report_files(
    tmp_path: Path,
):
    _skip_without_esp_runtime()

    paths = write_tail_wing_surface_mesh_probe_report(tmp_path / "probe")

    assert set(paths) == {"json", "markdown"}
    assert paths["json"].exists()
    assert paths["markdown"].exists()
    markdown = paths["markdown"].read_text(encoding="utf-8")
    assert "not_su2_ready" in markdown
    assert "surface_only_tail_mesh_not_external_flow_volume_handoff" in markdown
