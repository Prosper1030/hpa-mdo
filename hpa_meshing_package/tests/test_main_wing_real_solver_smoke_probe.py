import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

from hpa_meshing.main_wing_real_solver_smoke_probe import (
    build_main_wing_real_solver_smoke_probe_report,
    write_main_wing_real_solver_smoke_probe_report,
)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _write_source_su2_probe(tmp_path: Path) -> Path:
    case_dir = tmp_path / "su2_case"
    case_dir.mkdir()
    (case_dir / "su2_runtime.cfg").write_text("MESH_FILENAME= mesh.su2\n", encoding="utf-8")
    (case_dir / "mesh.su2").write_text("NDIME= 3\n", encoding="utf-8")
    _write_json(
        case_dir / "su2_handoff.json",
        {
            "contract": "su2_handoff.v1",
            "runtime": {"velocity_mps": 6.5},
            "runtime_cfg_path": str(case_dir / "su2_runtime.cfg"),
            "case_output_paths": {
                "case_dir": str(case_dir),
                "history": str(case_dir / "history.csv"),
                "solver_log": str(case_dir / "solver.log"),
                "contract_path": str(case_dir / "su2_handoff.json"),
            },
            "provenance_gates": {
                "reference_quantities": {"status": "warn"},
                "force_surface": {"status": "pass"},
            },
        },
    )
    mesh_case_report = tmp_path / "real_mesh_case" / "report.json"
    _write_json(
        mesh_case_report,
        {
            "mesh_handoff": {
                "contract": "mesh_handoff.v1",
                "geometry_family": "thin_sheet_lifting_surface",
                "artifacts": {"mesh": "mesh.msh"},
            }
        },
    )
    probe_path = tmp_path / "main_wing_real_su2_handoff_probe.v1.json"
    _write_json(
        probe_path,
        {
            "schema_version": "main_wing_real_su2_handoff_probe.v1",
            "component": "main_wing",
            "materialization_status": "su2_handoff_written",
            "case_dir": str(case_dir),
            "runtime_cfg_path": str(case_dir / "su2_runtime.cfg"),
            "su2_handoff_path": str(case_dir / "su2_handoff.json"),
            "history_path": str(case_dir / "history.csv"),
            "source_mesh_case_report_path": str(mesh_case_report),
            "component_force_ownership_status": "owned",
            "reference_geometry_status": "warn",
            "observed_velocity_mps": 6.5,
            "volume_element_count": 584460,
            "blocking_reasons": [
                "main_wing_solver_not_run",
                "convergence_gate_not_run",
                "main_wing_real_reference_geometry_warn",
            ],
        },
    )
    return probe_path


def _history_text() -> str:
    return "\n".join(
        [
            '"Inner_Iter","rms[Rho]","rms[U]","CL","CD","CMy"',
            "0,-1.0,-1.1,0.10,0.020,0.001",
            "1,-1.2,-1.2,0.15,0.030,0.002",
            "2,-1.3,-1.25,0.30,0.080,0.006",
        ]
    ) + "\n"


