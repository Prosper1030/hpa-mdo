from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "probe_wo006t_te_stageback_runtime.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("wo006t_probe", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_stageback_failure_classifier_records_hxt_triangle_limit() -> None:
    module = _load_module()

    failure = module.classify_stageback_failure(
        "Surface 1556 contains 48 elements which are not triangles. "
        "The HXT 3D meshing algorithm only supports triangles."
    )

    assert failure == "stageback_hxt_requires_triangle_boundary_surfaces"


def test_stageback_summary_rejects_failed_hxt_and_alg1_cases() -> None:
    module = _load_module()

    summary = module.build_probe_summary(
        [
            {
                "case_id": "global_te_xc099_hxt",
                "status": "failed",
                "failure_code": "stageback_hxt_requires_triangle_boundary_surfaces",
                "external_shape_changed": False,
            },
            {
                "case_id": "global_te_xc099_alg1",
                "status": "failed",
                "failure_code": "stageback_boundary_recovery_failed",
                "external_shape_changed": False,
            },
        ]
    )

    assert summary["verdict"] == "te_stageback_no_bl_gate_pass"
    assert summary["candidate_case_ids"] == []
    assert summary["failure_families"] == [
        "stageback_boundary_recovery_failed",
        "stageback_hxt_requires_triangle_boundary_surfaces",
    ]
    assert summary["cfd_status"] == "mesh_ladder_incomplete"


def test_stageback_summary_promotes_only_quality_pass_candidate() -> None:
    module = _load_module()

    summary = module.build_probe_summary(
        [
            {
                "case_id": "global_te_xc099_alg1",
                "status": "meshed",
                "gate_status": "pass",
                "external_shape_changed": False,
            },
            {
                "case_id": "global_te_xc099_hxt",
                "status": "failed",
                "failure_code": "stageback_hxt_requires_triangle_boundary_surfaces",
                "external_shape_changed": False,
            },
        ]
    )

    assert summary["verdict"] == "te_stageback_bl_gate_candidate_found"
    assert summary["candidate_case_ids"] == ["global_te_xc099_alg1"]
