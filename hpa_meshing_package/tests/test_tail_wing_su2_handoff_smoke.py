import json
import shutil
from pathlib import Path

import pytest

from hpa_meshing.tail_wing_su2_handoff_smoke import (
    build_tail_wing_su2_handoff_smoke_report,
    write_tail_wing_su2_handoff_smoke_report,
)


def test_tail_wing_su2_handoff_smoke_materializes_without_running_solver(
    tmp_path: Path,
):
    if shutil.which("gmsh") is None:
        pytest.skip("gmsh CLI not available")

    report = build_tail_wing_su2_handoff_smoke_report(tmp_path / "smoke")

    assert report.schema_version == "tail_wing_su2_handoff_smoke.v1"
    assert report.component == "tail_wing"
    assert report.no_su2_execution is True
    assert report.production_default_changed is False
    assert report.materialization_status == "su2_handoff_written"
    assert report.su2_contract == "su2_handoff.v1"
    assert report.input_mesh_contract == "mesh_handoff.v1"
    assert report.solver_execution_status == "not_run"
    assert report.convergence_gate_status == "not_run"
    assert report.run_status == "not_started"
    assert report.wall_marker_status == "tail_wing_marker_present"
    assert report.force_surface_scope == "component_subset"
    assert report.component_force_ownership_status == "owned"
    assert report.reference_geometry_status == "pass"
    assert report.su2_handoff_path is not None
    assert Path(report.su2_handoff_path).exists()
    assert Path(report.su2_mesh_path).exists()
    assert Path(report.runtime_cfg_path).exists()
    runtime_cfg = Path(report.runtime_cfg_path).read_text(encoding="utf-8")
    assert "MARKER_MONITORING= ( tail_wing )" in runtime_cfg
    assert "MARKER_FAR= ( farfield )" in runtime_cfg
    assert "tail_wing_component_force_marker_missing" not in report.blocking_reasons
    assert "convergence_gate_not_run" in report.blocking_reasons
    assert "tail_wing_force_marker_owned" in report.hpa_mdo_guarantees


def test_tail_wing_su2_handoff_smoke_writer_outputs_json_and_markdown(
    tmp_path: Path,
):
    if shutil.which("gmsh") is None:
        pytest.skip("gmsh CLI not available")

    paths = write_tail_wing_su2_handoff_smoke_report(tmp_path / "smoke")

    assert set(paths) == {"json", "markdown"}
    payload = json.loads(paths["json"].read_text(encoding="utf-8"))
    markdown = paths["markdown"].read_text(encoding="utf-8")

    assert payload["materialization_status"] == "su2_handoff_written"
    assert payload["solver_execution_status"] == "not_run"
    assert payload["component_force_ownership_status"] == "owned"
    assert "tail_wing" in markdown
    assert "su2_handoff.v1" in markdown