def test_main_wing_real_solver_smoke_probe_records_executed_nonconverged_solver(
    tmp_path: Path,
    monkeypatch,
):
    probe_path = _write_source_su2_probe(tmp_path)

    monkeypatch.setattr(
        "hpa_meshing.main_wing_real_solver_smoke_probe.shutil.which",
        lambda command: f"/fake/bin/{command}",
    )

    def fake_run(command, cwd, stdout, stderr, text, check, timeout, env):
        assert command == ["SU2_CFD", "-t", "4", "su2_runtime.cfg"]
        assert cwd == tmp_path / "su2_case"
        assert timeout == 12.0
        stdout.write("fake SU2 completed\n")
        (Path(cwd) / "history.csv").write_text(_history_text(), encoding="utf-8")
        (Path(cwd) / "restart.csv").write_text("large restart\n", encoding="utf-8")
        (Path(cwd) / "surface.csv").write_text("large surface\n", encoding="utf-8")
        (Path(cwd) / "vol_solution.vtk").write_text("large volume\n", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(
        "hpa_meshing.main_wing_real_solver_smoke_probe.subprocess.run",
        fake_run,
    )
    monkeypatch.setattr(
        "hpa_meshing.main_wing_real_solver_smoke_probe.evaluate_baseline_convergence_gate",
        lambda mesh_handoff, **kwargs: SimpleNamespace(
            overall_convergence_gate=SimpleNamespace(
                status="fail",
                comparability_level="not_comparable",
            ),
            model_dump=lambda mode="json": {
                "contract": "convergence_gate.v1",
                "overall_convergence_gate": {
                    "status": "fail",
                    "comparability_level": "not_comparable",
                },
            },
        ),
    )

    report = build_main_wing_real_solver_smoke_probe_report(
        tmp_path / "solver_probe",
        source_su2_probe_report_path=probe_path,
        timeout_seconds=12.0,
    )

    assert report.schema_version == "main_wing_real_solver_smoke_probe.v1"
    assert report.solver_execution_status == "solver_executed"
    assert report.convergence_gate_status == "fail"
    assert report.run_status == "solver_executed_but_not_converged"
    assert report.final_iteration == 2
    assert report.final_coefficients["cl"] == 0.30
    assert report.observed_velocity_mps == 6.5
    assert report.component_force_ownership_status == "owned"
    assert report.reference_geometry_status == "warn"
    assert "solver_executed_but_not_converged" in report.blocking_reasons
    assert "hpa_standard_flow_conditions_6p5_mps" in report.hpa_mdo_guarantees
    assert "heavy_solver_outputs_pruned" in report.hpa_mdo_guarantees
    assert len(report.pruned_output_paths) == 3
    assert not (tmp_path / "su2_case" / "restart.csv").exists()
    assert not (tmp_path / "su2_case" / "surface.csv").exists()
    assert not (tmp_path / "su2_case" / "vol_solution.vtk").exists()
    assert report.production_default_changed is False


def test_main_wing_real_solver_smoke_probe_records_solver_timeout(
    tmp_path: Path,
    monkeypatch,
):
    probe_path = _write_source_su2_probe(tmp_path)

    monkeypatch.setattr(
        "hpa_meshing.main_wing_real_solver_smoke_probe.shutil.which",
        lambda command: f"/fake/bin/{command}",
    )

    def fake_timeout(command, **kwargs):
        raise subprocess.TimeoutExpired(command, timeout=3.0)

    monkeypatch.setattr(
        "hpa_meshing.main_wing_real_solver_smoke_probe.subprocess.run",
        fake_timeout,
    )

    report = build_main_wing_real_solver_smoke_probe_report(
        tmp_path / "solver_probe",
        source_su2_probe_report_path=probe_path,
        timeout_seconds=3.0,
    )

    assert report.solver_execution_status == "solver_timeout"
    assert report.convergence_gate_status == "not_run"
    assert report.run_status == "solver_timeout"
    assert "main_wing_solver_timeout" in report.blocking_reasons
    assert "convergence_gate_not_run" in report.blocking_reasons


def test_main_wing_real_solver_smoke_probe_blocks_without_solver_binary(
    tmp_path: Path,
    monkeypatch,
):
    probe_path = _write_source_su2_probe(tmp_path)

    monkeypatch.setattr(
        "hpa_meshing.main_wing_real_solver_smoke_probe.shutil.which",
        lambda command: None,
    )

    report = build_main_wing_real_solver_smoke_probe_report(
        tmp_path / "solver_probe",
        source_su2_probe_report_path=probe_path,
    )

    assert report.solver_execution_status == "solver_unavailable"
    assert report.convergence_gate_status == "not_run"
    assert report.run_status == "solver_executable_missing"
    assert "su2_solver_executable_missing" in report.blocking_reasons


def test_main_wing_real_solver_smoke_probe_writer_outputs_json_and_markdown(
    tmp_path: Path,
    monkeypatch,
):
    probe_path = _write_source_su2_probe(tmp_path)
    monkeypatch.setattr(
        "hpa_meshing.main_wing_real_solver_smoke_probe.shutil.which",
        lambda command: None,
    )

    paths = write_main_wing_real_solver_smoke_probe_report(
        tmp_path / "solver_probe",
        source_su2_probe_report_path=probe_path,
    )

    payload = json.loads(paths["json"].read_text(encoding="utf-8"))
    markdown = paths["markdown"].read_text(encoding="utf-8")

    assert payload["solver_execution_status"] == "solver_unavailable"
    assert payload["observed_velocity_mps"] == 6.5
    assert "main_wing real solver smoke probe" in markdown
    assert "solver_executable_missing" in markdown
