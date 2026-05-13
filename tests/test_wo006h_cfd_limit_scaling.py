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


def test_classify_verdict_does_not_promote_single_timeout_to_hard_limit() -> None:
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
        == "wo006h_campaign_incomplete_needs_more_scaling"
    )
    assert (
        module.classify_verdict(
            no_bl_attempts=[{"status": "meshed", "volume_element_count": 1_500_000}],
            core_attempts=[{"status": "timeout"}],
        )
        == "wo006h_serious_no_bl_scaling_only_not_cfd_result"
    )


def test_no_bl_attempt_records_selected_gmsh_3d_algorithm() -> None:
    module = _load_module()

    attempt = module.NoBlMeshAttempt(
        attempt_id="no_bl_h_0p04_alg1",
        mesh_size=0.04,
        farfield_mesh_size=4.0,
        wing_refinement_radius=6.0,
        feature_refinement_size=0.12,
        timeout_seconds=900.0,
        mesh_algorithm3d=1,
    )

    assert attempt.mesh_algorithm3d == 1


def test_hpc_package_targets_failed_finer_and_bl_routes(tmp_path: Path) -> None:
    module = _load_module()

    module.write_hpc_package(tmp_path)

    case_matrix = (tmp_path / "case_matrix.csv").read_text(encoding="utf-8")
    run_script = (tmp_path / "run_hpc_campaign.sh").read_text(encoding="utf-8")
    slurm_script = (tmp_path / "slurm_wo006h_mesh_ladder.sbatch").read_text(encoding="utf-8")

    assert "mesh_h005_hxt" in case_matrix
    assert "mesh_h004_hxt" in case_matrix
    assert "mesh_h004_delaunay" in case_matrix
    assert "bl_core_preserve_alg1_32x2" in case_matrix
    assert "--mesh-sizes 0.04" in run_script
    assert "--no-bl-mesh-algorithm3d 1" in run_script
    assert "CORE_TIMEOUT_SECONDS" in run_script
    assert '--hpc-package-dir "$PACKAGE_DIR"' in run_script
    assert 'CORE_TIMEOUT_SECONDS="${CORE_TIMEOUT_SECONDS:-7200}"' in slurm_script
    assert "hpc_escalation_package" not in run_script
    assert "hpc_escalation_package" not in slurm_script
