from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "run_wo006h_cfd_limit_scaling.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("run_wo006h_cfd_limit_scaling", SCRIPT_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["run_wo006h_cfd_limit_scaling"] = module
    spec.loader.exec_module(module)
    return module


def test_required_cl_uses_current_authority_values() -> None:
    module = _load_module()

    assert module.required_cl() == pytest.approx(1.11697, rel=1e-4)


def test_classify_verdict_requires_serious_scaling_before_hard_limit() -> None:
    module = _load_module()

    assert (
        module.classify_verdict(
            no_bl_attempts=[{"status": "meshed", "volume_element_count": 1_500_000}],
            core_attempts=[
                {
                    "status": "meshed",
                    "boundary_layer_present": True,
                    "mesh_quality_status": "pass",
                    "can_merge_core_with_bl_block": False,
                    "unmatched_core_interface_face_count": 158,
                    "unmatched_bl_boundary_face_count": 4672,
                }
            ],
        )
        == "wo006h_serious_no_bl_scaling_only_not_cfd_result"
    )
    assert (
        module.classify_verdict(
            no_bl_attempts=[{"status": "meshed", "volume_element_count": 936017}],
            core_attempts=[{"status": "timeout"}],
        )
        == "wo006h_campaign_incomplete_needs_more_scaling"
    )
    assert (
        module.classify_verdict(
            no_bl_attempts=[{"status": "timeout", "mesh_size": 0.10}],
            core_attempts=[{"status": "timeout"}],
        )
        == "wo006h_hard_limit_escalation_package_ready_after_serious_scaling"
    )
    assert (
        module.classify_verdict(
            no_bl_attempts=[{"status": "meshed", "volume_element_count": 1_500_000}],
            core_attempts=[{"status": "timeout"}],
        )
        == "wo006h_hard_limit_escalation_package_ready_after_serious_scaling"
    )
