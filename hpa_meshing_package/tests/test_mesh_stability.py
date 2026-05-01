import pytest

from hpa_meshing.mesh_native.mesh_stability import select_cheapest_stable_mesh


def test_select_cheapest_stable_mesh_chooses_coarser_case_from_first_stable_pair():
    cases = [
        {
            "case_name": "coarse",
            "volume_element_count": 100_000,
            "history": {
                "final_coefficients": {
                    "cl": 0.50,
                    "cd": 0.040,
                    "cmy": -0.100,
                }
            },
        },
        {
            "case_name": "medium",
            "volume_element_count": 220_000,
            "history": {
                "final_coefficients": {
                    "cl": 0.620,
                    "cd": 0.045,
                    "cmy": -0.130,
                }
            },
        },
        {
            "case_name": "fine",
            "volume_element_count": 480_000,
            "history": {
                "final_coefficients": {
                    "cl": 0.626,
                    "cd": 0.046,
                    "cmy": -0.132,
                }
            },
        },
    ]

    result = select_cheapest_stable_mesh(
        cases,
        coefficient_tolerances={"cl": 0.01, "cd": 0.002, "cmy": 0.005},
    )

    assert result["status"] == "stable_pair_found"
    assert result["selected_case"]["case_name"] == "medium"
    assert result["compared_to_case"]["case_name"] == "fine"
    assert result["comparisons"][0]["status"] == "unstable"
    assert result["comparisons"][1]["status"] == "stable"
    assert result["comparisons"][1]["deltas"] == pytest.approx(
        {"cl": 0.006, "cd": 0.001, "cmy": 0.002}
    )


def test_select_cheapest_stable_mesh_accepts_cm_tolerance_for_cmy_history_key():
    cases = [
        {
            "case_name": "medium",
            "volume_element_count": 220_000,
            "history": {
                "final_coefficients": {
                    "cl": 0.620,
                    "cd": 0.045,
                    "cmy": -0.130,
                }
            },
        },
        {
            "case_name": "fine",
            "volume_element_count": 480_000,
            "history": {
                "final_coefficients": {
                    "cl": 0.626,
                    "cd": 0.046,
                    "cmy": -0.132,
                }
            },
        },
    ]

    result = select_cheapest_stable_mesh(
        cases,
        coefficient_tolerances={"cl": 0.01, "cd": 0.002, "cm": 0.005},
    )

    assert result["status"] == "stable_pair_found"
    assert result["selected_case"]["case_name"] == "medium"
    assert result["comparison"]["deltas"] == pytest.approx(
        {"cl": 0.006, "cd": 0.001, "cm": 0.002}
    )


def test_select_cheapest_stable_mesh_can_require_successful_case_gates():
    cases = [
        {
            "case_name": "coarse_failed",
            "volume_element_count": 100_000,
            "run_status": "failed",
            "returncode": 1,
            "mesh_quality_gate": {"status": "pass"},
            "marker_audit": {"status": "pass"},
            "history": {"final_coefficients": {"cl": 0.50, "cd": 0.040, "cmy": -0.100}},
        },
        {
            "case_name": "medium",
            "volume_element_count": 220_000,
            "run_status": "completed",
            "returncode": 0,
            "mesh_quality_gate": {"status": "pass"},
            "marker_audit": {"status": "pass"},
            "history": {"final_coefficients": {"cl": 0.620, "cd": 0.045, "cmy": -0.130}},
        },
        {
            "case_name": "fine",
            "volume_element_count": 480_000,
            "run_status": "completed",
            "returncode": 0,
            "mesh_quality_gate": {"status": "pass"},
            "marker_audit": {"status": "pass"},
            "history": {"final_coefficients": {"cl": 0.626, "cd": 0.046, "cmy": -0.132}},
        },
    ]

    result = select_cheapest_stable_mesh(
        cases,
        coefficient_tolerances={"cl": 0.01, "cd": 0.002, "cm": 0.005},
        require_successful_case_gates=True,
    )

    assert result["status"] == "stable_pair_found"
    assert result["selected_case"]["case_name"] == "medium"
    assert result["ineligible_cases"] == [
        {
            "case_name": "coarse_failed",
            "volume_element_count": 100_000,
            "reasons": ["run_status_not_completed", "returncode_nonzero"],
        }
    ]


