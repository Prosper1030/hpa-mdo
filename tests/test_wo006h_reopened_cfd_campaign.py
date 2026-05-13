from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "run_wo006h_reopened_cfd_campaign.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("wo006h_reopened", SCRIPT_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["wo006h_reopened"] = module
    spec.loader.exec_module(module)
    return module


def test_reopened_verdict_requires_targeted_hpc_missing_cases() -> None:
    module = _load_module()
    attempts = [
        {
            "attempt_id": "no_bl_h_0p055",
            "route": "current_go_mesh_native_no_bl_hxt_scaling",
            "status": "meshed",
            "mesh_size": 0.055,
            "volume_element_count": 3_790_657,
            "boundary_layer_present": False,
        },
        {
            "attempt_id": "no_bl_h_0p05",
            "status": "failed",
            "mesh_size": 0.05,
            "mesh_algorithm3d": 10,
            "error": "HXT 3D mesh failed",
        },
        {
            "attempt_id": "no_bl_h_0p04_alg1_delaunay",
            "status": "failed",
            "mesh_size": 0.04,
            "mesh_algorithm3d": 1,
            "error": "Invalid boundary mesh (overlapping facets)",
        },
        {
            "attempt_id": "attempt_full_bl_boundary_core_preserve_alg1_h1p0",
            "status": "failed",
            "elapsed_seconds": 325.0,
            "error": "PLC Error: A segment and a facet intersect at point",
        },
        {
            "attempt_id": "core_preserve_interface_alg1_h1p0_900s",
            "status": "timeout",
            "timeout_seconds": 900.0,
        },
    ]

    assert (
        module.classify_reopened_verdict(
            attempts=attempts,
            hpc_case_ids={
                "mesh_h004_hxt",
                "mesh_h004_delaunay",
                "mesh_h005_hxt",
                "bl_core_preserve_alg1_32x2",
                "bl_core_preserve_alg10_32x2",
            },
        )
        == "su2_local_hard_limit_proven_with_executable_hpc_case"
    )


def test_reopened_verdict_rejects_package_that_only_reruns_successful_no_bl_mesh() -> None:
    module = _load_module()

    assert (
        module.classify_reopened_verdict(
            attempts=[
                {
                    "attempt_id": "no_bl_h_0p055",
                    "status": "meshed",
                    "mesh_size": 0.055,
                    "volume_element_count": 3_790_657,
                    "boundary_layer_present": False,
                },
                {
                    "attempt_id": "core_preserve_interface_alg1_h1p0_900s",
                    "status": "timeout",
                    "timeout_seconds": 900.0,
                },
            ],
            hpc_case_ids={"mesh_h0055_hxt"},
        )
        == "campaign_incomplete_not_acceptable"
    )
