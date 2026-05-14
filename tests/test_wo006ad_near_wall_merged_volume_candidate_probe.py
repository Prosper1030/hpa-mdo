from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
HPA_MESHING_SRC = REPO_ROOT / "hpa_meshing_package" / "src"
if str(HPA_MESHING_SRC) not in sys.path:
    sys.path.insert(0, str(HPA_MESHING_SRC))

from hpa_meshing.mesh_native.near_wall_block import (  # noqa: E402
    BoundaryLayerBlockSpec,
    build_wing_boundary_layer_block,
)
from hpa_meshing.mesh_native.wing_surface import Reference, Station, WingSpec  # noqa: E402


SCRIPT_PATH = REPO_ROOT / "scripts" / "probe_wo006ad_near_wall_merged_volume_candidate.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("wo006ad_probe", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _sharp_te_block(layer_count: int = 2):
    stations = [
        Station(
            y=-0.5,
            airfoil_xz=[
                (1.0, 0.0),
                (0.5, 0.05),
                (0.0, 0.05),
                (0.0, -0.05),
                (0.5, -0.05),
                (1.0, 0.0),
            ],
            chord=1.0,
            twist_deg=0.0,
        ),
        Station(
            y=0.5,
            airfoil_xz=[
                (1.0, 0.0),
                (0.5, 0.05),
                (0.0, 0.05),
                (0.0, -0.05),
                (0.5, -0.05),
                (1.0, 0.0),
            ],
            chord=1.0,
            twist_deg=0.0,
        ),
    ]
    spec = WingSpec(
        stations=stations,
        side="full",
        te_rule="finite_thickness",
        tip_rule="planar_cap",
        root_rule="full",
        reference=Reference(sref_full=1.0, cref=1.0, bref_full=1.0),
    )
    return build_wing_boundary_layer_block(
        spec,
        BoundaryLayerBlockSpec(
            first_layer_height_m=0.01,
            growth_ratio=1.2,
            layer_count=layer_count,
            te_wake_length_m=0.2,
        ),
    )


def test_near_wall_candidate_internalizes_span_caps_and_stitches_sharp_te_wake() -> None:
    module = _load_module()
    block = _sharp_te_block(layer_count=2)

    candidate = module.build_near_wall_merged_volume_candidate(block)
    summary = module.summarize_near_wall_merged_volume_candidate(block, candidate)
    probe = module.build_probe_summary(merged_volume=summary)

    assert summary["status"] == "near_wall_volume_candidate_ready_core_mesh_pending"
    assert summary["owned_bl_cell_count"] == len(block.cells)
    assert summary["tip_receiver_cell_count"] > 0
    assert summary["wake_receiver_cell_count"] > 0
    assert summary["remaining_exposed_original_span_cap_face_count"] == 0
    assert summary["remaining_exposed_original_wake_cut_face_count"] == 0
    assert summary["te_base_stitched_face_count"] > 0
    assert summary["degenerate_receiver_base_removed_face_count"] > 0
    assert "receiver_base" not in summary["boundary_face_role_counts"]
    assert "final_merged_mesh_missing" not in summary["blockers"]
    assert "core_farfield_mesh_not_generated" in summary["blockers"]
    assert probe["goal_status"] == "INCOMPLETE"
    assert probe["cfd_status"] == "mesh_ladder_incomplete"
    assert probe["coefficient_interpretable"] is False


def test_near_wall_candidate_probe_run_writes_artifacts(tmp_path: Path) -> None:
    module = _load_module()

    summary = module.run_probe(
        output_dir=tmp_path / "wo006ad",
        points_per_side=8,
        spanwise_subdivisions=1,
    )

    assert summary["verdict"] == "near_wall_volume_candidate_ready_not_su2_handoff"
    assert summary["merged_volume"]["status"] == "near_wall_volume_candidate_ready_core_mesh_pending"
    assert summary["merged_volume"]["remaining_exposed_original_span_cap_face_count"] == 0
    assert summary["merged_volume"]["remaining_exposed_original_wake_cut_face_count"] == 0
    assert "receiver_base" not in summary["merged_volume"]["boundary_face_role_counts"]
    assert "final_merged_mesh_missing" not in summary["merged_volume"]["blockers"]
    assert "core_farfield_mesh_not_generated" in summary["merged_volume"]["blockers"]
    assert (tmp_path / "wo006ad" / "summary.json").exists()
    assert (tmp_path / "wo006ad" / "near_wall_merged_volume_report.md").exists()