def test_select_cheapest_stable_mesh_can_require_iterative_gate_pass():
    cases = [
        {
            "case_name": "coarse_unconverged",
            "volume_element_count": 100_000,
            "run_status": "completed",
            "returncode": 0,
            "mesh_quality_gate": {"status": "pass"},
            "marker_audit": {"status": "pass"},
            "iterative_gate_status": "fail",
            "history": {"final_coefficients": {"cl": 0.50, "cd": 0.040, "cmy": -0.100}},
        },
        {
            "case_name": "medium",
            "volume_element_count": 220_000,
            "run_status": "completed",
            "returncode": 0,
            "mesh_quality_gate": {"status": "pass"},
            "marker_audit": {"status": "pass"},
            "iterative_gate_status": "pass",
            "history": {"final_coefficients": {"cl": 0.620, "cd": 0.045, "cmy": -0.130}},
        },
        {
            "case_name": "fine",
            "volume_element_count": 480_000,
            "run_status": "completed",
            "returncode": 0,
            "mesh_quality_gate": {"status": "pass"},
            "marker_audit": {"status": "pass"},
            "iterative_gate_status": "pass",
            "history": {"final_coefficients": {"cl": 0.626, "cd": 0.046, "cmy": -0.132}},
        },
    ]

    result = select_cheapest_stable_mesh(
        cases,
        coefficient_tolerances={"cl": 0.01, "cd": 0.002, "cm": 0.005},
        require_successful_case_gates=True,
        require_iterative_gate_pass=True,
    )

    assert result["status"] == "stable_pair_found"
    assert result["selected_case"]["case_name"] == "medium"
    assert result["ineligible_cases"] == [
        {
            "case_name": "coarse_unconverged",
            "volume_element_count": 100_000,
            "reasons": ["iterative_gate_not_pass"],
        }
    ]


def test_select_cheapest_stable_mesh_can_reject_negative_drag():
    cases = [
        {
            "case_name": "coarse_negative_drag",
            "volume_element_count": 100_000,
            "run_status": "completed",
            "returncode": 0,
            "mesh_quality_gate": {"status": "pass"},
            "marker_audit": {"status": "pass"},
            "iterative_gate_status": "pass",
            "history": {"final_coefficients": {"cl": 0.50, "cd": -0.040, "cmy": -0.100}},
        },
        {
            "case_name": "medium",
            "volume_element_count": 220_000,
            "run_status": "completed",
            "returncode": 0,
            "mesh_quality_gate": {"status": "pass"},
            "marker_audit": {"status": "pass"},
            "iterative_gate_status": "pass",
            "history": {"final_coefficients": {"cl": 0.620, "cd": 0.045, "cmy": -0.130}},
        },
        {
            "case_name": "fine",
            "volume_element_count": 480_000,
            "run_status": "completed",
            "returncode": 0,
            "mesh_quality_gate": {"status": "pass"},
            "marker_audit": {"status": "pass"},
            "iterative_gate_status": "pass",
            "history": {"final_coefficients": {"cl": 0.626, "cd": 0.046, "cmy": -0.132}},
        },
    ]

    result = select_cheapest_stable_mesh(
        cases,
        coefficient_tolerances={"cl": 0.01, "cd": 0.002, "cm": 0.005},
        require_successful_case_gates=True,
        require_iterative_gate_pass=True,
        require_coefficient_sanity=True,
    )

    assert result["status"] == "stable_pair_found"
    assert result["selected_case"]["case_name"] == "medium"
    assert result["ineligible_cases"] == [
        {
            "case_name": "coarse_negative_drag",
            "volume_element_count": 100_000,
            "reasons": ["negative_cd"],
        }
    ]


def test_select_cheapest_stable_mesh_can_require_cfd_evidence_gate_pass():
    cases = [
        {
            "case_name": "coarse_short_run",
            "volume_element_count": 100_000,
            "run_status": "completed",
            "returncode": 0,
            "mesh_quality_gate": {"status": "pass"},
            "marker_audit": {"status": "pass"},
            "iterative_gate_status": "pass",
            "cfd_evidence_gate": {
                "status": "fail",
                "reasons": ["iteration_budget_below_cfd_evidence_minimum"],
            },
            "history": {"final_coefficients": {"cl": 0.50, "cd": 0.040, "cmy": -0.100}},
        },
        {
            "case_name": "medium",
            "volume_element_count": 220_000,
            "run_status": "completed",
            "returncode": 0,
            "mesh_quality_gate": {"status": "pass"},
            "marker_audit": {"status": "pass"},
            "iterative_gate_status": "pass",
            "cfd_evidence_gate": {"status": "pass", "reasons": []},
            "history": {"final_coefficients": {"cl": 0.620, "cd": 0.045, "cmy": -0.130}},
        },
        {
            "case_name": "fine",
            "volume_element_count": 480_000,
            "run_status": "completed",
            "returncode": 0,
            "mesh_quality_gate": {"status": "pass"},
            "marker_audit": {"status": "pass"},
            "iterative_gate_status": "pass",
            "cfd_evidence_gate": {"status": "pass", "reasons": []},
            "history": {"final_coefficients": {"cl": 0.626, "cd": 0.046, "cmy": -0.132}},
        },
    ]

    result = select_cheapest_stable_mesh(
        cases,
        coefficient_tolerances={"cl": 0.01, "cd": 0.002, "cm": 0.005},
        require_successful_case_gates=True,
        require_iterative_gate_pass=True,
        require_coefficient_sanity=True,
        require_cfd_evidence_gate_pass=True,
    )

    assert result["status"] == "stable_pair_found"
    assert result["selected_case"]["case_name"] == "medium"
    assert result["ineligible_cases"] == [
        {
            "case_name": "coarse_short_run",
            "volume_element_count": 100_000,
            "reasons": ["cfd_evidence_gate_not_pass"],
        }
    ]
