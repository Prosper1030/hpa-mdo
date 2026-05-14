from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "probe_wo006q_transition_normal_jump.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("wo006q_probe", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_summary_blocks_large_transition_aft_normal_jump() -> None:
    module = _load_module()

    summary = module.summarize_interval_metrics(
        [
            {
                "interval_id": "safe",
                "is_airfoil_transition": False,
                "max_aft_normal_angle_deg": 2.0,
                "max_aft_shape_delta_xz": 0.001,
            },
            {
                "interval_id": "transition",
                "is_airfoil_transition": True,
                "max_aft_normal_angle_deg": 45.0,
                "max_aft_shape_delta_xz": 0.055,
            },
        ]
    )

    assert summary["status"] == "blocked"
    assert "airfoil_transition_aft_normal_jump" in summary["blockers"]
    assert summary["worst_transition_interval"]["interval_id"] == "transition"
    assert summary["recommended_repair"] == "receiver_sleeve_or_local_airfoil_transition_smoothing"


def test_summary_passes_when_transition_jump_is_below_thresholds() -> None:
    module = _load_module()

    summary = module.summarize_interval_metrics(
        [
            {
                "interval_id": "transition",
                "is_airfoil_transition": True,
                "max_aft_normal_angle_deg": 8.0,
                "max_aft_shape_delta_xz": 0.005,
            }
        ]
    )

    assert summary["status"] == "pass"
    assert summary["blockers"] == []
    assert summary["recommended_repair"] == "none"
