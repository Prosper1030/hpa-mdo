import json
from pathlib import Path

from hpa_meshing.main_wing_station_seam_repair_decision import (
    build_main_wing_station_seam_repair_decision_report,
    write_main_wing_station_seam_repair_decision_report,
)


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def _write_fixture(path: Path) -> Path:
    return _write_json(
        path,
        {
            "topology_fixture_status": "real_defect_station_fixture_materialized",
            "fixture_summary": {
                "station_fixture_count": 2,
                "total_boundary_edge_count": 4,
                "total_nonmanifold_edge_count": 2,
                "candidate_curve_tags": [36, 50],
                "source_section_indices": [3, 4],
                "all_cases_violate_canonical_station_topology_contract": True,
            },
            "station_fixture_cases": [
                {
                    "defect_station_y_m": -10.5,
                    "source_section_index": 3,
                    "canonical_station_topology_contract": {
                        "current_signature_violates_contract": True,
                    },
                }
            ],
        },
    )


def _write_solver(path: Path) -> Path:
    return _write_json(
        path,
        {
            "solver_execution_status": "solver_executed",
            "convergence_gate_status": "fail",
            "run_status": "solver_executed_but_not_converged",
            "observed_velocity_mps": 6.5,
            "main_wing_lift_acceptance_status": "fail",
            "minimum_acceptable_cl": 1.0,
            "final_coefficients": {"cl": 0.263161913, "cd": 0.02496911575},
        },
    )


def test_station_seam_repair_decision_blocks_more_solver_budget_when_fixture_violates_contract(
    tmp_path: Path,
):
    report = build_main_wing_station_seam_repair_decision_report(
        topology_fixture_path=_write_fixture(tmp_path / "fixture.json"),
        solver_report_path=_write_solver(tmp_path / "solver.json"),
    )

    assert report.repair_decision_status == (
        "station_seam_repair_required_before_solver_budget"
    )
    assert report.production_default_changed is False
    assert report.topology_fixture_observed["total_boundary_edge_count"] == 4
    assert report.solver_context_observed["observed_velocity_mps"] == 6.5
    assert report.solver_context_observed["main_wing_lift_acceptance_status"] == "fail"
    assert "station_topology_contract_violated_by_real_fixture" in (
        report.decision_rationale
    )
    assert "solver_budget_is_not_primary_next_gate_while_station_fixture_fails" in (
        report.decision_rationale
    )
    assert report.repair_candidate_requirements[0] == (
        "eliminate_boundary_and_nonmanifold_edges_at_station_curve_tags_36_50"
    )
    assert report.next_actions[0] == (
        "prototype_station_seam_repair_against_minimal_fixture"
    )


def test_write_station_seam_repair_decision_report(tmp_path: Path):
    written = write_main_wing_station_seam_repair_decision_report(
        tmp_path / "out",
        topology_fixture_path=_write_fixture(tmp_path / "fixture.json"),
        solver_report_path=_write_solver(tmp_path / "solver.json"),
    )

    payload = json.loads(written["json"].read_text(encoding="utf-8"))
    markdown = written["markdown"].read_text(encoding="utf-8")
    assert payload["schema_version"] == "main_wing_station_seam_repair_decision.v1"
    assert payload["repair_decision_status"] == (
        "station_seam_repair_required_before_solver_budget"
    )
    assert "Main Wing Station Seam Repair Decision v1" in markdown
