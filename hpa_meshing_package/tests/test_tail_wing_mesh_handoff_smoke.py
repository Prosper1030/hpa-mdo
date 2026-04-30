import json
import shutil
from pathlib import Path

import pytest

from hpa_meshing.tail_wing_mesh_handoff_smoke import (
    build_tail_wing_mesh_handoff_smoke_report,
    write_tail_wing_mesh_handoff_smoke_report,
)


def test_tail_wing_mesh_handoff_smoke_writes_real_non_bl_handoff(tmp_path: Path):
    if shutil.which("gmsh") is None:
        pytest.skip("gmsh CLI not available")

    report = build_tail_wing_mesh_handoff_smoke_report(tmp_path / "smoke")

    assert report.schema_version == "tail_wing_mesh_handoff_smoke.v1"
    assert report.component == "tail_wing"
    assert report.meshing_route == "gmsh_thin_sheet_surface"
    assert report.no_su2_execution is True
    assert report.no_bl_runtime is True
    assert report.production_default_changed is False
    assert report.smoke_status == "mesh_handoff_pass"
    assert report.mesh_handoff_status == "written"
    assert report.mesh_contract == "mesh_handoff.v1"
    assert report.marker_summary_status == "component_wall_and_farfield_present"
    assert report.wall_marker_status == "tail_wing_marker_present"
    assert report.su2_promotion_status == "blocked_before_su2_handoff"
    assert report.volume_element_count > 0
    assert "tail_wing_specific_force_marker_present" in report.hpa_mdo_guarantees


def test_tail_wing_mesh_handoff_smoke_writer_outputs_json_and_markdown(tmp_path: Path):
    if shutil.which("gmsh") is None:
        pytest.skip("gmsh CLI not available")

    paths = write_tail_wing_mesh_handoff_smoke_report(tmp_path / "smoke")

    assert set(paths) == {"json", "markdown"}
    payload = json.loads(paths["json"].read_text(encoding="utf-8"))
    markdown = paths["markdown"].read_text(encoding="utf-8")

    assert payload["smoke_status"] == "mesh_handoff_pass"
    assert payload["mesh_contract"] == "mesh_handoff.v1"
    assert payload["no_su2_execution"] is True
    assert "tail_wing" in markdown
    assert "mesh_handoff.v1" in markdown
