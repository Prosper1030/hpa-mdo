from pathlib import Path

import pytest

from hpa_meshing.providers.esp_runtime import detect_esp_runtime
from hpa_meshing.tail_wing_explicit_volume_route_probe import (
    build_tail_wing_explicit_volume_route_probe_report,
    write_tail_wing_explicit_volume_route_probe_report,
)


def _skip_without_esp_runtime() -> None:
    runtime = detect_esp_runtime()
    if not runtime.available:
        pytest.skip("ESP/OpenCSM runtime not available")
    pytest.importorskip("openvsp")
    pytest.importorskip("gmsh")
    if not (Path(__file__).resolve().parents[2] / "data" / "blackcat_004_origin.vsp3").exists():
        pytest.skip("blackcat_004_origin.vsp3 not available")


def test_tail_wing_explicit_volume_route_probe_blocks_false_handoff(tmp_path: Path):
    _skip_without_esp_runtime()

    report = build_tail_wing_explicit_volume_route_probe_report(tmp_path / "probe")

    assert report.schema_version == "tail_wing_explicit_volume_route_probe.v1"
    assert report.component == "tail_wing"
    assert report.route_probe_status == "explicit_volume_route_blocked"
    assert report.mesh_handoff_status == "not_written"
    assert report.su2_volume_handoff_status == "not_su2_ready"
    assert report.provider_status == "materialized"
    assert report.provider_surface_count == 6
    assert report.provider_volume_count == 0
    assert report.surface_loop_volume_status == "volume_created"
    assert report.surface_loop_farfield_cut_status == "invalid_fluid_boundary"
    assert report.baffle_fragment_status == "mesh_failed_plc"
    assert report.surface_loop_signed_volume is not None
    assert report.surface_loop_signed_volume < 0.0
    assert "tail_explicit_surface_loop_volume_not_valid_external_flow_handoff" in report.blocking_reasons
    assert "tail_baffle_fragment_mesh_failed_plc" in report.blocking_reasons
    assert "explicit_occ_surface_loop_add_volume_attempted" in report.hpa_mdo_guarantees
    assert "baffle_fragment_volume_attempted" in report.hpa_mdo_guarantees


def test_tail_wing_explicit_volume_route_probe_writer_outputs_report_files(
    tmp_path: Path,
):
    _skip_without_esp_runtime()

    paths = write_tail_wing_explicit_volume_route_probe_report(tmp_path / "probe")

    assert set(paths) == {"json", "markdown"}
    assert paths["json"].exists()
    assert paths["markdown"].exists()
    markdown = paths["markdown"].read_text(encoding="utf-8")
    assert "explicit_volume_route_blocked" in markdown
    assert "tail_baffle_fragment_mesh_failed_plc" in markdown
