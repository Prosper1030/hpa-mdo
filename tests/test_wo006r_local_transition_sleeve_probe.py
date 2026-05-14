from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "probe_wo006r_local_transition_sleeve_bl_quality.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("wo006r_probe", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_local_sleeve_summary_requires_bl_quality_pass() -> None:
    module = _load_module()

    summary = module.build_probe_summary(
        [
            {
                "case_id": "local4",
                "status": "meshed",
                "gate_status": "fail",
                "blockers": ["boundary_layer_non_positive_min_sicn"],
            },
            {
                "case_id": "local8",
                "status": "timeout",
                "failure_code": "local_timeout",
            },
        ]
    )

    assert summary["verdict"] == "local_transition_sleeve_no_bl_gate_pass"
    assert summary["candidate_case_ids"] == []
    assert summary["goal_status"] == "INCOMPLETE"


def test_local_sleeve_summary_promotes_quality_pass_candidate() -> None:
    module = _load_module()

    summary = module.build_probe_summary(
        [
            {
                "case_id": "local8",
                "status": "meshed",
                "gate_status": "pass",
                "blockers": [],
                "external_shape_changed": False,
            }
        ]
    )

    assert summary["verdict"] == "local_transition_sleeve_bl_gate_candidate_found"
    assert summary["candidate_case_ids"] == ["local8"]
