import json
from pathlib import Path
from types import SimpleNamespace

from hpa_meshing.fairing_solid_real_mesh_handoff_probe import (
    FairingSolidRealMeshHandoffProbeReport,
)
from hpa_meshing.fairing_solid_real_su2_handoff_probe import (
    build_fairing_solid_real_su2_handoff_probe_report,
    write_fairing_solid_real_su2_handoff_probe_report,
)


def _write_mesh_probe_report(
    tmp_path: Path,
    *,
    probe_status: str = "mesh_handoff_pass",
    mesh_handoff_status: str = "written",
) -> Path:
    case_dir = tmp_path / "real_mesh_case"
    case_dir.mkdir()
    (case_dir / "report.json").write_text(
        json.dumps({"mesh_handoff": {"contract": "mesh_handoff.v1"}}) + "\n",
        encoding="utf-8",
    )
    report = FairingSolidRealMeshHandoffProbeReport(
        source_path="fairing.vsp3",
        case_dir=str(case_dir),
        probe_status=probe_status,
        mesh_probe_status="completed",
        mesh_handoff_status=mesh_handoff_status,
        provider_status="materialized",
        marker_summary_status="component_wall_and_farfield_present",
        fairing_force_marker_status="component_specific_marker_present",
        bounded_probe_timeout_seconds=1.0,
        node_count=29394,
        element_count=173122,
        volume_element_count=153251,
    )
    report_path = tmp_path / "fairing_solid_real_mesh_handoff_probe.v1.json"
    report_path.write_text(
        json.dumps(report.model_dump(mode="json"), indent=2) + "\n",
        encoding="utf-8",
    )
    return report_path


def _fake_case(case_root: Path, *, wall_marker: str = "fairing_solid"):
    case_dir = case_root / "alpha_0_real_fairing_materialization_probe"
    case_dir.mkdir(parents=True)
    contract_path = case_dir / "su2_handoff.json"
    su2_mesh = case_dir / "mesh.su2"
    runtime_cfg = case_dir / "su2_runtime.cfg"
    history = case_dir / "history.csv"
    contract_path.write_text('{"contract":"su2_handoff.v1"}\n', encoding="utf-8")
    su2_mesh.write_text("NDIME= 3\n", encoding="utf-8")
    runtime_cfg.write_text("MESH_FILENAME= mesh.su2\n", encoding="utf-8")
    return SimpleNamespace(
        contract="su2_handoff.v1",
        provenance={"source_contract": "mesh_handoff.v1"},
        force_surface_provenance=SimpleNamespace(
            wall_marker=wall_marker,
            scope="component_subset" if wall_marker == "fairing_solid" else "whole_aircraft_wall",
        ),
        convergence_gate=None,
        run_status="not_started",
        reference_geometry=SimpleNamespace(gate_status="warn"),
        input_mesh_artifact=Path("mesh.msh"),
        runtime_cfg_path=runtime_cfg,
        case_output_paths=SimpleNamespace(
            case_dir=case_dir,
            contract_path=contract_path,
            su2_mesh=su2_mesh,
            history=history,
        ),
    )


def test_fairing_solid_real_su2_handoff_probe_materializes_from_real_mesh_probe(
    tmp_path: Path,
    monkeypatch,
):
    probe_path = _write_mesh_probe_report(tmp_path)

    def fake_materialize(mesh_handoff, runtime, case_root, source_root=None):
        assert mesh_handoff["contract"] == "mesh_handoff.v1"
        assert runtime.reference_mode == "geometry_derived"
        return _fake_case(case_root)

    monkeypatch.setattr(
        "hpa_meshing.fairing_solid_real_su2_handoff_probe.materialize_baseline_case",
        fake_materialize,
    )

    report = build_fairing_solid_real_su2_handoff_probe_report(
        tmp_path / "su2_probe",
        source_mesh_probe_report_path=probe_path,
    )

    assert report.schema_version == "fairing_solid_real_su2_handoff_probe.v1"
    assert report.materialization_status == "su2_handoff_written"
    assert report.source_mesh_probe_status == "mesh_handoff_pass"
    assert report.source_mesh_handoff_status == "written"
    assert report.su2_contract == "su2_handoff.v1"
    assert report.input_mesh_contract == "mesh_handoff.v1"
    assert report.solver_execution_status == "not_run"
    assert report.convergence_gate_status == "not_run"
    assert report.wall_marker_status == "fairing_solid_marker_present"
    assert report.force_surface_scope == "component_subset"
    assert report.component_force_ownership_status == "owned"
    assert report.reference_geometry_status == "warn"
    assert report.production_default_changed is False
    assert "fairing_real_geometry_su2_handoff_not_run" not in report.blocking_reasons
    assert "fairing_solver_not_run" in report.blocking_reasons
    assert "convergence_gate_not_run" in report.blocking_reasons
    assert "fairing_real_reference_geometry_warn" in report.blocking_reasons
    assert "real_fairing_mesh_handoff_v1_consumed" in report.hpa_mdo_guarantees
    assert "su2_handoff_v1_written_for_real_fairing" in report.hpa_mdo_guarantees
    assert "fairing_solid_force_marker_owned" in report.hpa_mdo_guarantees


