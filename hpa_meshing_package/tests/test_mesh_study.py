from __future__ import annotations

import json
from pathlib import Path

import pytest

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
                "characteristic_length_policy": "reference_length",
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


def test_evaluate_mesh_study_uses_absolute_cm_tolerance_for_near_zero_pitching_moment(
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
            cl=0.02433915373,
            cd=0.03351685049,
            cm=-0.003245134559,
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
            cl=0.03478908784,
            cd=0.03078336339,
            cm=-0.01123460302,
            convergence_status="pass",
            comparability_level="preliminary_compare",
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
            cl=0.03153145365,
            cd=0.02925969757,
            cm=-0.007360669653,
            convergence_status="pass",
            comparability_level="preliminary_compare",
        ),
    ]

    comparison, verdict = evaluate_mesh_study(cases)

    medium_fine = comparison.coefficient_spread["medium_fine"]
    assert medium_fine.status == "pass"
    assert medium_fine.observed["cl_relative_range"] == pytest.approx(0.09363954021968987)
    assert medium_fine.observed["cm_absolute_range"] == pytest.approx(0.0038739333670000005)
    assert medium_fine.expected["cl_relative_range_threshold"] == pytest.approx(0.10)
    assert medium_fine.expected["cm_absolute_tolerance"] == pytest.approx(0.005)
    assert "cm_relative_range_above_threshold" not in medium_fine.warnings
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


def test_build_default_mesh_study_presets_biases_surface_refinement_by_reference_length():
    presets = {preset.name: preset for preset in build_default_mesh_study_presets(1.0425)}

    assert presets["coarse"].characteristic_length_policy == "reference_length"
    assert presets["coarse"].near_body_factor == pytest.approx(1.0 / 64.0)
    assert presets["medium"].near_body_factor == pytest.approx(1.0 / 96.0)
    assert presets["fine"].near_body_factor == pytest.approx(1.0 / 128.0)
    assert presets["super-fine"].near_body_factor == pytest.approx(1.0 / 160.0)
    assert presets["coarse"].farfield_factor == pytest.approx(6.0)
    assert presets["medium"].farfield_factor == pytest.approx(5.0)
    assert presets["fine"].farfield_factor == pytest.approx(4.0)
    assert presets["super-fine"].farfield_factor == pytest.approx(3.5)
    assert presets["coarse"].near_body_size == pytest.approx(1.0425 / 64.0)
    assert presets["medium"].near_body_size == pytest.approx(1.0425 / 96.0)
    assert presets["fine"].near_body_size == pytest.approx(1.0425 / 128.0)
    assert presets["super-fine"].near_body_size == pytest.approx(1.0425 / 160.0)
    assert presets["coarse"].runtime.max_iterations == 80
    assert presets["medium"].runtime.max_iterations == 160
    assert presets["fine"].runtime.max_iterations == 180
    assert presets["super-fine"].runtime.max_iterations == 180
    assert presets["coarse"].runtime.cfl_number == pytest.approx(2.0)
    assert presets["medium"].runtime.cfl_number == pytest.approx(1.5)
    assert presets["fine"].runtime.cfl_number == pytest.approx(1.25)
    assert presets["super-fine"].runtime.cfl_number == pytest.approx(1.25)


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
        rank = {"coarse": 1, "medium": 2, "fine": 3, "super-fine": 4}[config.out_dir.name]
        convergence_status = "pass" if config.out_dir.name in {"fine", "super-fine"} else "warn"
        comparability_level = "preliminary_compare" if config.out_dir.name in {"fine", "super-fine"} else "run_only"
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

    monkeypatch.setattr("hpa_meshing.mesh_study._resolve_reference_length", lambda config: 1.0425)
    monkeypatch.setattr("hpa_meshing.mesh_study.run_job", fake_run_job)

    presets = build_default_mesh_study_presets(1.0425)
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

    assert [entry["out_dir"].name for entry in called] == ["coarse", "medium", "fine", "super-fine"]
    assert (
        called[0]["near_body_size"]
        > called[1]["near_body_size"]
        > called[2]["near_body_size"]
        > called[3]["near_body_size"]
    )
    assert (
        called[0]["farfield_size"]
        > called[1]["farfield_size"]
        > called[2]["farfield_size"]
        > called[3]["farfield_size"]
    )
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
    assert report["comparison"]["case_order"] == ["coarse", "medium", "fine"]
    assert report["cases"][0]["preset"]["name"] == "coarse"
    assert report["cases"][-1]["preset"]["name"] == "super-fine"


def test_run_mesh_study_keeps_base_verdict_when_super_fine_diagnostic_case_fails(
    tmp_path: Path,
    monkeypatch,
):
    geometry = tmp_path / "assembly.vsp3"
    geometry.write_text("<vsp3/>", encoding="utf-8")

    def fake_run_job(config: MeshJobConfig):
        if config.out_dir.name == "super-fine":
            return {
                "status": "failed",
                "failure_code": "quality_gate_failed",
                "mesh": {},
                "su2": {
                    "final_coefficients": {
                        "cl": None,
                        "cd": None,
                        "cm": None,
                        "cm_axis": None,
                    }
                },
            }

        rank = {"coarse": 1, "medium": 2, "fine": 3}[config.out_dir.name]
        convergence_status = "pass" if config.out_dir.name in {"medium", "fine"} else "warn"
        comparability_level = "preliminary_compare" if config.out_dir.name in {"medium", "fine"} else "run_only"
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
                    "cl": 0.02433915373 if config.out_dir.name == "coarse" else (0.03478908784 if config.out_dir.name == "medium" else 0.03153145365),
                    "cd": 0.03351685049 if config.out_dir.name == "coarse" else (0.03078336339 if config.out_dir.name == "medium" else 0.02925969757),
                    "cm": -0.003245134559 if config.out_dir.name == "coarse" else (-0.01123460302 if config.out_dir.name == "medium" else -0.007360669653),
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

    monkeypatch.setattr("hpa_meshing.mesh_study._resolve_reference_length", lambda config: 1.0425)
    monkeypatch.setattr("hpa_meshing.mesh_study.run_job", fake_run_job)

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

    assert result["verdict"]["verdict"] == "preliminary_compare"
    assert result["comparison"]["expected_case_count"] == 3
    assert result["comparison"]["completed_case_count"] == 3
    assert result["comparison"]["case_order"] == ["coarse", "medium", "fine"]
    assert result["warnings"] == ["diagnostic_case_failed:super-fine"]
    assert result["cases"][-1]["preset"]["name"] == "super-fine"
    assert result["cases"][-1]["status"] == "failed"
