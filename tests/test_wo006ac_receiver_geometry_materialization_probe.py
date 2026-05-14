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


SCRIPT_PATH = REPO_ROOT / "scripts" / "probe_wo006ac_receiver_geometry_materialization.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("wo006ac_probe", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _simple_block(layer_count: int = 2):
    stations = [
        Station(
            y=-0.5,
            airfoil_xz=[
                (1.0, 0.05),
                (0.0, 0.05),
                (0.0, -0.05),
                (1.0, -0.05),
            ],
            chord=1.0,
            twist_deg=0.0,
        ),
        Station(
            y=0.5,
            airfoil_xz=[
                (1.0, 0.05),
                (0.0, 0.05),
                (0.0, -0.05),
                (1.0, -0.05),
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


def test_tip_receiver_geometry_materializes_virtual_nodes_with_positive_volumes() -> None:
    module = _load_module()
    block = _simple_block(layer_count=2)

    materialized = module.materialize_tip_receiver_geometry(block)
    summary = module.summarize_materialized_tip_receiver(block, materialized)
    probe = module.build_probe_summary(receiver_geometry=summary)

    assert summary["status"] == "tip_receiver_geometry_materialized_quality_pass"
    assert summary["tip_receiver_cell_count"] == 20
    assert summary["matched_bl_span_cap_face_count"] == 20
    assert summary["remaining_bl_span_cap_face_count"] == 0
    assert summary["virtual_node_count"] > 0
    assert summary["receiver_thickness_m"] > 0.0
    assert summary["non_positive_volume_count"] == 0
    assert summary["min_receiver_volume_m3"] > 0.0
    assert summary["external_shape_changed"] is False
    assert probe["verdict"] == "receiver_geometry_materialized_not_handoff"
    assert probe["goal_status"] == "INCOMPLETE"
    assert probe["cfd_status"] == "mesh_ladder_incomplete"
    assert probe["coefficient_interpretable"] is False


def test_receiver_geometry_probe_run_writes_baseline_a_artifacts(tmp_path: Path) -> None:
    module = _load_module()

    summary = module.run_probe(
        output_dir=tmp_path / "wo006ac",
        points_per_side=8,
        spanwise_subdivisions=1,
    )

    assert summary["verdict"] == "receiver_geometry_materialized_not_handoff"
    assert summary["receiver_geometry"]["status"] == "tip_receiver_geometry_materialized_quality_pass"
    assert summary["receiver_geometry"]["non_positive_volume_count"] == 0
    assert summary["receiver_geometry"]["min_receiver_volume_m3"] > 0.0
    assert summary["topology_accounting"]["status"] == "topology_receiver_geometry_ready_mesh_pending"
    assert "receiver_geometry_not_materialized" not in summary["topology_accounting"]["blockers"]
    assert "final_merged_mesh_missing" in summary["receiver_geometry"]["blockers"]
    assert (tmp_path / "wo006ac" / "summary.json").exists()
    assert (tmp_path / "wo006ac" / "receiver_geometry_report.md").exists()