def test_fairing_solid_real_su2_handoff_probe_blocks_when_real_mesh_handoff_missing(
    tmp_path: Path,
):
    probe_path = _write_mesh_probe_report(
        tmp_path,
        probe_status="mesh_handoff_blocked",
        mesh_handoff_status="missing",
    )

    report = build_fairing_solid_real_su2_handoff_probe_report(
        tmp_path / "su2_probe",
        source_mesh_probe_report_path=probe_path,
    )

    assert report.materialization_status == "blocked_before_su2_handoff"
    assert report.su2_contract is None
    assert report.component_force_ownership_status == "insufficient_evidence"
    assert "fairing_real_mesh_handoff_not_available" in report.blocking_reasons
    assert "fairing_real_su2_handoff_not_materialized" in report.blocking_reasons


def test_fairing_solid_real_su2_handoff_probe_resolves_packaged_report_relative_paths(
    tmp_path: Path,
    monkeypatch,
):
    report_dir = tmp_path / "hpa_meshing_package" / "docs" / "reports" / "fairing_probe"
    case_dir = report_dir / "artifacts" / "real_mesh_probe"
    mesh_dir = case_dir / "artifacts" / "mesh"
    mesh_dir.mkdir(parents=True)
    (mesh_dir / "mesh.msh").write_text("$MeshFormat\n", encoding="utf-8")
    (case_dir / "report.json").write_text(
        json.dumps(
            {
                "mesh_handoff": {
                    "contract": "mesh_handoff.v1",
                    "artifacts": {
                        "mesh": "docs/reports/fairing_probe/artifacts/real_mesh_probe/artifacts/mesh/mesh.msh"
                    },
                }
            }
        )
        + "\n",
        encoding="utf-8",
    )
    probe = FairingSolidRealMeshHandoffProbeReport(
        source_path="fairing.vsp3",
        case_dir="docs/reports/fairing_probe/artifacts/real_mesh_probe",
        probe_status="mesh_handoff_pass",
        mesh_probe_status="completed",
        mesh_handoff_status="written",
        provider_status="materialized",
        marker_summary_status="component_wall_and_farfield_present",
        fairing_force_marker_status="component_specific_marker_present",
        bounded_probe_timeout_seconds=1.0,
    )
    probe_path = report_dir / "fairing_solid_real_mesh_handoff_probe.v1.json"
    probe_path.write_text(
        json.dumps(probe.model_dump(mode="json"), indent=2) + "\n",
        encoding="utf-8",
    )

    def fake_materialize(mesh_handoff, runtime, case_root, source_root=None):
        assert source_root == tmp_path / "hpa_meshing_package"
        return _fake_case(case_root)

    monkeypatch.setattr(
        "hpa_meshing.fairing_solid_real_su2_handoff_probe.materialize_baseline_case",
        fake_materialize,
    )

    report = build_fairing_solid_real_su2_handoff_probe_report(
        tmp_path / "su2_probe",
        source_mesh_probe_report_path=probe_path,
    )

    assert report.materialization_status == "su2_handoff_written"
    assert report.source_mesh_case_report_path == str(case_dir / "report.json")


def test_fairing_solid_real_su2_handoff_probe_records_missing_component_force_marker(
    tmp_path: Path,
    monkeypatch,
):
    probe_path = _write_mesh_probe_report(tmp_path)

    def fake_materialize(mesh_handoff, runtime, case_root, source_root=None):
        return _fake_case(case_root, wall_marker="aircraft")

    monkeypatch.setattr(
        "hpa_meshing.fairing_solid_real_su2_handoff_probe.materialize_baseline_case",
        fake_materialize,
    )

    report = build_fairing_solid_real_su2_handoff_probe_report(
        tmp_path / "su2_probe",
        source_mesh_probe_report_path=probe_path,
    )

    assert report.materialization_status == "su2_handoff_written"
    assert report.wall_marker_status == "generic_aircraft_wall_present"
    assert report.component_force_ownership_status == "missing"
    assert "fairing_solid_component_force_marker_missing" in report.blocking_reasons
    assert "fairing_solid_force_marker_owned" not in report.hpa_mdo_guarantees


def test_fairing_solid_real_su2_handoff_probe_writer_outputs_json_and_markdown(
    tmp_path: Path,
    monkeypatch,
):
    probe_path = _write_mesh_probe_report(tmp_path)

    monkeypatch.setattr(
        "hpa_meshing.fairing_solid_real_su2_handoff_probe.materialize_baseline_case",
        lambda mesh_handoff, runtime, case_root, source_root=None: _fake_case(case_root),
    )

    paths = write_fairing_solid_real_su2_handoff_probe_report(
        tmp_path / "su2_probe",
        source_mesh_probe_report_path=probe_path,
    )

    assert set(paths) == {"json", "markdown"}
    payload = json.loads(paths["json"].read_text(encoding="utf-8"))
    markdown = paths["markdown"].read_text(encoding="utf-8")

    assert payload["materialization_status"] == "su2_handoff_written"
    assert payload["source_mesh_probe_status"] == "mesh_handoff_pass"
    assert payload["solver_execution_status"] == "not_run"
    assert "fairing_solid real su2_handoff probe" in markdown
    assert "su2_handoff.v1" in markdown
