from __future__ import annotations

import importlib.util
import math
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "run_wo006_current_go_cfd_completion.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("wo006_current_go_cfd_completion", SCRIPT_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["wo006_current_go_cfd_completion"] = module
    spec.loader.exec_module(module)
    return module


def _candidate(**patch):
    payload = {
        "run_status": "completed",
        "returncode": 0,
        "history": {
            "final_iteration": 159,
            "final_coefficients": {"cl": 1.28, "cd": 0.55},
            "final_residuals": {"rms[P]": -1.5, "rms[U]": -0.2},
        },
        "mesh_report": {
            "mesh_quality_gate": {"status": "pass", "blockers": []},
            "quality_metrics": {
                "non_positive_volume_count": 0,
                "non_positive_min_sicn_count": 0,
                "non_positive_min_sige_count": 0,
                "ill_shaped_volume_element_count": 0,
            },
        },
        "marker_audit": {
            "status": "pass",
            "missing_from_mesh": [],
            "mesh_summary": {
                "nmark": 2,
                "markers": {
                    "wing_wall": {"element_count": 10},
                    "farfield": {"element_count": 12},
                },
            },
        },
    }
    payload.update(patch)
    return payload


def test_completion_gate_accepts_finite_100_iteration_current_go_evidence() -> None:
    module = _load_module()

    gate = module.evaluate_completion_gate(_candidate(), minimum_iterations=100)

    assert gate["status"] == "pass"
    assert gate["su2_iterations_completed"] == 159
    assert gate["cl"] == 1.28
    assert gate["cd"] == 0.55
    assert gate["nan_inf_status"] == "pass"


def test_completion_gate_rejects_nan_force_or_insufficient_iteration() -> None:
    module = _load_module()

    nan_case = _candidate(
        history={
            "final_iteration": 159,
            "final_coefficients": {"cl": math.nan, "cd": 0.55},
            "final_residuals": {"rms[P]": -1.5},
        }
    )
    short_case = _candidate(
        history={
            "final_iteration": 99,
            "final_coefficients": {"cl": 1.28, "cd": 0.55},
            "final_residuals": {"rms[P]": -1.5},
        }
    )

    assert "non_finite_cl" in module.evaluate_completion_gate(nan_case)["blockers"]
    assert "su2_iterations_below_minimum" in module.evaluate_completion_gate(short_case)["blockers"]


def test_completion_gate_rejects_marker_and_quality_failures() -> None:
    module = _load_module()

    marker_fail = _candidate(
        marker_audit={
            "status": "fail",
            "missing_from_mesh": ["farfield"],
            "mesh_summary": {"nmark": 1, "markers": {"wing_wall": {"element_count": 10}}},
        }
    )
    quality_fail = _candidate(
        mesh_report={
            "mesh_quality_gate": {"status": "fail", "blockers": ["non_positive_volume"]},
            "quality_metrics": {"non_positive_volume_count": 1},
        }
    )

    assert "mesh_marker_audit_not_pass" in module.evaluate_completion_gate(marker_fail)["blockers"]
    assert "mesh_quality_gate_not_pass" in module.evaluate_completion_gate(quality_fail)["blockers"]
