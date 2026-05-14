from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "probe_wo006p_bl_span_refinement_runtime.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("wo006p_probe", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_span_refinement_summary_requires_quality_pass_before_candidate() -> None:
    module = _load_module()

    summary = module.build_probe_summary(
        [
            {
                "case_id": "span8",
                "status": "meshed",
                "gate_status": "fail",
                "blockers": ["boundary_layer_severe_low_p01_min_sicn"],
            },
            {
                "case_id": "span16",
                "status": "timeout",
                "failure_code": "local_timeout",
                "peak_sampled_rss_kb": 210_000,
                "elapsed_seconds": 420.0,
            },
        ]
    )

    assert summary["verdict"] == "span_refinement_runtime_limited_no_bl_gate_pass"
    assert summary["candidate_case_ids"] == []
    assert "span16" in summary["runtime_limited_case_ids"]
    assert summary["engineering_read"].startswith("Spanwise refinement has not cleared")


def test_span_refinement_summary_promotes_only_gate_passed_case() -> None:
    module = _load_module()

    summary = module.build_probe_summary(
        [
            {
                "case_id": "span8",
                "status": "meshed",
                "gate_status": "pass",
                "blockers": [],
            },
            {
                "case_id": "span16",
                "status": "meshed",
                "gate_status": "fail",
                "blockers": ["boundary_layer_non_positive_min_sicn"],
            },
        ]
    )

    assert summary["verdict"] == "span_refinement_bl_gate_candidate_found"
    assert summary["candidate_case_ids"] == ["span8"]
    assert "span16" not in summary["candidate_case_ids"]
