from pathlib import Path

import pytest

from hpa_meshing.providers.esp_runtime import detect_esp_runtime
from hpa_meshing.tail_wing_solidification_probe import (
    build_tail_wing_solidification_probe_report,
    write_tail_wing_solidification_probe_report,
)


def _skip_without_esp_runtime() -> None:
    runtime = detect_esp_runtime()
    if not runtime.available:
        pytest.skip("ESP/OpenCSM runtime not available")
    pytest.importorskip("openvsp")
    pytest.importorskip("gmsh")
    if not (Path(__file__).resolve().parents[2] / "data" / "blackcat_004_origin.vsp3").exists():
        pytest.skip("blackcat_004_origin.vsp3 not available")


def test_tail_wing_solidification_probe_records_naive_heal_no_volume(
    tmp_path: Path,
):
    _skip_without_esp_runtime()

    report = build_tail_wing_solidification_probe_report(tmp_path / "probe")

    assert report.schema_version == "tail_wing_solidification_probe.v1"
    assert report.component == "tail_wing"
    assert report.solidification_status == "no_volume_created"
    assert report.provider_status == "materialized"
    assert report.provider_surface_count >= 1
    assert report.provider_volume_count == 0
    assert report.best_output_volume_count == 0
    assert report.best_output_surface_count >= report.provider_surface_count
    assert len(report.attempts) >= 1
    assert "naive_gmsh_heal_make_solids_attempted" in report.hpa_mdo_guarantees
    assert "tail_naive_gmsh_heal_solidification_no_volume" in report.blocking_reasons
    assert report.recommended_next == "explicit_caps_or_baffle_volume_route_required"


def test_tail_wing_solidification_probe_writer_outputs_report_files(
    tmp_path: Path,
):
    _skip_without_esp_runtime()

    paths = write_tail_wing_solidification_probe_report(tmp_path / "probe")

    assert set(paths) == {"json", "markdown"}
    assert paths["json"].exists()
    assert paths["markdown"].exists()
    markdown = paths["markdown"].read_text(encoding="utf-8")
    assert "no_volume_created" in markdown
    assert "explicit_caps_or_baffle_volume_route_required" in markdown
