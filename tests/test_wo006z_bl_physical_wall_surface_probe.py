from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "probe_wo006z_bl_physical_wall_surface.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("wo006z_probe", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_wall_probe_summary_does_not_promote_physical_wall_basis_to_cfd() -> None:
    module = _load_module()

    summary = module.build_probe_summary(
        wall_surface={
            "status": "watertight",
            "marker_counts": {"wing_wall": 260},
            "source_wing_wall_face_count": 220,
            "tip_cap_face_count": 40,
            "te_base_face_count": 0,
            "sharp_te_seam_pair_count": 11,
        }
    )

    assert summary["verdict"] == "bl_physical_wall_basis_ready_not_handoff"
    assert summary["goal_status"] == "INCOMPLETE"
    assert summary["cfd_status"] == "mesh_ladder_incomplete"
    assert summary["coefficient_interpretable"] is False
    assert "medium/fine CFD ladder readiness" in summary["blocked_claims"]


def test_wall_probe_run_writes_baseline_a_surface_ownership_artifacts(tmp_path: Path) -> None:
    module = _load_module()

    summary = module.run_probe(
        output_dir=tmp_path / "wo006z",
        points_per_side=8,
        spanwise_subdivisions=1,
    )

    assert summary["verdict"] == "bl_physical_wall_basis_ready_not_handoff"
    assert summary["physical_wall_surface"]["status"] == "watertight"
    assert summary["physical_wall_surface"]["marker_counts"]["wing_wall"] > 0
    assert summary["physical_wall_surface"]["source_wing_wall_face_count"] > 0
    assert summary["physical_wall_surface"]["tip_cap_face_count"] > 0
    assert summary["owned_bl_block"]["boundary_marker_counts"]["span_cap"] > 0
    assert (tmp_path / "wo006z" / "summary.json").exists()
    assert (tmp_path / "wo006z" / "surface_ownership_report.md").exists()
