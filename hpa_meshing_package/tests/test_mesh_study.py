from __future__ import annotations

import json
from pathlib import Path

from hpa_meshing.mesh_study import build_default_mesh_study_presets, evaluate_mesh_study, run_mesh_study
from hpa_meshing.schema import MeshJobConfig, MeshStudyCaseResult, SU2RuntimeConfig


def _case(
    tmp_path: Path,
    *,
    name: str,
    tier: str,
    node_count: int,
    element_count: int,
    volume_element_count: int,
    near_body_size: float,
    farfield_size: float,
    cl: float,
    cd: float,
    cm: float,
    convergence_status: str,
    comparability_level: str,
) -> MeshStudyCaseResult:
    case_dir = tmp_path / name
    case_dir.mkdir(parents=True, exist_ok=True)
    report_path = case_dir / "report.json"
    report_path.write_text("{}", encoding="utf-8")
    history_path = case_dir / "history.csv"
    history_path.write_text("Inner_Iter,CL,CD,CMy\n49,0.0,0.0,0.0\n", encoding="utf-8")
    return MeshStudyCaseResult.model_validate(
        {
            "preset": {
                "name": name,
                "tier": tier,
                "characteristic_length_policy": "body_max_span",
                "near_body_factor": near_body_size / 10.0,
                "farfield_factor": farfield_size / 10.0,
                "near_body_size": near_body_size,
                "farfield_size": farfield_size,
                "runtime": {
                    "max_iterations": 50,
                    "cfl_number": 3.0,
                },
            },
            "out_dir": case_dir,
            "report_path": report_path,
            "status": "success",
            "mesh": {
                "mesh_dim": 3,
                "node_count": node_count,
                "element_count": element_count,
                "surface_element_count": max(node_count // 2, 1),
                "volume_element_count": volume_element_count,
                "characteristic_length": 10.0,
                "near_body_size": near_body_size,
                "farfield_size": farfield_size,
            },
            "cfd": {
                "case_name": f"alpha_0_{name}",
                "history_path": history_path,
                "final_iteration": 49,
                "cl": cl,
                "cd": cd,
                "cm": cm,
                "cm_axis": "CMy",
            },
            "convergence_gate": {
                "contract": "convergence_gate.v1",
                "mesh_gate": {
                    "status": "pass",
                    "confidence": "high",
                    "checks": {},
                    "warnings": [],
                    "notes": [],
                },
                "iterative_gate": {
                    "status": convergence_status,
                    "confidence": "medium",
                    "checks": {},
                    "warnings": [],
                    "notes": [],
                },
                "overall_convergence_gate": {
                    "status": convergence_status,
                    "confidence": "medium",
                    "comparability_level": comparability_level,
                    "checks": {},
                    "warnings": [],
                    "notes": [],
                },
            },
            "overall_convergence_status": convergence_status,
            "comparability_level": comparability_level,
        }
    )


def test_evaluate_mesh_study_promotes_to_preliminary_compare_when_medium_fine_are_tight(
    tmp_path: Path,
):
    cases = [
        _case(
            tmp_path,
            name="coarse",
            tier="coarse",
            node_count=1500,
            element_count=8000,
            volume_element_count=6500,
            near_body_size=1.10,
            farfield_size=4.50,
            cl=0.0345,
            cd=0.0292,
            cm=-0.0128,
            convergence_status="warn",
            comparability_level="run_only",
        ),
        _case(
            tmp_path,
            name="medium",
            tier="medium",
            node_count=2800,
            element_count=15000,
            volume_element_count=12000,
            near_body_size=0.80,
            farfield_size=3.50,
            cl=0.0358,
            cd=0.0289,
            cm=-0.0126,
            convergence_status="warn",
            comparability_level="run_only",
        ),
        _case(
            tmp_path,
            name="fine",
            tier="fine",
            node_count=4700,
            element_count=25500,
            volume_element_count=21000,
            near_body_size=0.60,
            farfield_size=2.70,
            cl=0.0360,
            cd=0.0287,
            cm=-0.0125,
            convergence_status="pass",
            comparability_level="preliminary_compare",
        ),
    ]

    comparison, verdict = evaluate_mesh_study(cases)

    assert comparison.mesh_hierarchy.status == "pass"
    assert comparison.coefficient_spread["medium_fine"].status == "pass"
    assert verdict.verdict == "preliminary_compare"
    assert verdict.comparability_level == "preliminary_compare"


def test_evaluate_mesh_study_stays_run_only_when_cases_finish_but_gates_do_not_improve(
    tmp_path: Path,
):
    cases = [
        _case(
            tmp_path,
            name="coarse",
            tier="coarse",
            node_count=1500,
            element_count=8000,
            volume_element_count=6500,
            near_body_size=1.10,
            farfield_size=4.50,
            cl=0.0345,
            cd=0.0292,
            cm=-0.0128,
            convergence_status="warn",
            comparability_level="run_only",
        ),
        _case(
            tmp_path,
            name="medium",
            tier="medium",
            node_count=2800,
            element_count=15000,
            volume_element_count=12000,
            near_body_size=0.80,
            farfield_size=3.50,
            cl=0.0350,
            cd=0.0288,
            cm=-0.0127,
            convergence_status="warn",
            comparability_level="run_only",
        ),
        _case(
            tmp_path,
            name="fine",
            tier="fine",
            node_count=4700,
            element_count=25500,
            volume_element_count=21000,
            near_body_size=0.60,
            farfield_size=2.70,
            cl=0.0352,
            cd=0.0286,
            cm=-0.0126,
            convergence_status="warn",
            comparability_level="run_only",
        ),
    ]

    comparison, verdict = evaluate_mesh_study(cases)

    assert comparison.mesh_hierarchy.status == "pass"
    assert comparison.convergence_progress.status == "warn"
    assert verdict.verdict == "still_run_only"
    assert verdict.comparability_level == "run_only"


def test_evaluate_mesh_study_marks_non_monotonic_mesh_tiers_as_insufficient(tmp_path: Path):
    cases = [
        _case(
            tmp_path,
            name="coarse",
            tier="coarse",
            node_count=2200,
            element_count=14000,
            volume_element_count=11000,
            near_body_size=1.10,
            farfield_size=4.50,
            cl=0.0345,
            cd=0.0292,
            cm=-0.0128,
            convergence_status="warn",
            comparability_level="run_only",
        ),
        _case(
            tmp_path,
            name="medium",
            tier="medium",
            node_count=1800,
            element_count=12000,
            volume_element_count=9000,
            near_body_size=0.80,
            farfield_size=3.50,
            cl=0.0350,
            cd=0.0288,
            cm=-0.0127,
            convergence_status="warn",
            comparability_level="run_only",
        ),
        _case(
            tmp_path,
            name="fine",
            tier="fine",
            node_count=4700,
            element_count=25500,
            volume_element_count=21000,
            near_body_size=0.60,
            farfield_size=2.70,
            cl=0.0352,
            cd=0.0286,
            cm=-0.0126,
            convergence_status="pass",
            comparability_level="preliminary_compare",
        ),
    ]

    comparison, verdict = evaluate_mesh_study(cases)

    assert comparison.mesh_hierarchy.status == "fail"
    assert verdict.verdict == "insufficient"
    assert verdict.comparability_level == "not_comparable"


def test_run_mesh_study_executes_default_presets_and_writes_machine_readable_report(
    tmp_path: Path,
    monkeypatch,
):
    geometry = tmp_path / "assembly.vsp3"
    geometry.write_text("<vsp3/>", encoding="utf-8")
    called = []

    def fake_run_job(config: MeshJobConfig):
        called.append(
            {
                "out_dir": config.out_dir,
                "near_body_size": config.global_min_size,
                "farfield_size": config.global_max_size,
                "max_iterations": config.su2.max_iterations,
                "cfl_number": config.su2.cfl_number,
                "linear_solver_error": config.su2.linear_solver_error,
                "linear_solver_iterations": config.su2.linear_solver_iterations,
            }
        )
        rank = {"coarse": 1, "medium": 2, "fine": 3}[config.out_dir.name]
        convergence_status = "pass" if config.out_dir.name == "fine" else "warn"
        comparability_level = "preliminary_compare" if config.out_dir.name == "fine" else "run_only"
        return {
            "status": "success",
            "failure_code": None,
            "mesh": {
                "node_count": 1000 * rank,
                "element_count": 6000 * rank,
                "surface_element_count": 1200 * rank,
                "volume_element_count": 4800 * rank,
                "mesh_dim": 3,
                "metadata_path": str(config.out_dir / "artifacts" / "mesh" / "mesh_metadata.json"),
            },
            "su2": {
                "history_path": str(config.out_dir / "artifacts" / "su2" / "history.csv"),
                "final_coefficients": {
                    "cl": 0.035 + 0.0003 * rank,
                    "cd": 0.029 - 0.0001 * rank,
                    "cm": -0.013 + 0.0001 * rank,
                    "cm_axis": "CMy",
                },
                "convergence_gate": {
                    "contract": "convergence_gate.v1",
                    "mesh_gate": {
                        "status": "pass",
                        "confidence": "high",
                        "checks": {},
                        "warnings": [],
                        "notes": [],
                    },
                    "iterative_gate": {
                        "status": convergence_status,
                        "confidence": "medium",
                        "checks": {},
                        "warnings": [],
                        "notes": [],
                    },
                    "overall_convergence_gate": {
                        "status": convergence_status,
                        "confidence": "medium",
                        "comparability_level": comparability_level,
                        "checks": {},
                        "warnings": [],
                        "notes": [],
                    },
                },
            },
        }

    monkeypatch.setattr("hpa_meshing.mesh_study._resolve_characteristic_length", lambda config: 10.0)
    monkeypatch.setattr("hpa_meshing.mesh_study.run_job", fake_run_job)

    presets = build_default_mesh_study_presets(10.0)
    result = run_mesh_study(
        MeshJobConfig(
            component="aircraft_assembly",
            geometry=geometry,
            out_dir=tmp_path / "study",
            geometry_provider="openvsp_surface_intersection",
            su2=SU2RuntimeConfig(
                enabled=True,
                case_name="alpha_0_baseline",
                linear_solver_error=1e-4,
                linear_solver_iterations=3,
            ),
        )
    )

    assert [entry["out_dir"].name for entry in called] == ["coarse", "medium", "fine"]
    assert called[0]["near_body_size"] > called[1]["near_body_size"] > called[2]["near_body_size"]
    assert called[0]["farfield_size"] > called[1]["farfield_size"] > called[2]["farfield_size"]
    assert [entry["linear_solver_error"] for entry in called] == [
        preset.runtime.linear_solver_error for preset in presets
    ]
    assert [entry["linear_solver_iterations"] for entry in called] == [
        preset.runtime.linear_solver_iterations for preset in presets
    ]
    assert result["contract"] == "mesh_study.v1"
    assert result["verdict"]["verdict"] == "preliminary_compare"

    report = json.loads((tmp_path / "study" / "report.json").read_text(encoding="utf-8"))
    assert report["comparison"]["completed_case_count"] == 3
    assert report["cases"][0]["preset"]["name"] == "coarse"
