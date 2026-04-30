from pathlib import Path

import pytest

from hpa_meshing.providers.esp_runtime import detect_esp_runtime
from hpa_meshing.tail_wing_real_mesh_handoff_probe import (
    build_tail_wing_real_mesh_handoff_probe_report,
    write_tail_wing_real_mesh_handoff_probe_report,
)


def _skip_without_esp_runtime() -> None:
    runtime = detect_esp_runtime()
    if not runtime.available:
        pytest.skip("ESP/OpenCSM runtime not available")
    pytest.importorskip("openvsp")
    if not (Path(__file__).resolve().parents[2] / "data" / "blackcat_004_origin.vsp3").exists():
        pytest.skip("blackcat_004_origin.vsp3 not available")


def test_tail_wing_real_mesh_handoff_probe_records_surface_only_blocker(
    tmp_path: Path,
):
    _skip_without_esp_runtime()

    report = build_tail_wing_real_mesh_handoff_probe_report(tmp_path / "probe")

    assert report.schema_version == "tail_wing_real_mesh_handoff_probe.v1"
    assert report.component == "tail_wing"
    assert report.probe_status == "mesh_handoff_blocked"
    assert report.failure_code == "gmsh_backend_failed"
    assert report.mesh_handoff_status == "missing"
    assert report.no_su2_execution is True
    assert report.provider_status == "materialized"
    assert report.provider_surface_count >= 1
    assert report.provider_volume_count == 0
    assert "real_tail_geometry_surface_only_no_occ_volume" in report.blocking_reasons
    assert "synthetic_tail_slab_is_not_real_tail_mesh_evidence" in report.limitations


def test_tail_wing_real_mesh_handoff_probe_writer_outputs_report_files(
    tmp_path: Path,
):
    _skip_without_esp_runtime()

    paths = write_tail_wing_real_mesh_handoff_probe_report(tmp_path / "probe")

    assert set(paths) == {"json", "markdown"}
    assert paths["json"].exists()
    assert paths["markdown"].exists()
    assert "surface_only" in paths["markdown"].read_text(encoding="utf-8")
