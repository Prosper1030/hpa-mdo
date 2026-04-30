import json
import shutil
from pathlib import Path

import pytest

from hpa_meshing.main_wing_mesh_handoff_smoke import (
    build_main_wing_mesh_handoff_smoke_report,
    write_main_wing_mesh_handoff_smoke_report,
)


def test_main_wing_mesh_handoff_smoke_writes_real_non_bl_handoff(tmp_path: Path):
    if shutil.which("gmsh") is None:
        pytest.skip("gmsh CLI not available")

    report = build_main_wing_mesh_handoff_smoke_report(tmp_path / "smoke")

    assert report.schema_version == "main_wing_mesh_handoff_smoke.v1"
    assert report.component == "main_wing"
    assert report.meshing_route == "gmsh_thin_sheet_surface"
    assert report.no_su2_execution is True
    assert report.no_bl_runtime is True
    assert report.production_default_changed is False
    assert report.smoke_status == "mesh_handoff_pass"
    assert report.mesh_handoff_status == "written"
    assert report.mesh_contract == "mesh_handoff.v1"
    assert report.marker_summary_status == "component_wall_and_farfield_present"
    assert report.wall_marker_status == "main_wing_marker_present"
    assert report.su2_promotion_status == "blocked_before_su2_handoff"
    assert report.volume_element_count > 0
    assert "main_wing_specific_force_marker_present" in report.hpa_mdo_guarantees


def test_main_wing_mesh_handoff_smoke_writer_outputs_json_and_markdown(tmp_path: Path):
    if shutil.which("gmsh") is None:
        pytest.skip("gmsh CLI not available")

    out_dir = tmp_path / "smoke"

    paths = write_main_wing_mesh_handoff_smoke_report(out_dir)

    assert set(paths) == {"json", "markdown"}
    payload = json.loads(paths["json"].read_text(encoding="utf-8"))
    markdown = paths["markdown"].read_text(encoding="utf-8")

    assert payload["smoke_status"] == "mesh_handoff_pass"
    assert payload["mesh_contract"] == "mesh_handoff.v1"
    assert payload["no_su2_execution"] is True
    assert "main_wing" in markdown
    assert "mesh_handoff.v1" in markdown
