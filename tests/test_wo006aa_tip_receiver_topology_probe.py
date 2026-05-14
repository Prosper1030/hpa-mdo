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


SCRIPT_PATH = REPO_ROOT / "scripts" / "probe_wo006aa_tip_receiver_topology.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("wo006aa_probe", SCRIPT_PATH)
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


def test_tip_receiver_accounts_every_bl_span_cap_face_without_cfd_promotion() -> None:
    module = _load_module()
    block = _simple_block(layer_count=2)

    tip_receiver = module.summarize_tip_receiver_topology(block)
    probe = module.build_probe_summary(tip_receiver)

    assert tip_receiver["bl_span_cap_face_count"] == 20
    assert tip_receiver["matched_bl_span_cap_face_count"] == 20
    assert tip_receiver["remaining_bl_span_cap_face_count"] == 0
    assert tip_receiver["tip_receiver_cell_count"] == 20
    assert tip_receiver["tip_receiver_status"] == "span_cap_receiver_accounting_ready"
    assert tip_receiver["receiver_boundary_role_counts"]["bl_span_cap_match"] == 20
    assert tip_receiver["receiver_boundary_role_counts"]["core_tip_receiver_outer"] == 20
    assert tip_receiver["receiver_side_boundary_role_counts"]["physical_wall_edge_receiver"] == 6
    assert tip_receiver["receiver_side_boundary_role_counts"]["core_outer_edge_receiver"] == 10
    assert tip_receiver["receiver_side_boundary_role_counts"]["wake_edge_receiver"] == 12
    assert probe["verdict"] == "tip_receiver_accounting_ready_not_handoff"
    assert probe["coefficient_interpretable"] is False
    assert probe["goal_status"] == "INCOMPLETE"
    assert probe["cfd_status"] == "mesh_ladder_incomplete"


def test_tip_receiver_run_writes_span_cap_accounting_artifacts(tmp_path: Path) -> None:
    module = _load_module()

    summary = module.run_probe(
        output_dir=tmp_path / "wo006aa",
        points_per_side=8,
        spanwise_subdivisions=1,
    )

    assert summary["verdict"] == "tip_receiver_accounting_ready_not_handoff"
    assert summary["tip_receiver"]["remaining_bl_span_cap_face_count"] == 0
    assert summary["tip_receiver"]["tip_receiver_cell_count"] > 0
    assert summary["tip_receiver"]["receiver_side_boundary_role_counts"][
        "physical_wall_edge_receiver"
    ] > 0
    assert summary["owned_bl_block"]["boundary_marker_counts"]["span_cap"] > 0
    assert (tmp_path / "wo006aa" / "summary.json").exists()
    assert (tmp_path / "wo006aa" / "tip_receiver_report.md").exists()
